"""Objective code-hygiene patterns and diff-budget governance tests.

These tests catch structural code-hygiene violations and scope-budget
failures: bare exception handlers, swallowed broad exceptions, unspecific
tooling suppressions, production print statements, delivered NotImplementedError,
untracked TODOs, redundant boolean branches, unstructured kwargs, and PR diff budgets.
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
RUNTIME_EXCLUDE_PATTERNS = {
    "docs/",
    "tests/",
    ".github/",
    "migrations/",
    "scripts/",
    "config/",
    "assets/",
}
RUNTIME_EXCLUDE_SUFFIXES = {
    ".md",
    ".yml",
    ".yaml",
    ".toml",
    ".json",
    ".cfg",
    ".ini",
    ".txt",
    ".lock",
}


def _iter_python_files(base: Path) -> list[Path]:
    return sorted(base.rglob("*.py"))


def _is_runtime_path(rel: str) -> bool:
    if any(rel.startswith(p) for p in RUNTIME_EXCLUDE_PATTERNS):
        return False
    return not any(rel.endswith(s) for s in RUNTIME_EXCLUDE_SUFFIXES)


# ---------------------------------------------------------------------------
# Objective code-hygiene patterns
# ---------------------------------------------------------------------------


def test_no_bare_except() -> None:
    """Bare `except:` is prohibited — catch specific exceptions."""
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, node.lineno))
    assert not offenders, f"Bare except found: {offenders}"


def test_no_broad_except_pass() -> None:
    """`except Exception: pass` is prohibited — it swallows failures silently."""
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
    """`# type: ignore` without a specific error code is prohibited."""
    pattern = re.compile(r"#\s*type:\s*ignore(?!\[)")
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, i))
    assert not offenders, f"Bare `# type: ignore` without code: {offenders}"


def test_no_noqa_without_code() -> None:
    """`# noqa` without a rule code is prohibited.

    Accepted forms: `# noqa: F401`, `# noqa: F401,E501`, `# noqa(F401)`.
    Rejected: `# noqa` (bare), `# noqa: ` (no code after colon),
    `# noqa E501` (missing colon/paren), `# NOQA` (case variant without code).
    Matching is case-insensitive on the `noqa` keyword but requires a
    colon or paren followed by at least one word character.
    """
    code_pattern = re.compile(r"^\s*[:\(]\s*\w+", re.IGNORECASE)
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            lower = line.lower()
            idx = lower.find("# noqa")
            if idx == -1:
                continue
            after = line[idx + len("# noqa") :]
            if not code_pattern.match(after):
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, i))
    assert not offenders, f"Bare `# noqa` without code: {offenders}"


def test_no_print_in_production() -> None:
    """`print()` in production code is prohibited — use structured logging."""
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


def test_no_not_implemented_in_delivered_code() -> None:
    """`raise NotImplementedError` in production code is prohibited."""
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            exc = node.exc
            if isinstance(exc, ast.Call):
                exc = exc.func
            if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, node.lineno))
    assert not offenders, f"`raise NotImplementedError` in production: {offenders}"


def test_no_todo_without_issue_link() -> None:
    """`TODO` without an issue link (#NNN) is prohibited."""
    pattern = re.compile(r"#\s*TODO\b(?!.*#\d+)", re.IGNORECASE)
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files(SRC):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                rel = path.relative_to(ROOT).as_posix()
                offenders.append((rel, i))
    assert not offenders, f"`TODO` without issue link: {offenders}"


def test_no_if_true_else_false_pattern() -> None:
    """`if cond: return True else: return False` is redundant logic."""
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
    assert not offenders, f"Redundant boolean branching pattern found: {offenders}"


# ---------------------------------------------------------------------------
# Structured kwargs gate
# ---------------------------------------------------------------------------


def _is_canonical_unpack(annotation: ast.expr | None) -> bool:
    """Return True if annotation is canonical Unpack[SpecificTypedDict]."""
    if not isinstance(annotation, ast.Subscript):
        return False
    value = annotation.value
    is_unpack = (isinstance(value, ast.Name) and value.id == "Unpack") or (
        isinstance(value, ast.Attribute)
        and value.attr == "Unpack"
        and isinstance(value.value, ast.Name)
        and value.value.id in {"typing", "typing_extensions", "t"}
    )
    if not is_unpack:
        return False
    target = annotation.slice
    if isinstance(target, ast.Subscript):
        target = target.value
    forbidden = {"Any", "dict", "Dict", "Mapping", "Tuple", "tuple", "object"}
    if isinstance(target, ast.Name):
        return target.id not in forbidden
    if isinstance(target, ast.Attribute):
        return target.attr not in forbidden
    return False


def _find_unstructured_kwargs(tree: ast.AST) -> list[tuple[int, str]]:
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Lambda):
            if node.args.kwarg is not None:
                offenders.append((node.lineno, "<lambda>"))
            continue
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        kwarg = node.args.kwarg
        if kwarg is not None and not _is_canonical_unpack(kwarg.annotation):
            offenders.append((node.lineno, node.name))
    return offenders


def test_kwargs_accepts_canonical_unpack() -> None:
    code = (
        "from typing import TypedDict, Unpack\n"
        "import typing as t\n"
        "class SpecificOptions(TypedDict):\n"
        "    flag: bool\n"
        "def valid_func(**kwargs: Unpack[SpecificOptions]) -> None:\n"
        "    pass\n"
        "def valid_aliased(**kwargs: t.Unpack[SpecificOptions]) -> None:\n"
        "    pass\n"
        "def valid_generic(**kwargs: Unpack[GenericOptions[int]]) -> None:\n"
        "    pass\n"
    )
    assert not _find_unstructured_kwargs(ast.parse(code))


def test_kwargs_rejects_unannotated_and_open_ended() -> None:
    prohibited_cases = [
        "def f(**kwargs): pass",
        "def f(**kwargs: Any): pass",
        "def f(**kwargs: dict[str, Any]): pass",
        "def f(**kwargs: Unpack[Any]): pass",
        "def f(**kwargs: Unpack[dict[str, Any]]): pass",
        "def f(**kwargs: SpecificTypedDict): pass",
        "action = lambda **kwargs: None",
    ]
    for case in prohibited_cases:
        violations = _find_unstructured_kwargs(ast.parse(case))
        assert violations, f"Expected violation for: {case}"


def test_no_unstructured_kwargs_in_production() -> None:
    """Production **kwargs must use canonical Unpack[SpecificTypedDict]."""
    offenders: list[tuple[str, int, str]] = []
    for path in _iter_python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, name in _find_unstructured_kwargs(tree):
            rel = path.relative_to(ROOT).as_posix()
            offenders.append((rel, lineno, name))
    assert not offenders, f"Unstructured **kwargs in production: {offenders}"


# ---------------------------------------------------------------------------
# Negative controls for retained gates
# ---------------------------------------------------------------------------


def test_retained_exception_and_suppression_gates_fail_on_prohibited() -> None:
    tree_bare = ast.parse("try:\n    pass\nexcept:\n    pass")
    bare_handlers = [
        n for n in ast.walk(tree_bare) if isinstance(n, ast.ExceptHandler) and n.type is None
    ]
    assert bare_handlers

    tree_pass = ast.parse("try:\n    pass\nexcept Exception:\n    pass")
    broad_pass = [
        n
        for n in ast.walk(tree_pass)
        if isinstance(n, ast.ExceptHandler)
        and (isinstance(n.type, ast.Name) and n.type.id == "Exception")
        and len(n.body) == 1
        and isinstance(n.body[0], ast.Pass)
    ]
    assert broad_pass

    type_pattern = re.compile(r"#\s*type:\s*ignore(?!\[)")
    assert type_pattern.search("x = 1  # type: ignore")
    assert not type_pattern.search("x = 1  # type: ignore[assignment]")

    noqa_pattern = re.compile(r"^\s*[:\(]\s*\w+", re.IGNORECASE)
    assert not noqa_pattern.match("")
    assert noqa_pattern.match(": F401")


# ---------------------------------------------------------------------------
# Diff budget
# ---------------------------------------------------------------------------


def _get_diff_numstat() -> str:
    """Return `git diff --numstat` output, or raise on failure (fail-closed).

    In CI (actions/checkout), `origin/main` may not exist as a remote ref.
    Fall back to the merge-base of HEAD and main, or GITHUB_BASE_REF.
    """
    base_ref = "origin/main"
    result = subprocess.run(
        ["git", "diff", "--numstat", f"{base_ref}...HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        # Try merge-base of HEAD and main branch
        mb = subprocess.run(
            ["git", "merge-base", "HEAD", "main"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=10,
            check=False,
        )
        if mb.returncode == 0 and mb.stdout.strip():
            base_ref = mb.stdout.strip()
            result = subprocess.run(
                ["git", "diff", "--numstat", f"{base_ref}...HEAD"],
                capture_output=True,
                text=True,
                cwd=ROOT,
                timeout=10,
                check=False,
            )
    if result.returncode != 0:
        raise RuntimeError(
            f"git diff --numstat failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def test_diff_budget_runtime_code_under_limit() -> None:
    """PR runtime-code diff must stay under 400 lines and 10 files.

    Uses `git diff --numstat` for authoritative insertion/deletion counts.
    Fails closed if git is unavailable or returns nonzero.
    """
    try:
        diff = _get_diff_numstat()
    except (subprocess.SubprocessError, FileNotFoundError, RuntimeError) as exc:
        raise AssertionError(f"Cannot evaluate diff budget: {exc}") from exc
    runtime_files = 0
    runtime_lines = 0
    for line in diff.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            raise AssertionError(f"Malformed numstat line: {line!r}")
        insertions_str, deletions_str, filename = parts[0], parts[1], parts[2]
        if insertions_str == "-" or deletions_str == "-":
            continue
        if not _is_runtime_path(filename):
            continue
        runtime_lines += int(insertions_str) + int(deletions_str)
        runtime_files += 1
    assert runtime_files <= RUNTIME_CODE_MAX_FILES, (
        f"PR touches {runtime_files} runtime files (max {RUNTIME_CODE_MAX_FILES})"
    )
    assert runtime_lines <= RUNTIME_CODE_MAX_LINES, (
        f"PR changes {runtime_lines} runtime lines (max {RUNTIME_CODE_MAX_LINES})"
    )
