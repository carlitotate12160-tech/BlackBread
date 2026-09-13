"""Regression proofs for candidate-tree diff-budget evidence collection.

Each proof runs in a temporary Git repository so the evidence helper is
exercised against real Git state without touching the real repository.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.governance.diff_budget_evidence import (
    PathStat,
    collect_candidate_diff,
)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=cwd, timeout=10, check=False
    )


def _init_repo(path: Path) -> None:
    """Initialize a git repo with a committed baseline on ``main``."""
    init_args = (
        ["init", "-b", "main"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
    )
    for args in init_args:
        assert _git(args, path).returncode == 0
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    for args in (["add", "."], ["commit", "-m", "baseline"], ["checkout", "-b", "feature"]):
        assert _git(args, path).returncode == 0


def _stats(diff: list[PathStat], filename: str) -> PathStat | None:
    """Return the first PathStat for *filename* or None."""
    return next((s for s in diff if s.path == filename), None)


def _total_insertions(diff: list[PathStat], filename: str) -> int:
    """Sum insertions across all entries for *filename* (detects duplicates)."""
    return sum(s.insertions for s in diff if s.path == filename)


def _path_count(diff: list[PathStat], filename: str) -> int:
    """Count entries for *filename* (should be 1 when deduplicated)."""
    return sum(1 for s in diff if s.path == filename)


def test_mixed_staged_unstaged_counts_once(tmp_path: Path) -> None:
    """A tracked file with both staged and unstaged edits appears once."""
    _init_repo(tmp_path)
    module = tmp_path / "src" / "blackbread" / "mixed.py"
    module.parent.mkdir(parents=True)
    module.write_text("x = 1\n", encoding="utf-8")
    assert _git(["add", "."], tmp_path).returncode == 0
    assert _git(["commit", "-m", "add mixed"], tmp_path).returncode == 0
    assert _git(["checkout", "main"], tmp_path).returncode == 0
    assert _git(["merge", "feature"], tmp_path).returncode == 0
    assert _git(["checkout", "feature"], tmp_path).returncode == 0
    module.write_text("x = 1\n" + "a = 1\n" * 10, encoding="utf-8")
    assert _git(["add", "."], tmp_path).returncode == 0
    module.write_text("x = 1\n" + "a = 1\n" * 10 + "b = 2\n" * 5, encoding="utf-8")
    diff = collect_candidate_diff(tmp_path)
    assert _path_count(diff, "src/blackbread/mixed.py") == 1
    assert _total_insertions(diff, "src/blackbread/mixed.py") == 15


def test_untracked_runtime_file_counted(tmp_path: Path) -> None:
    """An untracked runtime file is included with its full line count."""
    _init_repo(tmp_path)
    module = tmp_path / "src" / "blackbread" / "new.py"
    module.parent.mkdir(parents=True)
    module.write_text("x = 1\n" * 500, encoding="utf-8")
    diff = collect_candidate_diff(tmp_path)
    stat = _stats(diff, "src/blackbread/new.py")
    assert stat is not None
    assert stat.insertions == 500
    assert stat.deletions == 0


def test_untracked_ignored_file_excluded(tmp_path: Path) -> None:
    """An ignored untracked file does not appear in the candidate diff."""
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (tmp_path / "src" / "blackbread").mkdir(parents=True)
    (tmp_path / "src" / "blackbread" / "trace.log").write_text("noise\n" * 100, encoding="utf-8")
    diff = collect_candidate_diff(tmp_path)
    assert _stats(diff, "src/blackbread/trace.log") is None


def test_lifecycle_one_path_per_state(tmp_path: Path) -> None:
    """A file checked as untracked, staged, committed, then edited yields one path."""
    _init_repo(tmp_path)
    module = tmp_path / "src" / "blackbread" / "life.py"
    module.parent.mkdir(parents=True)
    module.write_text("x = 1\n" * 10, encoding="utf-8")
    diff = collect_candidate_diff(tmp_path)
    assert _path_count(diff, "src/blackbread/life.py") == 1
    assert _git(["add", "."], tmp_path).returncode == 0
    diff = collect_candidate_diff(tmp_path)
    assert _path_count(diff, "src/blackbread/life.py") == 1
    assert _git(["commit", "-m", "add life"], tmp_path).returncode == 0
    diff = collect_candidate_diff(tmp_path)
    assert _path_count(diff, "src/blackbread/life.py") == 1
    module.write_text("x = 1\n" * 10 + "y = 2\n" * 5, encoding="utf-8")
    diff = collect_candidate_diff(tmp_path)
    assert _path_count(diff, "src/blackbread/life.py") == 1


def test_evidence_failure_blocks(tmp_path: Path) -> None:
    """A directory without a valid Git base must fail, not return empty."""
    with pytest.raises(RuntimeError):
        collect_candidate_diff(tmp_path)


def test_empty_candidate_returns_zero(tmp_path: Path) -> None:
    """A clean tree with no changes returns an empty list, not an error."""
    _init_repo(tmp_path)
    assert collect_candidate_diff(tmp_path) == []


# ---------------------------------------------------------------------------
# F1: merge-base must be the actual merge-base SHA, not the branch tip


def test_merge_base_excludes_upstream_only_commit(tmp_path: Path) -> None:
    """An upstream-only commit on main after branching must not enter the diff."""
    _init_repo(tmp_path)
    # Feature work
    feat = tmp_path / "src" / "blackbread" / "feature.py"
    feat.parent.mkdir(parents=True)
    feat.write_text("x = 1\n", encoding="utf-8")
    assert _git(["add", "."], tmp_path).returncode == 0
    assert _git(["commit", "-m", "feature work"], tmp_path).returncode == 0
    # Advance main with an unrelated runtime commit
    assert _git(["checkout", "main"], tmp_path).returncode == 0
    upstream = tmp_path / "src" / "blackbread" / "upstream.py"
    upstream.parent.mkdir(parents=True, exist_ok=True)
    upstream.write_text("u = 1\n" * 50, encoding="utf-8")
    assert _git(["add", "."], tmp_path).returncode == 0
    assert _git(["commit", "-m", "upstream only"], tmp_path).returncode == 0
    assert _git(["checkout", "feature"], tmp_path).returncode == 0
    diff = collect_candidate_diff(tmp_path)
    assert _stats(diff, "src/blackbread/upstream.py") is None
    assert _stats(diff, "src/blackbread/feature.py") is not None


# ---------------------------------------------------------------------------
# F2: binary -/- entries must be retained with zero line counts


def test_binary_entry_retained(tmp_path: Path) -> None:
    """A binary file change (-/- numstat) must appear with binary=True and zero counts."""
    _init_repo(tmp_path)
    (tmp_path / "src" / "blackbread").mkdir(parents=True)
    binary_file = tmp_path / "src" / "blackbread" / "data.bin"
    binary_file.write_bytes(b"\x00\x01\x02\x03")
    assert _git(["add", "."], tmp_path).returncode == 0
    assert _git(["commit", "-m", "add binary"], tmp_path).returncode == 0
    assert _git(["checkout", "main"], tmp_path).returncode == 0
    assert _git(["merge", "feature"], tmp_path).returncode == 0
    assert _git(["checkout", "feature"], tmp_path).returncode == 0
    binary_file.write_bytes(b"\x00\x01\x02\x03\x04\x05")
    assert _git(["add", "."], tmp_path).returncode == 0
    diff = collect_candidate_diff(tmp_path)
    stat = _stats(diff, "src/blackbread/data.bin")
    assert stat is not None
    assert stat.binary is True
    assert stat.insertions == 0
    assert stat.deletions == 0


# F3: untracked paths with whitespace must be preserved byte-for-character


@pytest.mark.parametrize(
    "rel_path",
    [
        "src/blackbread/has spaces.py",
        "src/blackbread/ leading.py",
        " leading_root.py",
    ],
    ids=["internal_spaces", "leading_space", "leading_root_space"],
)
def test_untracked_exact_path_preserved(tmp_path: Path, rel_path: str) -> None:
    """An untracked file with whitespace in its name must appear with the exact path."""
    _init_repo(tmp_path)
    module = tmp_path / rel_path
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text("x = 1\n" * 20, encoding="utf-8")
    diff = collect_candidate_diff(tmp_path)
    stat = _stats(diff, rel_path)
    assert stat is not None
    assert stat.insertions == 20


# F4: collect_candidate_diff() without cwd must use the current directory


def test_default_cwd_follows_chdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling collect_candidate_diff() without cwd must evaluate Path.cwd() each time."""
    p1 = tmp_path / "repo1"
    p2 = tmp_path / "repo2"
    for p in (p1, p2):
        p.mkdir()
        _init_repo(p)
    monkeypatch.chdir(p1)
    assert collect_candidate_diff() == []
    repo2_mod = p2 / "src" / "blackbread" / "repo2.py"
    repo2_mod.parent.mkdir(parents=True, exist_ok=True)
    repo2_mod.write_text("z = 9\n" * 30, encoding="utf-8")
    monkeypatch.chdir(p2)
    diff2 = collect_candidate_diff()
    assert _path_count(diff2, "src/blackbread/repo2.py") == 1
    assert _stats(diff2, "src/blackbread/repo2.py") is not None
