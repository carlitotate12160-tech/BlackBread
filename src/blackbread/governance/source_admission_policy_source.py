"""Read-only loader binding the admission policy to a protected-main commit.

Given a controller-pinned repository and expected ``main`` commit SHA, the
loader reads the branch through the authenticated GitHub read transport,
requires its reported protected flag and the exact pinned SHA, follows the
commit's tree to the fixed policy path, requires a regular blob, retrieves
and identity-checks its bytes, strictly parses the policy, and derives its
semantic digest. Branch ``main`` is re-read before returning; a moved branch
or lifted protection invalidates the result.

Trust boundary: the expected SHA is a pin, not proof of protected origin.
Nothing here reads the candidate checkout -- the policy path is a module
constant and every request is a fixed path under the pinned repository; no
arbitrary URL, symlink, or submodule is ever followed. The returned objects
are caller-constructible and grant no admission, review, merge, or target
authority; the semantic digest proves content consistency only, never owner
authentication, freshness, or permission. A later composed consumer must
still recheck freshness and evaluate the same policy and bundle inside its
own call.
"""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any, NamedTuple, NoReturn, cast

from blackbread.governance.github_merge_transport import (
    GitHubReadTransport,
    TransportError,
    TransportResult,
)
from blackbread.governance.source_admission_contracts import SourcePolicyRef
from blackbread.governance.source_admission_policy import (
    PolicyValidationError,
    SourceAdmissionPolicy,
    UseProfile,
    compute_policy_digest,
    parse_policy_bytes,
)

_POLICY_SEGMENTS = ("config", "source-admission-policy.json")
_BLOB_MODES = frozenset({"100644", "100755"})
_TREE_MODES = frozenset({"040000"})
_OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_SHA1_RE = re.compile(r"[0-9a-f]{40}")


class PolicySourceError(Exception):
    """Sanitized policy-source failure; the message embeds no remote content."""

    def __init__(self, code: str) -> None:
        super().__init__(f"policy source retrieval failed: {code}")
        self.code = code


class ProtectedPolicySource(NamedTuple):
    """A parsed policy and its provenance reference; confers no authority."""

    policy: SourceAdmissionPolicy
    policy_ref: SourcePolicyRef


def _fail(code: str) -> NoReturn:
    raise PolicySourceError(code) from None


def _require(condition: bool, code: str) -> None:
    if not condition:
        _fail(code)


def _repository_parts(repository: str) -> tuple[str, str]:
    if not isinstance(repository, str) or repository.count("/") != 1:
        _fail("INVALID_REPOSITORY")
    owner, name = repository.split("/")
    valid = _OWNER_RE.fullmatch(owner) and _NAME_RE.fullmatch(name)
    _require(bool(valid) and name not in {".", ".."}, "INVALID_REPOSITORY")
    return owner, name


def _get(transport: GitHubReadTransport, path: str) -> Any:
    try:
        result = transport.rest_get(path)
    except TransportError:
        _fail("TRANSPORT_FAILURE")
    _require(isinstance(result, TransportResult), "MALFORMED_RESPONSE")
    _require(result.next_url is None, "MALFORMED_RESPONSE")
    return result.body


def _hex_sha1(value: Any, code: str = "MALFORMED_RESPONSE") -> str:
    _require(isinstance(value, str) and _SHA1_RE.fullmatch(value) is not None, code)
    return cast(str, value)


def _read_main_branch(transport: GitHubReadTransport, repo_path: str) -> tuple[str, bool]:
    body = _get(transport, f"{repo_path}/branches/main")
    _require(isinstance(body, dict), "MALFORMED_RESPONSE")
    _require(body.get("name") == "main", "MALFORMED_RESPONSE")
    commit = body.get("commit")
    sha = _hex_sha1(commit.get("sha") if isinstance(commit, dict) else None)
    protected = body.get("protected")
    _require(isinstance(protected, bool), "MALFORMED_RESPONSE")
    return sha, protected


def _commit_tree_sha(transport: GitHubReadTransport, repo_path: str, commit_sha: str) -> str:
    body = _get(transport, f"{repo_path}/git/commits/{commit_sha}")
    _require(isinstance(body, dict), "MALFORMED_RESPONSE")
    _require(body.get("sha") == commit_sha, "OBJECT_IDENTITY_MISMATCH")
    tree = body.get("tree")
    return _hex_sha1(tree.get("sha") if isinstance(tree, dict) else None)


def _tree_entry(
    transport: GitHubReadTransport, repo_path: str, tree_sha: str, segment: str
) -> dict[str, Any]:
    body = _get(transport, f"{repo_path}/git/trees/{tree_sha}")
    _require(isinstance(body, dict), "MALFORMED_RESPONSE")
    _require(body.get("sha") == tree_sha, "OBJECT_IDENTITY_MISMATCH")
    _require(body.get("truncated") is False, "TRUNCATED_TREE")
    entries = body.get("tree")
    _require(isinstance(entries, list), "MALFORMED_RESPONSE")
    _require(all(isinstance(item, dict) for item in entries), "MALFORMED_RESPONSE")
    matches = [item for item in entries if item.get("path") == segment]
    _require(bool(matches), "OBJECT_PATH_MISSING")
    _require(len(matches) == 1, "MALFORMED_RESPONSE")
    return cast("dict[str, Any]", matches[0])


def _entry_object_sha(entry: dict[str, Any], *, leaf: bool) -> str:
    kind = "blob" if leaf else "tree"
    modes = _BLOB_MODES if leaf else _TREE_MODES
    # A symlink (120000) or gitlink/submodule (160000) never reaches a fetch.
    _require(entry.get("type") == kind and entry.get("mode") in modes, "OBJECT_KIND_MISMATCH")
    return _hex_sha1(entry.get("sha"))


def _resolve_policy_blob_sha(transport: GitHubReadTransport, repo_path: str, tree_sha: str) -> str:
    current = tree_sha
    for index, segment in enumerate(_POLICY_SEGMENTS):
        entry = _tree_entry(transport, repo_path, current, segment)
        leaf = index == len(_POLICY_SEGMENTS) - 1
        current = _entry_object_sha(entry, leaf=leaf)
    return current


def _policy_blob_bytes(transport: GitHubReadTransport, repo_path: str, blob_sha: str) -> bytes:
    body = _get(transport, f"{repo_path}/git/blobs/{blob_sha}")
    _require(isinstance(body, dict), "MALFORMED_RESPONSE")
    _require(body.get("sha") == blob_sha, "OBJECT_IDENTITY_MISMATCH")
    _require(body.get("encoding") == "base64", "MALFORMED_RESPONSE")
    content = body.get("content")
    _require(isinstance(content, str), "MALFORMED_RESPONSE")
    try:
        raw = base64.b64decode("".join(content.split()), validate=True)
    except ValueError:
        _fail("MALFORMED_RESPONSE")
    size = body.get("size")
    _require(
        isinstance(size, int) and not isinstance(size, bool) and size == len(raw),
        "OBJECT_IDENTITY_MISMATCH",
    )
    # Git object identity: SHA-1 is the protocol-mandated preimage frame, not
    # a hash choice made for security here.
    frame = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    _require(
        hashlib.sha1(frame, usedforsecurity=False).hexdigest() == blob_sha,
        "OBJECT_IDENTITY_MISMATCH",
    )
    return raw


def _parse_policy(payload: bytes) -> SourceAdmissionPolicy:
    try:
        return parse_policy_bytes(payload)
    except PolicyValidationError as exc:
        # The inner codes are already stable and input-free; re-wrap under the
        # loader's exception type only.
        _fail(exc.code)


def _policy_ref(
    policy: SourceAdmissionPolicy, commit_sha: str, blob_sha: str, use: UseProfile
) -> SourcePolicyRef:
    _require(use in policy.use_profiles, "USE_PROFILE_NOT_PERMITTED")
    try:
        return SourcePolicyRef(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            source_commit_sha1=commit_sha,
            source_blob_sha1=blob_sha,
            policy_sha256=compute_policy_digest(policy),
            use_profile=use,
            processor_profile=policy.processor_profile,
            retention=policy.retention,
        )
    except ValueError:
        _fail("POLICY_REF_INVALID")


def load_protected_main_policy(
    transport: GitHubReadTransport,
    repository: str,
    expected_main_sha1: str,
    use_profile: UseProfile,
) -> ProtectedPolicySource:
    """Load the protected-main policy pinned to ``expected_main_sha1``.

    Every failure raises ``PolicySourceError`` with a stable code; transport
    details, credentials, and response bodies never appear in the error.
    """
    owner, name = _repository_parts(repository)
    _require(
        isinstance(expected_main_sha1, str) and _SHA1_RE.fullmatch(expected_main_sha1) is not None,
        "INVALID_EXPECTED_SHA",
    )
    repo_path = f"/repos/{owner}/{name}"
    sha, protected = _read_main_branch(transport, repo_path)
    _require(sha == expected_main_sha1, "EXPECTED_SHA_MISMATCH")
    _require(protected, "BRANCH_UNPROTECTED")
    tree_sha = _commit_tree_sha(transport, repo_path, expected_main_sha1)
    blob_sha = _resolve_policy_blob_sha(transport, repo_path, tree_sha)
    policy = _parse_policy(_policy_blob_bytes(transport, repo_path, blob_sha))
    policy_ref = _policy_ref(policy, expected_main_sha1, blob_sha, use_profile)
    sha_now, still_protected = _read_main_branch(transport, repo_path)
    _require(sha_now == expected_main_sha1 and still_protected, "MAIN_MOVED")
    return ProtectedPolicySource(policy=policy, policy_ref=policy_ref)
