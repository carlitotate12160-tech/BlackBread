from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath


class BudgetConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class QualityCaps:
    production_module: int
    function: int
    test_module: int

    @classmethod
    def from_json(cls, source: str) -> QualityCaps:
        values = json.loads(source)
        if values.get("schema_version") != 1:
            raise BudgetConfigurationError("quality budget schema_version must be 1")
        caps = cls(
            production_module=values["production_module_max_lines"],
            function=values["function_max_lines"],
            test_module=values["test_module_max_lines"],
        )
        if any(type(value) is not int or value < 1 for value in caps.values()):
            raise BudgetConfigurationError("quality budget caps must be positive integers")
        return caps

    def values(self) -> tuple[int, int, int]:
        return (self.production_module, self.function, self.test_module)


def cap_increases(base: QualityCaps, head: QualityCaps) -> list[str]:
    names = ("production_module", "function", "test_module")
    return [
        f"{name}: {base_value} -> {head_value}"
        for name, base_value, head_value in zip(names, base.values(), head.values(), strict=True)
        if head_value > base_value
    ]


def _line_count(source: str) -> int:
    return len(source.splitlines())


def _function_lengths(source: str, path: str) -> list[tuple[str, int]]:
    tree = ast.parse(source, filename=path)
    lengths: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_line = node.end_lineno or node.lineno
            lengths.append((node.name, end_line - node.lineno + 1))
    return lengths


def _module_violation(
    path: str,
    source: str,
    base_source: str | None,
    cap: int,
) -> str | None:
    current_lines = _line_count(source)
    base_lines = _line_count(base_source) if base_source is not None else 0
    allowed = max(base_lines, cap)
    if current_lines > allowed:
        return f"{path}: {current_lines} lines exceeds protected allowance {allowed}"
    return None


def _function_violations(
    path: str,
    source: str,
    base_source: str | None,
    cap: int,
) -> list[str]:
    current = _function_lengths(source, path)
    base = _function_lengths(base_source, path) if base_source is not None else []
    base_by_name: dict[str, list[int]] = {}
    current_counts: dict[str, int] = {}
    for name, length in base:
        base_by_name.setdefault(name, []).append(length)
    for name, _length in current:
        current_counts[name] = current_counts.get(name, 0) + 1

    seen: dict[str, int] = {}
    violations: list[str] = []
    for name, length in current:
        occurrence = seen.get(name, 0)
        seen[name] = occurrence + 1
        protected = base_by_name.get(name, [])
        allowed = max(cap, protected[occurrence] if occurrence < len(protected) else 0)
        if length > allowed:
            suffix = f"#{occurrence + 1}" if current_counts[name] > 1 else ""
            violations.append(
                f"{path}:{name}{suffix}: {length} lines exceeds protected allowance {allowed}"
            )
    return violations


def evaluate_size_budget(
    base_files: Mapping[str, str],
    head_files: Mapping[str, str],
    caps: QualityCaps,
) -> list[str]:
    violations: list[str] = []
    for path, source in sorted(head_files.items()):
        base_source = base_files.get(path)
        if path.startswith("src/blackbread/") and path.endswith(".py"):
            module = _module_violation(path, source, base_source, caps.production_module)
            if module is not None:
                violations.append(module)
            violations.extend(_function_violations(path, source, base_source, caps.function))
        elif (
            path.startswith("tests/")
            and path.endswith(".py")
            and PurePosixPath(path).name != "conftest.py"
        ):
            module = _module_violation(path, source, base_source, caps.test_module)
            if module is not None:
                violations.append(module)
    return violations
