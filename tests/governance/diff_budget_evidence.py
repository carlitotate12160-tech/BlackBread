"""Normalized candidate-tree diff statistics for the runtime diff-budget gate.

Collects one tracked diff against the merge base (committed + staged + unstaged
in a single ``git diff --numstat <merge-base>``) plus untracked non-ignored
files (``git ls-files --others --exclude-standard -z``).  Each path appears at
most once.  Fail-closed on any Git failure, malformed numstat, or unresolved
base.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import NamedTuple


class PathStat(NamedTuple):
    """One file's candidate-tree change relative to the merge base."""

    path: str
    insertions: int
    deletions: int


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command with standard capture; never raises."""
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=cwd, timeout=10, check=False
    )


def _resolve_merge_base(cwd: Path) -> str:
    """Return the merge-base SHA; fail-closed if unavailable."""
    for ref in ("origin/main", "main"):
        r = _git(["rev-parse", "--verify", ref], cwd)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    mb = _git(["merge-base", "HEAD", "main"], cwd)
    if mb.returncode == 0 and mb.stdout.strip():
        return mb.stdout.strip()
    raise RuntimeError("cannot resolve merge base: origin/main and merge-base HEAD main failed")


def _parse_numstat(stdout: str) -> list[PathStat]:
    """Parse ``git diff --numstat`` output into structured records."""
    out: list[PathStat] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            raise RuntimeError(f"malformed numstat line: {line!r}")
        ins, dels, path = parts[0], parts[1], "\t".join(parts[2:])
        if ins == "-" or dels == "-":
            continue
        out.append(PathStat(path=path, insertions=int(ins), deletions=int(dels)))
    return out


def _untracked_stats(cwd: Path) -> list[PathStat]:
    """Return PathStat records for untracked non-ignored files (all-insertion)."""
    r = _git(["ls-files", "--others", "--exclude-standard", "-z"], cwd)
    if r.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {r.stderr.strip()}")
    out: list[PathStat] = []
    for raw_name in r.stdout.split("\0"):
        name = raw_name.strip()
        if not name:
            continue
        p = cwd / name
        if p.is_file():
            out.append(PathStat(path=name, insertions=sum(1 for _ in p.open("rb")), deletions=0))
    return out


_DEFAULT_CWD: Path | None = None


def _default_cwd() -> Path:
    global _DEFAULT_CWD  # noqa: PLW0603
    if _DEFAULT_CWD is None:
        _DEFAULT_CWD = Path.cwd()
    return _DEFAULT_CWD


def collect_candidate_diff(cwd: Path | None = None) -> list[PathStat]:
    """Return deduplicated candidate-tree PathStat records relative to the merge base.

    Combines one tracked diff (``git diff --numstat <merge-base>``) with untracked
    non-ignored files.  Each path appears at most once.  Fail-closed on any Git
    failure or malformed evidence.
    """
    if cwd is None:
        cwd = _default_cwd()
    base = _resolve_merge_base(cwd)
    r = _git(["diff", "--numstat", base], cwd)
    if r.returncode != 0:
        raise RuntimeError(f"git diff --numstat {base} failed: {r.stderr.strip()}")
    tracked = _parse_numstat(r.stdout)
    untracked = _untracked_stats(cwd)
    seen: dict[str, PathStat] = {}
    for stat in tracked + untracked:
        if stat.path not in seen:
            seen[stat.path] = stat
    return list(seen.values())
