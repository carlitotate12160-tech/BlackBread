"""Banned code patterns, AI-slop signatures, and diff-budget governance tests.

Inspired by Decepticon's QUALITY_BAR.md — these tests catch patterns that
ruff/mypy cannot detect: AI-generated code smells, defensive redundancy,
and PR scope violations.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
SRC = ROOT / "src" / "blackbread"
TESTS = ROOT / "tests"

RUNTIME_CODE_MAX_LINES = 400
RUNTIME_CODE_MAX_FILES = 10
RUNTIME_EXCLUDE_PATTERNS = {"docs/", "tests/", ".github/", "migrations/", "scripts/"}

VAGUE_NAMES = frozenset({"data", "info", "obj", "item", "stuff", "thing"})
FLAG_WORDS = frozenset(
    {
        "leverage",
        "leveraged",
        "leveraging",
        "robust",
        "robustly",
        "comprehensive",
        "comprehensively",
        "utilize",
        "utilized",
        "utilizing",
        "seamless",
        "seamlessly",
        "elegant",
        "elegantly",
        "optimal",
        "optimally",
    }
)


def _iter_python_files(base: Path) -> list[Path]:
    return sorted(base.rglob("*.py"))


def _is_runtime_path(rel: str) -> bool:
    return not any(rel.startswith(p) for p in RUNTIME_EXCLUDE_PATTERNS)


# ---------------------------------------------------------------------------
# Banned patterns
# ---------------------------------------------------------------------------


def test_no_bare_except() -> None:
    """Bare `except:` is banned — catch specific exceptions."""
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, node.lineno))
    assert not offenders, f"Bare except found: {offenders}"


def test_no_broad_except_pass() -> None:
    """`except Exception: pass` is banned — it swallows failures silently."""
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            is_broad = (
                node.type is None
                or (isinstance(node.type, ast.Name) and node.type.id == "Exception")
                or (isinstance(node.type, ast.Attribute) and node.type.attr == "Exception")
            )
            if not is_broad:
                continue
            body = node.body
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, node.lineno))
    assert not offenders, f"`except Exception: pass` found: {offenders}"


def test_no_type_ignore_without_code() -> None:
    """`# type: ignore` without a specific code is banned."""
    pattern = re.compile(r"#\s*type:\s*ignore(?!\[)")
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, i))
    assert not offenders, f"Bare `# type: ignore` without code: {offenders}"


def test_no_noqa_without_code() -> None:
    """`# noqa` without a rule code is banned."""
    noqa_prefixes = (
        "(",
        "E",
        "W",
        "F",
        "B",
        "S",
        "C",
        "N",
        "U",
        "A",
        "R",
        "P",
        "I",
        "T",
        "D",
        "SIM",
        "RET",
        "PL",
        "RUF",
        "ASYNC",
        "UP",
    )
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.split("# noqa", 1)
            if len(stripped) == 2:
                after = stripped[1]
                if not after.strip().startswith(noqa_prefixes):
                    rel = path.relative_to(ROOT).as_posix()
                    offenders.append((rel, i))
    assert not offenders, f"Bare `# noqa` without code: {offenders}"


def test_no_print_in_production() -> None:
    """`print()` in production code is banned — use logging."""
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, node.lineno))
    assert not offenders, f"`print()` in production code: {offenders}"


def test_no_suppressed_return_values() -> None:
    """`_ = call()` is banned — use the value or don't call."""
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_"
                and isinstance(node.value, ast.Call)
            ):
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, node.lineno))
    assert not offenders, f"Suppressed return value `_ = call()`: {offenders}"


def test_no_not_implemented_in_delivered_code() -> None:
    """`raise NotImplementedError` in production code is banned."""
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id == "NotImplementedError"
            ):
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, node.lineno))
    assert not offenders, f"`raise NotImplementedError` in production: {offenders}"


def test_no_todo_without_issue_link() -> None:
    """`TODO` without an issue link (#NNN) is banned."""
    pattern = re.compile(r"#\s*TODO\b(?!.*#\d+)", re.IGNORECASE)
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, i))
    assert not offenders, f"`TODO` without issue link: {offenders}"


# ---------------------------------------------------------------------------
# AI-slop signatures
# ---------------------------------------------------------------------------


def test_no_if_true_else_false_pattern() -> None:
    """`if cond: return True else: return False` is AI-slop — use `return cond`."""
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.If) or not node.orelse:
                continue
            if_body = node.body
            else_body = node.orelse
            if len(if_body) != 1 or len(else_body) != 1:
                continue
            if_return = isinstance(if_body[0], ast.Return)
            else_return = isinstance(else_body[0], ast.Return)
            if not if_return or not else_return:
                continue
            if_val = if_body[0].value
            else_val = else_body[0].value
            if (
                isinstance(if_val, ast.Constant)
                and if_val.value is True
                and isinstance(else_val, ast.Constant)
                and else_val.value is False
            ):
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, node.lineno))
    assert not offenders, f"`if cond: return True else: return False` pattern: {offenders}"


def test_no_vague_variable_names_in_production() -> None:
    """Variables named `data`, `info`, `obj`, `item` are AI-slop — rename to describe."""
    offenders: list[tuple[str, int, str]] = []
    for path in _iter_python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in VAGUE_NAMES:
                        rel = path.relative_to(ROOT).as_posix()
                        offenders.append((rel, node.lineno, target.id))
    assert not offenders, f"Vague variable names: {offenders}"


def test_no_flag_words_in_comments() -> None:
    """Flag words like 'leverage', 'robust', 'comprehensive' are AI-slop."""
    offenders: list[tuple[str, int, str]] = []
    for path in _iter_python_files(SRC):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("#"):
                lower = line.lower()
                for word in FLAG_WORDS:
                    if word in lower:
                        rel = path.relative_to(ROOT).as_posix()
                        offenders.append((rel, i, word))
                        break
    assert not offenders, f"AI-slop flag words in comments: {offenders}"


def test_no_speculative_kwargs_in_production() -> None:
    """Speculative `**kwargs` parameters are AI-slop — add when the second caller arrives."""
    offenders: list[tuple[str, int, str]] = []
    for path in _iter_python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            has_kwargs = node.args.kwarg is not None
            if has_kwargs:
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, node.lineno, node.name))
    assert not offenders, f"Speculative **kwargs in production: {offenders}"


# ---------------------------------------------------------------------------
# Diff budget
# ---------------------------------------------------------------------------


def _get_diff_stat() -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "origin/main...HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def test_diff_budget_runtime_code_under_limit() -> None:
    """PR runtime-code diff must stay under 400 lines and 10 files."""
    diff = _get_diff_stat()
    if not diff.strip():
        return
    runtime_files = 0
    runtime_lines = 0
    for line in diff.strip().splitlines():
        if "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) < 2:
            continue
        filename = parts[0].strip()
        if not _is_runtime_path(filename):
            continue
        insertions = 0
        deletions = 0
        for token in parts[1].split():
            if token.startswith("+"):
                insertions += int(token.count("+"))
            elif token.startswith("-"):
                deletions += int(token.count("-"))
        runtime_lines += insertions + deletions
        runtime_files += 1
    assert runtime_files <= RUNTIME_CODE_MAX_FILES, (
        f"PR touches {runtime_files} runtime files (max {RUNTIME_CODE_MAX_FILES})"
    )
    assert runtime_lines <= RUNTIME_CODE_MAX_LINES, (
        f"PR changes {runtime_lines} runtime lines (max {RUNTIME_CODE_MAX_LINES})"
    )
