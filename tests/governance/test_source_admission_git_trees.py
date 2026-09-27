"""Read-only pinned-commit Git-tree census proofs."""

from __future__ import annotations

import ast
import base64
import hashlib
import inspect
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from blackbread.governance.github_merge_transport import TransportError, TransportResult
from blackbread.governance.source_admission_git_trees import (
    CensusEntry,
    GitTreeCensus,
    GitTreeCensusError,
    GitTreeInventory,
    LeafStatus,
    TreeLeaf,
    collect_git_tree_census,
    reconcile_git_tree_census,
)

REPO = "owner/repo"
ROOT = f"/repos/{REPO}"
BASE = "a" * 40
HEAD = "b" * 40
OTHER = "c" * 40


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _path(leaf: TreeLeaf) -> bytes:
    return base64.b64decode(leaf.path_base64)


def _blob(raw: bytes) -> str:
    frame = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    return hashlib.sha1(frame, usedforsecurity=False).hexdigest()


def _entry(path: str, mode: str, sha: str) -> dict[str, str]:
    kind = "tree" if mode == "040000" else "commit" if mode == "160000" else "blob"
    return {"path": path, "mode": mode, "type": kind, "sha": sha}


def _tree(entries: list[dict[str, str]]) -> dict[str, Any]:
    preimage = b"".join(
        entry["mode"].lstrip("0").encode("ascii")
        + b" "
        + entry["path"].encode("utf-8")
        + b"\0"
        + bytes.fromhex(entry["sha"])
        for entry in sorted(
            entries,
            key=lambda item: (
                item["path"].encode("utf-8") + (b"/" if item["mode"] == "040000" else b"")
            ),
        )
    )
    frame = b"tree " + str(len(preimage)).encode("ascii") + b"\0" + preimage
    return {
        "sha": hashlib.sha1(frame, usedforsecurity=False).hexdigest(),
        "tree": entries,
        "truncated": False,
    }


class FakeTransport:
    def __init__(self) -> None:
        nested = _tree([_entry("main.py", "100644", _blob(b"print(1)"))])
        base_root = _tree(
            [
                _entry("src", "040000", nested["sha"]),
                _entry("readme.txt", "100644", _blob(b"base")),
                _entry("link", "120000", _blob(b"readme.txt")),
                _entry("vendor", "160000", OTHER),
            ]
        )
        head_root = _tree(
            [
                _entry("src", "040000", nested["sha"]),
                _entry("readme.txt", "100755", _blob(b"head")),
                _entry("link", "120000", _blob(b"readme.txt")),
                _entry("vendor", "160000", OTHER),
                _entry("café.txt", "100644", _blob(b"utf8")),
            ]
        )
        self.base_root = base_root["sha"]
        self.head_root = head_root["sha"]
        self.nested = nested["sha"]
        self.responses: dict[str, Any] = {
            f"{ROOT}/git/commits/{BASE}": {"sha": BASE, "tree": {"sha": self.base_root}},
            f"{ROOT}/git/commits/{HEAD}": {"sha": HEAD, "tree": {"sha": self.head_root}},
            f"{ROOT}/git/trees/{self.base_root}": base_root,
            f"{ROOT}/git/trees/{self.head_root}": head_root,
            f"{ROOT}/git/trees/{self.nested}": nested,
        }
        self.calls: list[str] = []

    def rest_get(self, path_or_url: str, params: Any = None) -> TransportResult:
        assert params is None
        self.calls.append(path_or_url)
        body = self.responses.get(path_or_url, TransportError("missing"))
        if isinstance(body, Exception):
            raise body
        if isinstance(body, TransportResult):
            return body
        return TransportResult(status=200, body=deepcopy(body), next_url=None)

    def graphql_query(self, document: str, variables: Any = None) -> TransportResult:
        raise AssertionError("collector must use REST GET only")


def _collect(fake: FakeTransport) -> GitTreeCensus:
    return collect_git_tree_census(fake, REPO, BASE, HEAD)


def _reject(fake: FakeTransport, code: str) -> None:
    with pytest.raises(GitTreeCensusError) as exc:
        _collect(fake)
    assert exc.value.code == code
    assert REPO not in str(exc.value)


def test_valid_pinned_trees_preserve_modes_kinds_and_raw_utf8_paths() -> None:
    fake = FakeTransport()
    result = _collect(fake)
    assert isinstance(result, GitTreeCensus)
    assert result.repository == REPO
    assert (result.base_commit_sha1, result.head_commit_sha1) == (BASE, HEAD)
    assert (result.base_tree_sha1, result.head_tree_sha1) == (fake.base_root, fake.head_root)
    for leaves in (result.base_leaves, result.head_leaves):
        assert leaves == tuple(sorted(leaves, key=_path))
        assert all(leaf.mode != "040000" for leaf in leaves)
    expected_base = {
        _b64(b"readme.txt"): ("100644", "blob", _blob(b"base")),
        _b64(b"link"): ("120000", "blob", _blob(b"readme.txt")),
        _b64(b"vendor"): ("160000", "commit", OTHER),
        _b64(b"src/main.py"): ("100644", "blob", _blob(b"print(1)")),
    }
    observed_base = {
        leaf.path_base64: (leaf.mode, leaf.kind, leaf.object_sha1) for leaf in result.base_leaves
    }
    assert observed_base == expected_base
    cafe = TreeLeaf(_b64("café.txt".encode()), "100644", "blob", _blob(b"utf8"))
    assert cafe in result.head_leaves
    assert TreeLeaf(_b64(b"readme.txt"), "100755", "blob", _blob(b"head")) in result.head_leaves
    assert TreeLeaf(_b64(b"vendor"), "160000", "commit", OTHER) in result.head_leaves
    assert TreeLeaf(_b64(b"link"), "120000", "blob", _blob(b"readme.txt")) in result.head_leaves
    assert len(result.head_leaves) == len(result.base_leaves) + 1
    assert all("/git/blobs/" not in path for path in fake.calls)
    assert set(fake.calls).issubset(
        {
            f"{ROOT}/git/commits/{BASE}",
            f"{ROOT}/git/commits/{HEAD}",
            f"{ROOT}/git/trees/{fake.base_root}",
            f"{ROOT}/git/trees/{fake.head_root}",
            f"{ROOT}/git/trees/{fake.nested}",
        }
    )


@pytest.mark.parametrize("side", ["base", "head"])
def test_commit_sha_echo_and_tree_link_fail_closed(side: str) -> None:
    fake = FakeTransport()
    pinned = BASE if side == "base" else HEAD
    fake.responses[f"{ROOT}/git/commits/{pinned}"]["sha"] = OTHER
    _reject(fake, "OBJECT_IDENTITY_MISMATCH")
    fake = FakeTransport()
    fake.responses[f"{ROOT}/git/commits/{pinned}"]["tree"] = {"sha": "z" * 40}
    _reject(fake, "MALFORMED_RESPONSE")
    fake = FakeTransport()
    fake.responses[f"{ROOT}/git/commits/{pinned}"]["tree"] = {"sha": OTHER}
    _reject(fake, "TRANSPORT_FAILURE")


@pytest.mark.parametrize("side", ["base", "head"])
@pytest.mark.parametrize(
    "change",
    [
        "omit_child_entry",
        "omit_root_entry",
        "wrong_mode",
        "wrong_oid",
        "wrong_type",
        "lossy_path",
        "duplicate",
        "unsafe_path",
        "unknown_mode",
        "truncated",
        "wrong_echo",
    ],
)
def test_tree_identity_and_complete_inventory_rejects_mutation(side: str, change: str) -> None:
    fake = FakeTransport()
    root_sha = fake.base_root if side == "base" else fake.head_root
    root = fake.responses[f"{ROOT}/git/trees/{root_sha}"]
    nested = fake.responses[f"{ROOT}/git/trees/{fake.nested}"]
    if change == "omit_child_entry":
        nested["tree"] = []
    elif change == "omit_root_entry":
        root["tree"].pop()
    elif change in {
        "wrong_mode",
        "wrong_oid",
        "wrong_type",
        "lossy_path",
        "unsafe_path",
        "unknown_mode",
    }:
        field, value = {
            "wrong_mode": ("mode", "100644"),
            "wrong_oid": ("sha", OTHER),
            "wrong_type": ("type", "commit"),
            "lossy_path": ("path", "cafe.txt"),
            "unsafe_path": ("path", "../escape"),
            "unknown_mode": ("mode", "100664"),
        }[change]
        target = -1 if side == "head" and change == "lossy_path" else 0
        root["tree"][target][field] = value
    elif change == "duplicate":
        root["tree"].append(deepcopy(root["tree"][0]))
    elif change == "truncated":
        root["truncated"] = True
    else:
        root["sha"] = OTHER
    with pytest.raises(GitTreeCensusError):
        _collect(fake)


def test_missing_child_tree_fails_closed_without_partial_census() -> None:
    fake = FakeTransport()
    del fake.responses[f"{ROOT}/git/trees/{fake.nested}"]
    _reject(fake, "TRANSPORT_FAILURE")


def test_valid_deep_tree_exceeding_resource_bound_is_rejected() -> None:
    fake = FakeTransport()
    child = _tree([_entry("leaf", "100644", _blob(b"leaf"))])
    for _ in range(34):
        fake.responses[f"{ROOT}/git/trees/{child['sha']}"] = child
        child = _tree([_entry("d", "040000", child["sha"])])
    fake.responses[f"{ROOT}/git/trees/{child['sha']}"] = child
    fake.responses[f"{ROOT}/git/commits/{HEAD}"]["tree"]["sha"] = child["sha"]
    with pytest.raises(GitTreeCensusError):
        _collect(fake)


def test_invalid_unicode_path_is_sanitized() -> None:
    fake = FakeTransport()
    fake.responses[f"{ROOT}/git/trees/{fake.head_root}"]["tree"][0]["path"] = "\ud800"
    with pytest.raises(GitTreeCensusError):
        _collect(fake)


def test_transport_failure_and_pagination_are_sanitized() -> None:
    fake = FakeTransport()
    canary = "sensitive_remote_body"
    fake.responses[f"{ROOT}/git/trees/{fake.head_root}"] = TransportError(canary)
    _reject(fake, "TRANSPORT_FAILURE")
    fake = FakeTransport()
    path = f"{ROOT}/git/trees/{fake.head_root}"
    fake.responses[path] = TransportResult(
        status=200,
        body=fake.responses[path],
        next_url="https://api.github.com/other",
    )
    _reject(fake, "MALFORMED_RESPONSE")


@pytest.mark.parametrize(
    "repository,base,head",
    [
        ("owner", BASE, HEAD),
        ("owner/repo?x=1", BASE, HEAD),
        ("../repo", BASE, HEAD),
        (REPO, "X" * 40, HEAD),
        (REPO, BASE, "a" * 39),
        (REPO, BASE, True),
        (REPO, None, HEAD),
    ],
)
def test_bad_locator_never_issues_network_request(repository: Any, base: Any, head: Any) -> None:
    fake = FakeTransport()
    with pytest.raises(GitTreeCensusError):
        collect_git_tree_census(fake, repository, base, head)
    assert fake.calls == []


def test_unwired_and_caller_constructible_without_authority() -> None:
    fake = FakeTransport()
    result = _collect(fake)
    assert GitTreeCensus(*result) == result
    assert not hasattr(result, "authorize")
    assert set(inspect.signature(collect_git_tree_census).parameters) == {
        "transport",
        "repository",
        "base_commit_sha1",
        "head_commit_sha1",
    }
    root = Path(__file__).resolve().parents[2] / "src" / "blackbread"
    collector_path = root / "governance" / "source_admission_git_trees.py"
    content = collector_path.read_text(encoding="utf-8")
    assert "source_admission_policy" not in content
    assert "source_admission_contracts" not in content
    assert "source_admission_evaluator" not in content
    for path in root.rglob("*.py"):
        if path == collector_path:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported = {module, *(f"{module}.{alias.name}" for alias in node.names)}
            else:
                continue
            assert not any(name.endswith("source_admission_git_trees") for name in imported)


def _typed_leaf(path: bytes, mode: str, sha: str) -> TreeLeaf:
    kind = "commit" if mode == "160000" else "blob"
    return TreeLeaf(_b64(path), mode, kind, sha)


def _census(base: list[TreeLeaf], head: list[TreeLeaf]) -> GitTreeCensus:
    return GitTreeCensus(REPO, BASE, HEAD, "d" * 40, "e" * 40, tuple(base), tuple(head))


def _reject_reconcile(census: Any, code: str) -> None:
    with pytest.raises(GitTreeCensusError) as exc:
        reconcile_git_tree_census(census)
    assert exc.value.code == code
    assert REPO not in str(exc.value)


def test_reconcile_collected_census_marks_each_union_path_once() -> None:
    census = _collect(FakeTransport())
    result = reconcile_git_tree_census(census)
    assert isinstance(result, GitTreeInventory)
    assert result[:5] == census[:5]
    paths = [base64.b64decode(entry.path_base64) for entry in result.entries]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))
    observed = {entry.path_base64: entry for entry in result.entries}
    assert {path: entry.status for path, entry in observed.items()} == {
        _b64(b"readme.txt"): LeafStatus.MODIFIED,
        _b64(b"link"): LeafStatus.UNCHANGED,
        _b64(b"vendor"): LeafStatus.UNCHANGED,
        _b64(b"src/main.py"): LeafStatus.UNCHANGED,
        _b64("café.txt".encode()): LeafStatus.ADDED,
    }
    link = TreeLeaf(_b64(b"link"), "120000", "blob", _blob(b"readme.txt"))
    assert observed[_b64(b"link")].base_leaf == observed[_b64(b"link")].head_leaf == link
    vendor = TreeLeaf(_b64(b"vendor"), "160000", "commit", OTHER)
    assert observed[_b64(b"vendor")].base_leaf == observed[_b64(b"vendor")].head_leaf == vendor
    added = observed[_b64("café.txt".encode())]
    assert added.base_leaf is None and added.head_leaf is not None


def test_reconcile_union_statuses_without_rename_inference() -> None:
    keep = _typed_leaf(b"keep.txt", "100644", _blob(b"keep"))
    chmod_base = _typed_leaf(b"chmod.sh", "100644", _blob(b"run"))
    chmod_head = _typed_leaf(b"chmod.sh", "100755", _blob(b"run"))
    edit_base = _typed_leaf(b"edit.py", "100644", _blob(b"old"))
    edit_head = _typed_leaf(b"edit.py", "100644", _blob(b"new"))
    moved = _blob(b"payload")
    old = _typed_leaf(b"old.txt", "100644", moved)
    new = _typed_leaf(b"new.txt", "100644", moved)
    base = sorted([keep, chmod_base, edit_base, old], key=_path)
    head = sorted([keep, chmod_head, edit_head, new], key=_path)
    result = reconcile_git_tree_census(_census(base, head))
    paths = [base64.b64decode(entry.path_base64) for entry in result.entries]
    assert paths == [b"chmod.sh", b"edit.py", b"keep.txt", b"new.txt", b"old.txt"]
    observed = {base64.b64decode(entry.path_base64): entry for entry in result.entries}
    assert observed[b"keep.txt"].status is LeafStatus.UNCHANGED
    mode_only = observed[b"chmod.sh"]
    assert mode_only.status is LeafStatus.MODIFIED
    assert (mode_only.base_leaf, mode_only.head_leaf) == (chmod_base, chmod_head)
    assert observed[b"edit.py"].status is LeafStatus.MODIFIED
    deleted, added = observed[b"old.txt"], observed[b"new.txt"]
    assert (deleted.status, added.status) == (LeafStatus.DELETED, LeafStatus.ADDED)
    assert deleted.head_leaf is None and added.base_leaf is None
    assert deleted.base_leaf is not None and added.head_leaf is not None
    assert added.head_leaf.object_sha1 == deleted.base_leaf.object_sha1


def test_reconcile_empty_census_yields_empty_union() -> None:
    result = reconcile_git_tree_census(_census([], []))
    assert result == GitTreeInventory(REPO, BASE, HEAD, "d" * 40, "e" * 40, ())


@pytest.mark.parametrize("side", ["base", "head"])
def test_reconcile_rejects_duplicate_path_bytes(side: str) -> None:
    leaf = _typed_leaf(b"dup.txt", "100644", _blob(b"dup"))
    duplicate = [leaf, TreeLeaf(leaf.path_base64, "100755", "blob", OTHER)]
    census = _census(duplicate, []) if side == "base" else _census([], duplicate)
    _reject_reconcile(census, "DUPLICATE_PATH")


@pytest.mark.parametrize("side", ["base", "head"])
def test_reconcile_rejects_noncanonical_leaf_order(side: str) -> None:
    first = _typed_leaf(b"a.txt", "100644", _blob(b"a"))
    unordered = [_typed_leaf(b"b.txt", "100644", _blob(b"b")), first]
    census = _census(unordered, []) if side == "base" else _census([], unordered)
    _reject_reconcile(census, "NONCANONICAL_CENSUS")


@pytest.mark.parametrize(
    "leaf",
    [
        TreeLeaf("!!!not-base64!!!", "100644", "blob", OTHER),
        TreeLeaf("", "100644", "blob", OTHER),
        TreeLeaf("QX==", "100644", "blob", OTHER),
        TreeLeaf(123, "100644", "blob", OTHER),
        TreeLeaf(_b64(b"x"), "999999", "blob", OTHER),
        TreeLeaf(_b64(b"x"), "040000", "tree", OTHER),
        TreeLeaf(_b64(b"x"), "160000", "blob", OTHER),
        TreeLeaf(_b64(b"x"), "100644", "blob", "zzzz"),
        TreeLeaf(_b64(b"x"), "100644", "blob", 123),
        ("not-a-leaf",),
    ],
)
def test_reconcile_rejects_malformed_leaf_input(leaf: Any) -> None:
    _reject_reconcile(_census([leaf], []), "MALFORMED_CENSUS")


def test_reconcile_rejects_non_census_input() -> None:
    _reject_reconcile("not-a-census", "MALFORMED_CENSUS")


def test_reconcile_is_pure_caller_constructible_without_authority() -> None:
    leaf = _typed_leaf(b"only.txt", "100644", _blob(b"only"))
    result = reconcile_git_tree_census(_census([leaf], [leaf]))
    assert GitTreeInventory(*result) == result
    assert CensusEntry(*result.entries[0]) == result.entries[0]
    assert not hasattr(result, "authorize")
    assert set(inspect.signature(reconcile_git_tree_census).parameters) == {"census"}
