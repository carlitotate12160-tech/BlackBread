"""Documentation-integrity governance for protected-base diffs.

Detects line-budget gaming that strips comments or docstrings from a module
whose executable code did not shrink. Ruff cannot see this because deleting
documentation is valid Python. The execution-contract density-gaming rule
forbids it; this module makes that rule enforceable in the size gate.
"""

from __future__ import annotations

import ast
import difflib
import io
import tokenize
from collections.abc import Mapping
from dataclasses import dataclass

# Require the documentation loss to exceed both an absolute line count and a
# significant fraction of the original documentation. The ratio (just above 1/3)
# catches deliberate stripping while tolerating ordinary refactor cleanup.
DOCUMENTATION_LOSS_MIN_LINES = 5
DOCUMENTATION_LOSS_MIN_RATIO = 0.34

# Tokens that do not make a line count as executable code for the purpose of
# distinguishing documentation-only lines from code lines.
_IGNORED_CODE_TOKENS = frozenset(
    {
        tokenize.ENCODING,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
        tokenize.COMMENT,
        tokenize.STRING,
        tokenize.ERRORTOKEN,
    }
)

# Minimum token-signature similarity for a head-only file to be treated as a
# rename of a base-only file. Comparing code-token streams makes the check
# insensitive to removed comments and docstrings.
_RENAME_SIMILARITY_THRESHOLD = 0.80

# When documentation is removed together with executable code, the code shrink
# must be at least this fraction of the documentation loss. This prevents the
# one-line-trick bypass: removing a single assignment does not justify stripping
# a large docstring.
_CODE_SHRINK_TO_DOC_LOSS_MIN_RATIO = 0.5


@dataclass(frozen=True, slots=True)
class _ModuleShape:
    code_lines: int
    documentation_lines: int


def _docstring_rows(source: str, path: str) -> set[int]:
    tree = ast.parse(source, filename=path)
    rows: set[int] = set()
    documented = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, documented):
            continue
        if ast.get_docstring(node, clean=False) is None or not node.body:
            continue
        expression = node.body[0]
        end_line = expression.end_lineno or expression.lineno
        rows.update(range(expression.lineno, end_line + 1))
    return rows


def _comment_rows(source: str) -> set[int]:
    rows: set[int] = set()
    try:
        tokens = tokenize.tokenize(io.BytesIO(source.encode()).readline)
    except (tokenize.TokenError, SyntaxError):
        return rows
    for token in tokens:
        if token.type == tokenize.COMMENT:
            rows.update(range(token.start[0], token.end[0] + 1))
    return rows


def _code_token_lines(source: str) -> set[int]:
    rows: set[int] = set()
    try:
        tokens = tokenize.tokenize(io.BytesIO(source.encode()).readline)
    except (tokenize.TokenError, SyntaxError):
        return rows
    for token in tokens:
        if token.type in _IGNORED_CODE_TOKENS:
            continue
        rows.update(range(token.start[0], token.end[0] + 1))
    return rows


def _token_signature(source: str) -> str:
    parts: list[str] = []
    try:
        tokens = tokenize.tokenize(io.BytesIO(source.encode()).readline)
    except (tokenize.TokenError, SyntaxError):
        return ""
    for token in tokens:
        if token.type in _IGNORED_CODE_TOKENS:
            continue
        parts.append(token.string)
    return " ".join(parts)


def _module_shape(source: str, path: str) -> _ModuleShape:
    docstring_rows = _docstring_rows(source, path)
    comment_rows = _comment_rows(source)
    code_rows = _code_token_lines(source)
    documentation_rows = docstring_rows | comment_rows
    return _ModuleShape(
        code_lines=len(code_rows),
        documentation_lines=len(documentation_rows),
    )


def _stripping_violation(path: str, base: str, head: str) -> str | None:
    before = _module_shape(base, path)
    after = _module_shape(head, path)
    lost = before.documentation_lines - after.documentation_lines
    ratio_floor = before.documentation_lines * DOCUMENTATION_LOSS_MIN_RATIO
    if lost <= DOCUMENTATION_LOSS_MIN_LINES and lost <= ratio_floor:
        return None
    code_lost = before.code_lines - after.code_lines
    if code_lost > 0 and code_lost >= lost * _CODE_SHRINK_TO_DOC_LOSS_MIN_RATIO:
        return None
    return (
        f"{path}: documentation dropped by {lost} lines while code did not shrink "
        f"({before.code_lines} -> {after.code_lines} code lines); density gaming is "
        "forbidden. STOP and split the slice instead of stripping documentation."
    )


def _in_scope(path: str) -> bool:
    return path.startswith(("src/blackbread/", "tests/")) and path.endswith(".py")


def _find_renames(
    base_files: Mapping[str, str],
    head_files: Mapping[str, str],
) -> dict[str, str]:
    """Match head-only paths against base-only paths using code-token similarity.

    This catches module renames that would otherwise be treated as new files,
    allowing documentation-integrity checks to see whether documentation was
    stripped during the rename.
    """
    base_only = [p for p in base_files if _in_scope(p) and p not in head_files]
    head_only = [p for p in head_files if _in_scope(p) and p not in base_files]
    if not base_only or not head_only:
        return {}

    base_sigs = {p: _token_signature(base_files[p]) for p in base_only}
    head_sigs = {p: _token_signature(head_files[p]) for p in head_only}

    candidates: list[tuple[float, str, str]] = []
    for head_path, head_sig in head_sigs.items():
        if not head_sig:
            continue
        for base_path, base_sig in base_sigs.items():
            if not base_sig:
                continue
            ratio = difflib.SequenceMatcher(None, base_sig, head_sig).ratio()
            if ratio >= _RENAME_SIMILARITY_THRESHOLD:
                candidates.append((ratio, head_path, base_path))

    candidates.sort(reverse=True)
    matched: dict[str, str] = {}
    used_bases: set[str] = set()
    for _ratio, head_path, base_path in candidates:
        if head_path in matched or base_path in used_bases:
            continue
        matched[head_path] = base_path
        used_bases.add(base_path)

    return matched


def evaluate_documentation_integrity(
    base_files: Mapping[str, str],
    head_files: Mapping[str, str],
) -> list[str]:
    violations: list[str] = []
    renames = _find_renames(base_files, head_files)
    for path, head_source in sorted(head_files.items()):
        base_source = base_files.get(path)
        if base_source is None:
            renamed_base = renames.get(path)
            if renamed_base is not None:
                base_source = base_files.get(renamed_base)
        if base_source is None:
            continue
        if not _in_scope(path):
            continue
        try:
            violation = _stripping_violation(path, base_source, head_source)
        except SyntaxError as exc:
            violations.append(
                f"{path}: syntax error prevents documentation-integrity check ({exc})"
            )
            continue
        if violation is not None:
            violations.append(violation)
    return violations
