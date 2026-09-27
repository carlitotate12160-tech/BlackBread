"""Read-only leaf census of two caller-pinned Git trees.

Given a repository locator and two immutable commit SHA-1 pins selected by
the caller, the collector reads each pinned commit, follows its root tree
link, fetches every reachable tree object non-recursively, rejects
truncation, validates every entry, and recomputes each tree's Git object
identity from its ordered raw entries before trusting its contents. Each
side yields a separately sorted leaf census whose canonical path bytes are
base64-encoded next to the Git mode, object kind, and object SHA-1. A pure
reconciler joins both sides into one deterministic entry per unioned path
byte with an ADDED, DELETED, MODIFIED, or UNCHANGED status.

Trust boundary: the caller owns pin selection and freshness. The pins are
inputs, not proof of protected origin, PR currency, review state, or
permission; this collector reads no moving ref and makes no freshness claim.
Only leaf facts are emitted -- blob contents are never fetched, no rename or
legal-origin lineage is derived, and the caller-constructible result grants
no admission, merge, or target authority. The reconciler performs no I/O and
authenticates nothing: it keys by decoded path bytes, rejects duplicate or
non-canonical leaf order instead of overwriting entries, and passes census
pins and leaf contents through verbatim.
"""

from __future__ import annotations

import base64
import hashlib
import re
from enum import StrEnum
from typing import Any, NamedTuple, NoReturn, cast

from blackbread.governance.github_merge_transport import (
    GitHubReadTransport,
    TransportError,
    TransportResult,
)

_OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_SHA1_RE = re.compile(r"[0-9a-f]{40}")
_TREE_MODE = "040000"
_MODES = {
    _TREE_MODE: "tree",
    "100644": "blob",
    "100755": "blob",
    "120000": "blob",
    "160000": "commit",
}
_MAX_TREES = 512
_MAX_ENTRIES = 10000
_MAX_DEPTH = 32
_MAX_PATH_BYTES = 4096
_MAX_COMPONENT_BYTES = 1024
_OK_STATUS = 200
_CONTROL_LIMIT = 32
_DELETE_BYTE = 127
_UNSAFE_BYTES = frozenset({47, 92})


class GitTreeCensusError(Exception):
    """Sanitized census failure; the code is stable and input-free."""

    def __init__(self, code: str) -> None:
        super().__init__(f"Git-tree census failed: {code}")
        self.code = code


class TreeLeaf(NamedTuple):
    """One non-tree Git entry; canonical path bytes are verbatim in base64."""

    path_base64: str
    mode: str
    kind: str
    object_sha1: str


class GitTreeCensus(NamedTuple):
    """Caller-constructible leaf facts for two pinned trees; no authority."""

    repository: str
    base_commit_sha1: str
    head_commit_sha1: str
    base_tree_sha1: str
    head_tree_sha1: str
    base_leaves: tuple[TreeLeaf, ...]
    head_leaves: tuple[TreeLeaf, ...]


class LeafStatus(StrEnum):
    """Reconciliation status for one unioned path; a fact, never a decision."""

    ADDED = "ADDED"
    DELETED = "DELETED"
    MODIFIED = "MODIFIED"
    UNCHANGED = "UNCHANGED"


class CensusEntry(NamedTuple):
    """One unioned path row; each side's leaf passes through verbatim or None."""

    path_base64: str
    status: LeafStatus
    base_leaf: TreeLeaf | None
    head_leaf: TreeLeaf | None


class GitTreeInventory(NamedTuple):
    """Deterministic path union of both census sides; data only, no authority."""

    repository: str
    base_commit_sha1: str
    head_commit_sha1: str
    base_tree_sha1: str
    head_tree_sha1: str
    entries: tuple[CensusEntry, ...]


def _fail(code: str) -> NoReturn:
    raise GitTreeCensusError(code) from None


def _require(condition: bool, code: str = "MALFORMED_RESPONSE") -> None:
    if not condition:
        _fail(code)


def _repository_parts(repository: str) -> tuple[str, str]:
    if not isinstance(repository, str) or repository.count("/") != 1:
        _fail("INVALID_REPOSITORY")
    owner, name = repository.split("/")
    valid = _OWNER_RE.fullmatch(owner) and _NAME_RE.fullmatch(name)
    _require(bool(valid) and name not in {".", ".."}, "INVALID_REPOSITORY")
    return owner, name


def _commit_pin(value: str) -> str:
    _require(
        isinstance(value, str) and _SHA1_RE.fullmatch(value) is not None,
        "INVALID_COMMIT_PIN",
    )
    return value


def _get(transport: GitHubReadTransport, path: str) -> dict[str, Any]:
    try:
        result = transport.rest_get(path)
    except TransportError:
        _fail("TRANSPORT_FAILURE")
    _require(isinstance(result, TransportResult))
    _require(result.status == _OK_STATUS and result.next_url is None)
    _require(isinstance(result.body, dict))
    return cast("dict[str, Any]", result.body)


def _hex_sha1(value: Any) -> str:
    _require(isinstance(value, str) and _SHA1_RE.fullmatch(value) is not None)
    return cast(str, value)


def _commit_tree_sha(transport: GitHubReadTransport, repo_path: str, commit_sha: str) -> str:
    body = _get(transport, f"{repo_path}/git/commits/{commit_sha}")
    _require(body.get("sha") == commit_sha, "OBJECT_IDENTITY_MISMATCH")
    tree = body.get("tree")
    return _hex_sha1(tree.get("sha") if isinstance(tree, dict) else None)


def _component(value: Any) -> bytes:
    _require(isinstance(value, str), "UNSAFE_PATH")
    try:
        name = cast(str, value).encode()
    except UnicodeEncodeError:
        _fail("UNSAFE_PATH")
    _require(
        bool(name)
        and len(name) <= _MAX_COMPONENT_BYTES
        and name not in {b".", b".."}
        and name.lower() != b".git"
        and not any(
            byte < _CONTROL_LIMIT or byte == _DELETE_BYTE or byte in _UNSAFE_BYTES for byte in name
        ),
        "UNSAFE_PATH",
    )
    return name


def _nodes(raw: Any, prefix_len: int) -> list[tuple[bytes, str, str, str]]:
    _require(isinstance(raw, list))
    nodes: list[tuple[bytes, str, str, str]] = []
    for item in cast("list[Any]", raw):
        _require(isinstance(item, dict))
        entry = cast("dict[str, Any]", item)
        name = _component(entry.get("path"))
        mode = entry.get("mode")
        _require(isinstance(mode, str) and mode in _MODES, "OBJECT_KIND_MISMATCH")
        kind = _MODES[cast(str, mode)]
        _require(entry.get("type") == kind, "OBJECT_KIND_MISMATCH")
        nodes.append((name, cast(str, mode), kind, _hex_sha1(entry.get("sha"))))
        _require(prefix_len + len(name) <= _MAX_PATH_BYTES, "RESOURCE_BOUND")
    _require(len({node[0] for node in nodes}) == len(nodes), "DUPLICATE_PATH")
    return nodes


def _verify_tree_id(tree_sha: str, nodes: list[tuple[bytes, str, str, str]]) -> None:
    # Git tree identity: directories sort as name+"/" and modes lose their
    # leading zero; SHA-1 here is the protocol preimage, not a security choice.
    ordered = sorted(nodes, key=lambda node: node[0] + (b"/" if node[1] == _TREE_MODE else b""))
    payload = b"".join(
        mode.lstrip("0").encode("ascii") + b" " + name + b"\0" + bytes.fromhex(sha)
        for name, mode, _kind, sha in ordered
    )
    frame = b"tree " + str(len(payload)).encode("ascii") + b"\0" + payload
    _require(
        hashlib.sha1(frame, usedforsecurity=False).hexdigest() == tree_sha,
        "OBJECT_IDENTITY_MISMATCH",
    )


def _leaf(path: bytes, mode: str, kind: str, sha: str) -> TreeLeaf:
    return TreeLeaf(base64.b64encode(path).decode("ascii"), mode, kind, sha)


class _TreeWalker:
    """Depth-first walk of pinned trees; bounds apply across the whole call."""

    def __init__(self, transport: GitHubReadTransport, repo_path: str) -> None:
        self.transport = transport
        self.repo_path = repo_path
        self.trees = 0
        self.entries = 0

    def collect(
        self, tree_sha: str, prefix: bytes = b"", depth: int = 0
    ) -> list[tuple[bytes, TreeLeaf]]:
        self.trees += 1
        _require(self.trees <= _MAX_TREES and depth <= _MAX_DEPTH, "RESOURCE_BOUND")
        body = _get(self.transport, f"{self.repo_path}/git/trees/{tree_sha}")
        _require(body.get("sha") == tree_sha, "OBJECT_IDENTITY_MISMATCH")
        _require(body.get("truncated") is False, "TRUNCATED_TREE")
        nodes = _nodes(body.get("tree"), len(prefix))
        self.entries += len(nodes)
        _require(self.entries <= _MAX_ENTRIES, "RESOURCE_BOUND")
        _verify_tree_id(tree_sha, nodes)
        leaves: list[tuple[bytes, TreeLeaf]] = []
        for name, mode, kind, sha in nodes:
            path = prefix + name
            if mode == _TREE_MODE:
                leaves.extend(self.collect(sha, path + b"/", depth + 1))
            else:
                leaves.append((path, _leaf(path, mode, kind, sha)))
        return sorted(leaves, key=lambda pair: pair[0])


def collect_git_tree_census(
    transport: GitHubReadTransport,
    repository: str,
    base_commit_sha1: str,
    head_commit_sha1: str,
) -> GitTreeCensus:
    """Census every leaf under two caller-pinned commits in ``repository``.

    Both pins must be full lowercase SHA-1 hex; they are inputs, never proof
    of protected origin or freshness. Every failure raises
    ``GitTreeCensusError`` with a stable code and yields no partial result.
    """
    owner, name = _repository_parts(repository)
    base_sha = _commit_pin(base_commit_sha1)
    head_sha = _commit_pin(head_commit_sha1)
    repo_path = f"/repos/{owner}/{name}"
    base_tree = _commit_tree_sha(transport, repo_path, base_sha)
    head_tree = _commit_tree_sha(transport, repo_path, head_sha)
    walker = _TreeWalker(transport, repo_path)
    base_leaves = tuple(leaf for _raw, leaf in walker.collect(base_tree))
    head_leaves = tuple(leaf for _raw, leaf in walker.collect(head_tree))
    return GitTreeCensus(
        repository=repository,
        base_commit_sha1=base_sha,
        head_commit_sha1=head_sha,
        base_tree_sha1=base_tree,
        head_tree_sha1=head_tree,
        base_leaves=base_leaves,
        head_leaves=head_leaves,
    )


def _well_formed_leaf(leaf: TreeLeaf) -> bool:
    """Check a leaf carries a real non-tree mode, matching kind, and SHA-1."""
    return (
        isinstance(leaf.mode, str)
        and leaf.mode in _MODES
        and leaf.mode != _TREE_MODE
        and leaf.kind == _MODES[leaf.mode]
        and isinstance(leaf.object_sha1, str)
        and _SHA1_RE.fullmatch(leaf.object_sha1) is not None
    )


def _canonical_leaves(leaves: tuple[TreeLeaf, ...] | list[TreeLeaf]) -> dict[bytes, TreeLeaf]:
    """Validate leaf shape and require canonical unique sorted path order."""
    _require(isinstance(leaves, (tuple, list)), "MALFORMED_CENSUS")
    decoded: dict[bytes, TreeLeaf] = {}
    previous: bytes | None = None
    for leaf in leaves:
        _require(isinstance(leaf, TreeLeaf), "MALFORMED_CENSUS")
        encoded = leaf.path_base64
        _require(isinstance(encoded, str), "MALFORMED_CENSUS")
        _require(_well_formed_leaf(leaf), "MALFORMED_CENSUS")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError:
            _fail("MALFORMED_CENSUS")
        _require(
            bool(raw) and base64.b64encode(raw).decode("ascii") == encoded,
            "MALFORMED_CENSUS",
        )
        if previous is not None and raw == previous:
            _fail("DUPLICATE_PATH")
        _require(previous is None or previous < raw, "NONCANONICAL_CENSUS")
        decoded[raw] = leaf
        previous = raw
    return decoded


def reconcile_git_tree_census(census: GitTreeCensus) -> GitTreeInventory:
    """Join both leaf sides into one sorted entry per unioned path byte.

    Pure function over caller-supplied data: it reads no moving ref and
    performs no I/O. Census pins pass through unverified and leaf contents
    are preserved verbatim; identical leaf identity yields UNCHANGED and any
    difference in mode, kind, or object SHA-1 yields MODIFIED. No rename or
    origin lineage is inferred. Malformed leaves, duplicated paths, or a
    non-canonical leaf order fail closed with no partial inventory.
    """
    _require(isinstance(census, GitTreeCensus), "MALFORMED_CENSUS")
    base = _canonical_leaves(census.base_leaves)
    head = _canonical_leaves(census.head_leaves)
    entries: list[CensusEntry] = []
    for path in sorted(set(base) | set(head)):
        base_leaf = base.get(path)
        head_leaf = head.get(path)
        if base_leaf is None:
            status = LeafStatus.ADDED
        elif head_leaf is None:
            status = LeafStatus.DELETED
        elif base_leaf == head_leaf:
            status = LeafStatus.UNCHANGED
        else:
            status = LeafStatus.MODIFIED
        entries.append(
            CensusEntry(
                path_base64=base64.b64encode(path).decode("ascii"),
                status=status,
                base_leaf=base_leaf,
                head_leaf=head_leaf,
            )
        )
    return GitTreeInventory(
        repository=census.repository,
        base_commit_sha1=census.base_commit_sha1,
        head_commit_sha1=census.head_commit_sha1,
        base_tree_sha1=census.base_tree_sha1,
        head_tree_sha1=census.head_tree_sha1,
        entries=tuple(entries),
    )
