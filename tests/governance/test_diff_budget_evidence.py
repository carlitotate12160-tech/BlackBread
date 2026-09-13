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
    # Commit the file on main so it exists in the merge-base
    module = tmp_path / "src" / "blackbread" / "mixed.py"
    module.parent.mkdir(parents=True)
    module.write_text("x = 1\n", encoding="utf-8")
    assert _git(["add", "."], tmp_path).returncode == 0
    assert _git(["commit", "-m", "add mixed"], tmp_path).returncode == 0
    # Merge feature into main, then return to feature
    assert _git(["checkout", "main"], tmp_path).returncode == 0
    assert _git(["merge", "feature"], tmp_path).returncode == 0
    assert _git(["checkout", "feature"], tmp_path).returncode == 0
    # Staged edit (+10 lines)
    module.write_text("x = 1\n" + "a = 1\n" * 10, encoding="utf-8")
    assert _git(["add", "."], tmp_path).returncode == 0
    # Unstaged edit (+5 more lines)
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
    # Untracked
    module.write_text("x = 1\n" * 10, encoding="utf-8")
    diff = collect_candidate_diff(tmp_path)
    assert sum(1 for s in diff if s.path == "src/blackbread/life.py") == 1
    # Staged
    assert _git(["add", "."], tmp_path).returncode == 0
    diff = collect_candidate_diff(tmp_path)
    assert sum(1 for s in diff if s.path == "src/blackbread/life.py") == 1
    # Committed
    assert _git(["commit", "-m", "add life"], tmp_path).returncode == 0
    diff = collect_candidate_diff(tmp_path)
    assert sum(1 for s in diff if s.path == "src/blackbread/life.py") == 1
    # Edited (unstaged)
    module.write_text("x = 1\n" * 10 + "y = 2\n" * 5, encoding="utf-8")
    diff = collect_candidate_diff(tmp_path)
    assert sum(1 for s in diff if s.path == "src/blackbread/life.py") == 1


def test_evidence_failure_blocks(tmp_path: Path) -> None:
    """A directory without a valid Git base must fail, not return empty."""
    with pytest.raises(RuntimeError):
        collect_candidate_diff(tmp_path)


def test_empty_candidate_returns_zero(tmp_path: Path) -> None:
    """A clean tree with no changes returns an empty list, not an error."""
    _init_repo(tmp_path)
    diff = collect_candidate_diff(tmp_path)
    assert diff == []


def test_filename_with_spaces(tmp_path: Path) -> None:
    """An untracked file with spaces in its name is counted correctly."""
    _init_repo(tmp_path)
    module = tmp_path / "src" / "blackbread" / "has spaces.py"
    module.parent.mkdir(parents=True)
    module.write_text("x = 1\n" * 20, encoding="utf-8")
    diff = collect_candidate_diff(tmp_path)
    stat = _stats(diff, "src/blackbread/has spaces.py")
    assert stat is not None
    assert stat.insertions == 20
