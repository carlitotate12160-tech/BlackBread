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
    binary: bool = False


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command with standard capture; never raises."""
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=cwd, timeout=10, check=False
    )


def _resolve_merge_base(cwd: Path) -> str:
    """Return the merge-base SHA of HEAD and a verified main ref.

    Validates ``origin/main`` or ``main`` exists, then computes the actual
    merge-base so upstream-only commits after branching do not enter evidence.
    """
    for ref in ("origin/main", "main"):
        verify = _git(["rev-parse", "--verify", ref], cwd)
        if verify.returncode == 0 and verify.stdout.strip():
            mb = _git(["merge-base", "HEAD", ref], cwd)
            if mb.returncode == 0 and mb.stdout.strip():
                return mb.stdout.strip()
            raise RuntimeError(f"git merge-base HEAD {ref} failed: {mb.stderr.strip()}")
    raise RuntimeError("cannot resolve merge base: origin/main and main unavailable")


def _parse_numstat(stdout: str) -> list[PathStat]:
    """Parse ``git diff --numstat`` output into structured records.

    Paired ``-/-`` entries are binary (zero line counts, ``binary=True``).
    A mixed numeric/``-`` record is malformed and raises ``RuntimeError``.
    """
    out: list[PathStat] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            raise RuntimeError(f"malformed numstat line: {line!r}")
        ins, dels, path = parts[0], parts[1], "\t".join(parts[2:])
        if ins == "-" and dels == "-":
            out.append(PathStat(path=path, insertions=0, deletions=0, binary=True))
        elif ins == "-" or dels == "-":
            raise RuntimeError(f"malformed numstat line (mixed binary/numeric): {line!r}")
        else:
            out.append(PathStat(path=path, insertions=int(ins), deletions=int(dels)))
    return out


def _untracked_stats(cwd: Path) -> list[PathStat]:
    """Return PathStat records for untracked non-ignored files (all-insertion).

    Preserves NUL-delimited paths byte-for-character — no ``strip()``.
    Raises ``RuntimeError`` if a reported path is not a readable regular file.
    """
    r = _git(["ls-files", "--others", "--exclude-standard", "-z"], cwd)
    if r.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {r.stderr.strip()}")
    out: list[PathStat] = []
    for raw_name in r.stdout.split("\0"):
        if raw_name == "":
            continue
        p = cwd / raw_name
        if not p.is_file():
            raise RuntimeError(f"untracked path not a readable file: {raw_name!r}")
        out.append(PathStat(path=raw_name, insertions=sum(1 for _ in p.open("rb")), deletions=0))
    return out


def collect_candidate_diff(cwd: Path | None = None) -> list[PathStat]:
    """Return deduplicated candidate-tree PathStat records relative to the merge base.

    Combines one tracked diff (``git diff --numstat <merge-base>``) with untracked
    non-ignored files.  Each path appears at most once.  Fail-closed on any Git
    failure or malformed evidence.
    """
    if cwd is None:
        cwd = Path.cwd()
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
