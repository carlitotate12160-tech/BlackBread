"""Protected-main policy-source loader proofs (GOV-IP-PROVENANCE-001B2a)."""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

import blackbread.governance.source_admission_policy_source as policy_source_module
from blackbread.governance.github_merge_transport import TransportError, TransportResult
from blackbread.governance.source_admission_contracts import SourcePolicyRef
from blackbread.governance.source_admission_policy import (
    ProcessorProfile,
    SourceAdmissionPolicy,
    UseProfile,
    compute_policy_digest,
    parse_policy_bytes,
)
from blackbread.governance.source_admission_policy_source import (
    PolicySourceError,
    ProtectedPolicySource,
    load_protected_main_policy,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY_BYTES = (ROOT / "config" / "source-admission-policy.json").read_bytes()
KNOWN_DIGEST = "ab0f6408d257fd8a5a38ddc5582900aad45be2ae2c438e1d7697cfcb75523463"
REPO_PATH = "/repos/owner/repo"
BRANCH_PATH = f"{REPO_PATH}/branches/main"
MAIN_SHA = "a" * 40
ALT_SHA = "b" * 40
TREE_SHA = "c" * 40
CONFIG_TREE_SHA = "d" * 40
OTHER_SHA = "e" * 40
CANARY = "ghp_candidate_secret_0000"


def _git_blob_sha(content: bytes) -> str:
    # Git object identity is the protocol-mandated SHA-1 framing.
    frame = b"blob " + str(len(content)).encode("ascii") + b"\0" + content
    return hashlib.sha1(frame, usedforsecurity=False).hexdigest()


BLOB_SHA = _git_blob_sha(POLICY_BYTES)
EXPECTED_CALLS = [
    BRANCH_PATH,
    f"{REPO_PATH}/git/commits/{MAIN_SHA}",
    f"{REPO_PATH}/git/trees/{TREE_SHA}",
    f"{REPO_PATH}/git/trees/{CONFIG_TREE_SHA}",
    f"{REPO_PATH}/git/blobs/{BLOB_SHA}",
    BRANCH_PATH,
]


def _result(body: Any, next_url: str | None = None) -> TransportResult:
    return TransportResult(status=200, body=body, next_url=next_url)


def _branch(sha: str = MAIN_SHA, protected: bool = True) -> dict[str, Any]:
    return {"name": "main", "protected": protected, "commit": {"sha": sha}}


def _entry(path: str, mode: str, kind: str, sha: str) -> dict[str, Any]:
    return {"path": path, "mode": mode, "type": kind, "sha": sha}


def _tree_body(sha: str, entries: list[dict[str, Any]], truncated: bool = False) -> dict[str, Any]:
    return {"sha": sha, "truncated": truncated, "tree": entries}


def _root_tree(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    default = [_entry("config", "040000", "tree", CONFIG_TREE_SHA)]
    return _tree_body(TREE_SHA, entries if entries is not None else default)


def _config_tree(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    default = [_entry("source-admission-policy.json", "100644", "blob", BLOB_SHA)]
    return _tree_body(CONFIG_TREE_SHA, entries if entries is not None else default)


def _blob_body(content: bytes = POLICY_BYTES, sha: str | None = None) -> dict[str, Any]:
    return {
        "sha": sha if sha is not None else _git_blob_sha(content),
        "encoding": "base64",
        "size": len(content),
        "content": base64.b64encode(content).decode("ascii"),
    }


def _default_responses() -> dict[str, TransportResult | Exception]:
    return {
        f"{REPO_PATH}/git/commits/{MAIN_SHA}": _result(
            {"sha": MAIN_SHA, "tree": {"sha": TREE_SHA}}
        ),
        f"{REPO_PATH}/git/trees/{TREE_SHA}": _result(_root_tree()),
        f"{REPO_PATH}/git/trees/{CONFIG_TREE_SHA}": _result(_config_tree()),
        f"{REPO_PATH}/git/blobs/{BLOB_SHA}": _result(_blob_body()),
    }


class _FakeTransport:
    """Scripted GitHubReadTransport; unscripted paths fail like a 404."""

    def __init__(
        self,
        responses: dict[str, TransportResult | Exception] | None = None,
        branch_bodies: list[Any] | None = None,
    ) -> None:
        self._responses = responses if responses is not None else _default_responses()
        self._branch_bodies = (
            list(branch_bodies) if branch_bodies is not None else [_branch(), _branch()]
        )
        self.rest_calls: list[str] = []
        self.graphql_calls: list[tuple[str, Any]] = []
        self._branch_reads = 0

    def rest_get(self, path_or_url: str, params: dict[str, str] | None = None) -> TransportResult:
        self.rest_calls.append(path_or_url)
        if path_or_url == BRANCH_PATH:
            index = min(self._branch_reads, len(self._branch_bodies) - 1)
            self._branch_reads += 1
            body = self._branch_bodies[index]
            if isinstance(body, Exception):
                raise body
            return _result(body)
        item = self._responses.get(path_or_url, TransportError("unexpected HTTP status"))
        if isinstance(item, Exception):
            raise item
        return item

    def graphql_query(
        self, document: str, variables: dict[str, Any] | None = None
    ) -> TransportResult:
        self.graphql_calls.append((document, variables))
        raise TransportError("graphql unsupported")


def _load(
    transport: _FakeTransport | None = None,
    repository: str = "owner/repo",
    sha: str = MAIN_SHA,
    use: UseProfile = UseProfile.ENGINEERING_REVIEW,
) -> ProtectedPolicySource:
    return load_protected_main_policy(transport or _FakeTransport(), repository, sha, use)


def _assert_code(code: str, **kwargs: Any) -> PolicySourceError:
    with pytest.raises(PolicySourceError) as excinfo:
        _load(**kwargs)
    assert excinfo.value.code == code
    return excinfo.value


def test_protected_main_policy_loads_with_exact_bindings() -> None:
    fake = _FakeTransport()
    result = _load(fake)
    assert isinstance(result.policy, SourceAdmissionPolicy)
    assert isinstance(result.policy_ref, SourcePolicyRef)
    assert result.policy.policy_id == "blackbread-source-admission"
    ref = result.policy_ref
    assert ref.policy_id == result.policy.policy_id
    assert ref.policy_version == result.policy.policy_version
    assert ref.source_commit_sha1 == MAIN_SHA
    assert ref.source_blob_sha1 == BLOB_SHA
    assert ref.policy_sha256 == KNOWN_DIGEST
    assert ref.use_profile is UseProfile.ENGINEERING_REVIEW
    assert ref.processor_profile is ProcessorProfile.LOCAL_ONLY
    assert ref.retention == result.policy.retention
    assert fake.rest_calls == EXPECTED_CALLS
    assert fake.graphql_calls == []


def test_candidate_checkout_policy_is_never_consulted(tmp_path: Path) -> None:
    # A permissive policy planted in a candidate checkout changes nothing:
    # the loader has no path input and only ever reads fixed API routes.
    candidate = tmp_path / "config" / "source-admission-policy.json"
    candidate.parent.mkdir(parents=True)
    raw = json.loads(POLICY_BYTES.decode("utf-8"))
    raw["unknown_default"] = "POTENTIALLY_ADMISSIBLE"
    raw["unknown_admissible"] = True
    candidate_bytes = json.dumps(raw).encode("utf-8")
    candidate.write_bytes(candidate_bytes)
    candidate_digest = compute_policy_digest(parse_policy_bytes(candidate_bytes))
    assert candidate_digest != KNOWN_DIGEST
    fake = _FakeTransport()
    result = _load(fake)
    assert result.policy_ref.policy_sha256 == KNOWN_DIGEST
    assert fake.rest_calls == EXPECTED_CALLS
    assert all(call.startswith(REPO_PATH + "/") for call in fake.rest_calls)
    parameters = inspect.signature(load_protected_main_policy).parameters
    assert all("path" not in name and "checkout" not in name for name in parameters)


def test_alternate_valid_main_sha_is_rejected() -> None:
    error = _assert_code(
        "EXPECTED_SHA_MISMATCH", transport=_FakeTransport(branch_bodies=[_branch(sha=ALT_SHA)])
    )
    assert ALT_SHA not in str(error)


def test_unprotected_branch_is_rejected() -> None:
    _assert_code(
        "BRANCH_UNPROTECTED",
        transport=_FakeTransport(branch_bodies=[_branch(protected=False)]),
    )


@pytest.mark.parametrize(
    "second",
    [_branch(sha=ALT_SHA), _branch(protected=False)],
    ids=["moved_sha", "protection_lifted"],
)
def test_main_moving_between_reads_invalidates(second: dict[str, Any]) -> None:
    fake = _FakeTransport(branch_bodies=[_branch(), second])
    _assert_code("MAIN_MOVED", transport=fake)
    assert fake.rest_calls.count(BRANCH_PATH) == 2


def _replace_root(responses: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    key = f"{REPO_PATH}/git/trees/{TREE_SHA}"
    responses[key] = _result(_root_tree(entries=entries))


def _replace_leaf(responses: dict[str, Any], entry: dict[str, Any]) -> None:
    key = f"{REPO_PATH}/git/trees/{CONFIG_TREE_SHA}"
    responses[key] = _result(_config_tree(entries=[entry]))


def _replace_blob(responses: dict[str, Any], body: dict[str, Any]) -> None:
    responses[f"{REPO_PATH}/git/blobs/{BLOB_SHA}"] = _result(body)


def _commit_sha_mismatch(responses: dict[str, Any]) -> None:
    key = f"{REPO_PATH}/git/commits/{MAIN_SHA}"
    responses[key] = _result({"sha": ALT_SHA, "tree": {"sha": TREE_SHA}})


def _commit_tree_missing(responses: dict[str, Any]) -> None:
    responses[f"{REPO_PATH}/git/commits/{MAIN_SHA}"] = _result({"sha": MAIN_SHA})


def _config_not_tree(responses: dict[str, Any]) -> None:
    _replace_root(responses, [_entry("config", "100644", "blob", CONFIG_TREE_SHA)])


def _config_missing(responses: dict[str, Any]) -> None:
    _replace_root(responses, [_entry("other", "040000", "tree", OTHER_SHA)])


def _config_duplicated(responses: dict[str, Any]) -> None:
    pair = _entry("config", "040000", "tree", CONFIG_TREE_SHA)
    _replace_root(responses, [pair, pair])


def _tree_sha_mismatch(responses: dict[str, Any]) -> None:
    key = f"{REPO_PATH}/git/trees/{TREE_SHA}"
    responses[key] = _result(_tree_body(OTHER_SHA, _root_tree()["tree"]))


def _tree_truncated(responses: dict[str, Any]) -> None:
    key = f"{REPO_PATH}/git/trees/{TREE_SHA}"
    responses[key] = _result(_tree_body(TREE_SHA, _root_tree()["tree"], truncated=True))


def _leaf_missing(responses: dict[str, Any]) -> None:
    _replace_leaf(responses, _entry("unrelated.txt", "100644", "blob", OTHER_SHA))


def _leaf_symlink(responses: dict[str, Any]) -> None:
    _replace_leaf(responses, _entry("source-admission-policy.json", "120000", "blob", BLOB_SHA))


def _leaf_submodule(responses: dict[str, Any]) -> None:
    _replace_leaf(responses, _entry("source-admission-policy.json", "160000", "commit", OTHER_SHA))


def _leaf_sha_malformed(responses: dict[str, Any]) -> None:
    _replace_leaf(responses, _entry("source-admission-policy.json", "100644", "blob", "not-hex"))


def _blob_alternate_object(responses: dict[str, Any]) -> None:
    responses[f"{REPO_PATH}/git/blobs/{ALT_SHA}"] = TransportError(
        "unexpected HTTP status", status=404
    )
    _replace_leaf(responses, _entry("source-admission-policy.json", "100644", "blob", ALT_SHA))


def _blob_sha_lie(responses: dict[str, Any]) -> None:
    _replace_blob(responses, _blob_body(sha=ALT_SHA))


def _blob_bytes_substituted(responses: dict[str, Any]) -> None:
    # Response claims the pinned blob SHA and a matching size for its own
    # bytes, but the recomputed Git identity cannot match the claimed SHA.
    forged = _blob_body(content=b"{}")
    forged["sha"] = BLOB_SHA
    forged["size"] = len(b"{}")
    _replace_blob(responses, forged)


def _blob_encoding_utf8(responses: dict[str, Any]) -> None:
    _replace_blob(responses, {**_blob_body(), "encoding": "utf-8"})


def _blob_content_not_base64(responses: dict[str, Any]) -> None:
    _replace_blob(responses, {**_blob_body(), "content": "!!!not-base64!!!"})


def _blob_size_lie(responses: dict[str, Any]) -> None:
    _replace_blob(responses, {**_blob_body(), "size": len(POLICY_BYTES) + 1})


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (_commit_sha_mismatch, "OBJECT_IDENTITY_MISMATCH"),
        (_commit_tree_missing, "MALFORMED_RESPONSE"),
        (_config_not_tree, "OBJECT_KIND_MISMATCH"),
        (_config_missing, "OBJECT_PATH_MISSING"),
        (_config_duplicated, "MALFORMED_RESPONSE"),
        (_tree_sha_mismatch, "OBJECT_IDENTITY_MISMATCH"),
        (_tree_truncated, "TRUNCATED_TREE"),
        (_leaf_missing, "OBJECT_PATH_MISSING"),
        (_leaf_symlink, "OBJECT_KIND_MISMATCH"),
        (_leaf_submodule, "OBJECT_KIND_MISMATCH"),
        (_leaf_sha_malformed, "MALFORMED_RESPONSE"),
        (_blob_alternate_object, "TRANSPORT_FAILURE"),
        (_blob_sha_lie, "OBJECT_IDENTITY_MISMATCH"),
        (_blob_bytes_substituted, "OBJECT_IDENTITY_MISMATCH"),
        (_blob_encoding_utf8, "MALFORMED_RESPONSE"),
        (_blob_content_not_base64, "MALFORMED_RESPONSE"),
        (_blob_size_lie, "OBJECT_IDENTITY_MISMATCH"),
    ],
)
def test_object_checks_fail_closed(mutation: Any, code: str) -> None:
    responses = _default_responses()
    mutation(responses)
    _assert_code(code, transport=_FakeTransport(responses=responses))


@pytest.mark.parametrize(
    "body",
    [
        ["not", "a", "dict"],
        {"name": "main", "protected": True, "commit": {"sha": "z" * 40}},
        {**_branch(), "protected": "yes"},
    ],
    ids=["list_body", "non_hex_commit_sha", "non_boolean_protected"],
)
def test_malformed_branch_shapes_fail_closed(body: Any) -> None:
    _assert_code("MALFORMED_RESPONSE", transport=_FakeTransport(branch_bodies=[body]))


def test_paginated_single_object_responses_are_rejected() -> None:
    responses = _default_responses()
    key = f"{REPO_PATH}/git/commits/{MAIN_SHA}"
    responses[key] = _result(
        {"sha": MAIN_SHA, "tree": {"sha": TREE_SHA}},
        next_url="https://api.github.com" + key + "?page=2",
    )
    _assert_code("MALFORMED_RESPONSE", transport=_FakeTransport(responses=responses))


def test_executable_bit_blob_remains_a_regular_file() -> None:
    responses = _default_responses()
    key = f"{REPO_PATH}/git/trees/{CONFIG_TREE_SHA}"
    exe = _entry("source-admission-policy.json", "100755", "blob", BLOB_SHA)
    responses[key] = _result(_config_tree(entries=[exe]))
    assert _load(_FakeTransport(responses=responses)).policy_ref.source_blob_sha1 == BLOB_SHA


def test_changed_policy_bytes_with_consistent_parse_still_fail_on_identity() -> None:
    # Even self-consistent substituted policy bytes cannot match the pinned
    # blob identity: the served object hash disagrees with the tree's SHA.
    tampered = b'{"schema_version": 2}'
    tampered_sha = _git_blob_sha(tampered)
    responses = _default_responses()
    key = f"{REPO_PATH}/git/trees/{CONFIG_TREE_SHA}"
    alt = _entry("source-admission-policy.json", "100644", "blob", tampered_sha)
    responses[key] = _result(_config_tree(entries=[alt]))
    responses[f"{REPO_PATH}/git/blobs/{tampered_sha}"] = _result(_blob_body(content=tampered))
    error = _assert_code("POLICY_SCHEMA_UNSUPPORTED", transport=_FakeTransport(responses=responses))
    assert "2" not in str(error)


def test_transport_error_never_leaks_token_or_body() -> None:
    responses = _default_responses()
    responses[f"{REPO_PATH}/git/blobs/{BLOB_SHA}"] = TransportError(
        f"upstream said {CANARY} near body"
    )
    error = _assert_code("TRANSPORT_FAILURE", transport=_FakeTransport(responses=responses))
    assert CANARY not in str(error)
    assert "body" not in str(error)


@pytest.mark.parametrize(
    "repository",
    ["owner", "owner/repo/extra", "owner/repo?x=1", "../repo", "owner/../x"],
)
def test_invalid_repository_causes_zero_io(repository: str) -> None:
    fake = _FakeTransport()
    error = _assert_code("INVALID_REPOSITORY", transport=fake, repository=repository)
    assert repository not in str(error)
    assert fake.rest_calls == []


@pytest.mark.parametrize("sha", ["", "A" * 40, "g" * 40, "a" * 39, 9619])
def test_invalid_expected_sha_causes_zero_io(sha: Any) -> None:
    fake = _FakeTransport()
    _assert_code("INVALID_EXPECTED_SHA", transport=fake, sha=sha)
    assert fake.rest_calls == []


def test_unlisted_use_profile_is_rejected() -> None:
    _assert_code("USE_PROFILE_NOT_PERMITTED", use=UseProfile.PUBLIC_DISTRIBUTION)


def test_result_is_caller_constructible_and_grants_no_authority() -> None:
    result = _load()
    assert isinstance(result, ProtectedPolicySource)
    assert result._fields == ("policy", "policy_ref")
    public = {name for name in vars(policy_source_module) if not name.startswith("_")}
    assert not hasattr(result, "is_authoritative")
    assert not hasattr(result.policy_ref, "verify_digest")
    assert not any(name.lower() in {"merge", "execute", "authorize", "write"} for name in public)
