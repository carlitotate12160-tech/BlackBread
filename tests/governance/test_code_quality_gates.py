"""Anti-spaghetti, anti-redundancy, and supply-chain governance tests.

These tests enforce the engineering guardrails in AGENTS.md and
.devin/rules/blackbread.md deterministically in CI.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from collections.abc import Iterator
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
SRC = ROOT / "src" / "blackbread"
TESTS = ROOT / "tests"

PRODUCTION_MODULE_WARNING_LINES = 320
ACTIVE_CAPABILITY_LIFECYCLES = ("IMPLEMENTED", "VERIFIED", "RELEASED")


def _iter_python_files(base: Path) -> list[Path]:
    return sorted(base.rglob("*.py"))


def _module_name(path: Path) -> str:
    rel = str(path.relative_to(SRC).with_suffix("")).replace("/", ".")
    return f"blackbread.{rel}"


def _extract_blackbread_imports(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("blackbread.")
        ):
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("blackbread."):
                    imports.add(alias.name)
    return imports


def _build_import_graph() -> dict[str, set[str]]:
    modules: dict[str, set[str]] = {}
    for path in _iter_python_files(SRC):
        if "__pycache__" in path.parts or path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules[_module_name(path)] = _extract_blackbread_imports(tree)
    return modules


def _has_cycle(
    start: str,
    modules: dict[str, set[str]],
    visited: set[str],
    path_stack: set[str],
) -> bool:
    if start in path_stack:
        return True
    if start in visited:
        return False
    visited.add(start)
    path_stack.add(start)
    for dep in modules.get(start, set()):
        if _has_cycle(dep, modules, visited, path_stack):
            return True
    path_stack.discard(start)
    return False


def _iter_test_functions(base: Path) -> Iterator[tuple[str, str]]:
    for path in _iter_python_files(base):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
                "test_"
            ):
                yield (node.name, rel)


def test_no_duplicate_test_names() -> None:
    """Test function names must be unique across the entire test suite."""
    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str, str]] = []
    for name, rel in _iter_test_functions(TESTS):
        if name in seen:
            duplicates.append((name, seen[name], rel))
        else:
            seen[name] = rel
    assert not duplicates, f"Duplicate test names found: {duplicates}"


def test_no_circular_imports_in_production_code() -> None:
    """Production modules must not have circular import dependencies."""
    modules = _build_import_graph()
    cycles: list[str] = []
    for mod in modules:
        if _has_cycle(mod, modules, set(), set()):
            cycles.append(mod)
    assert not cycles, f"Circular imports detected in: {cycles}"


def test_pyproject_has_no_floating_version_constraints() -> None:
    """Dependencies must not use floating ranges (latest, *, unbounded >=)."""
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject.get("project", {}).get("dependencies", [])
    dev_deps = (
        pyproject.get("dependency-groups", {}).get("dev", [])
        if pyproject.get("dependency-groups")
        else []
    )
    all_deps = list(deps) + list(dev_deps)
    floating: list[str] = []
    for dep in all_deps:
        if dep.strip() == "*" or "latest" in dep.lower():
            floating.append(dep)
        if dep.startswith(">=") and not any(c in dep for c in ["<", ",", "==", "~="]):
            floating.append(dep)
    assert not floating, f"Floating version constraints found: {floating}"
    assert "version" in lock, "uv.lock must exist and be populated"


def test_docker_images_are_digest_pinned() -> None:
    """All Docker images in CI, Compose, and Dockerfile must be digest-pinned."""
    files_to_check = [
        ROOT / ".github" / "workflows" / "ci.yml",
        ROOT / "compose.yaml",
        ROOT / "Dockerfile",
    ]
    image_pattern = re.compile(r"(?:image:|FROM)\s+([^\s]+)", re.IGNORECASE)
    offenders: list[tuple[str, str]] = []
    for path in files_to_check:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for match in image_pattern.finditer(text):
            image = match.group(1).strip().strip("\"'")
            if "@" not in image and not image.startswith("scratch"):
                offenders.append((path.relative_to(ROOT).as_posix(), image))
    assert not offenders, f"Docker images without digest pin: {offenders}"


def test_github_actions_are_sha_pinned() -> None:
    """All GitHub Actions in workflows must be pinned to a 40-char SHA."""
    workflows_dir = ROOT / ".github" / "workflows"
    if not workflows_dir.exists():
        return
    sha_pattern = re.compile(r"^[^@]+@[0-9a-f]{40}")
    offenders: list[tuple[str, str]] = []
    for path in sorted(workflows_dir.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        uses_matches = re.findall(r"uses:\s+(\S+)", text)
        for uses_raw in uses_matches:
            uses = uses_raw.strip().strip("\"'")
            if uses.startswith("./"):
                continue
            if not sha_pattern.match(uses):
                offenders.append((path.relative_to(ROOT).as_posix(), uses))
    assert not offenders, f"GitHub Actions without SHA pin: {offenders}"


def test_capability_registry_tools_have_supply_chain_pins() -> None:
    """Active capabilities must have non-null supply_chain_pin."""
    registry = json.loads(
        (ROOT / "config" / "capability-registry.json").read_text(encoding="utf-8")
    )
    offenders: list[tuple[str, str]] = []
    for cap in registry.get("capabilities", []):
        lifecycle = cap.get("lifecycle", "PLANNED")
        pin = cap.get("supply_chain_pin")
        if lifecycle in ACTIVE_CAPABILITY_LIFECYCLES and not pin:
            offenders.append((cap["id"], lifecycle))
    assert not offenders, f"Active capabilities without supply chain pin: {offenders}"


def test_ci_jobs_have_no_skip_or_continue_on_error() -> None:
    """CI jobs must not use if-conditions or continue-on-error to skip required gates."""
    ci_path = ROOT / ".github" / "workflows" / "ci.yml"
    if not ci_path.exists():
        return
    text = ci_path.read_text(encoding="utf-8")
    quoted = re.sub(r"^on:", '"on":', text, count=1, flags=re.MULTILINE)
    workflow = yaml.safe_load(quoted)
    jobs = workflow.get("jobs", {})
    offenders: list[str] = []
    for name, job in jobs.items():
        if "if" in job:
            offenders.append(f"{name}: has 'if' condition")
        if "continue-on-error" in job:
            offenders.append(f"{name}: has continue-on-error")
        for step in job.get("steps", []):
            if "continue-on-error" in step:
                offenders.append(f"{name}.step: has continue-on-error")
    assert not offenders, f"CI jobs with skip/continue-on-error: {offenders}"
