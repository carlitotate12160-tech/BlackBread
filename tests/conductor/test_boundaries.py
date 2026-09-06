"""Structural boundaries: purity, forbidden dependencies, and no import cycle."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import blackbread.conductor.contracts as conductor_contracts
import blackbread.conductor.intake as conductor_intake
import blackbread.policy.admission as policy_admission
import blackbread.policy.contracts as policy_contracts
from blackbread.policy import runtime_contracts, runtime_gate, runtime_result

SRC = Path(__file__).parents[2] / "src" / "blackbread"

FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "sqlalchemy",
        "asyncpg",
        "alembic",
        "fastapi",
        "starlette",
        "uvicorn",
        "httpx",
        "networkx",
    }
)
FORBIDDEN_BLACKBREAD_MODULES = frozenset(
    {
        "blackbread.database",
        "blackbread.app",
        "blackbread.health",
        "blackbread.models",
        "blackbread.graph.persistence",
        "blackbread.graph.temporal_persistence",
        "blackbread.ledger.append",
    }
)


def _file_package_parts(path: Path, base: Path = SRC) -> tuple[str, ...]:
    """Return the dotted package parts of *path* relative to *base*."""
    rel = path.relative_to(base)
    return ("blackbread", *rel.parts[:-1])


def _resolve_import_from(node: ast.ImportFrom, file_parts: tuple[str, ...]) -> str | None:
    """Resolve an ``ast.ImportFrom`` to its fully qualified base module.

    Absolute imports (level 0) return ``node.module``. Relative imports
    resolve against *file_parts* — the importing file's dotted package —
    so ``from . import foo`` and ``from .sub import bar`` produce correct
    fully qualified names instead of bare or mis-resolved fragments.
    """
    if node.level == 0:
        return node.module
    up = max(1, len(file_parts) - (node.level - 1))
    resolved_pkg = ".".join(file_parts[:up])
    return f"{resolved_pkg}.{node.module}" if node.module else resolved_pkg


def _imported_modules(path: Path, *, base: Path = SRC) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    file_parts = _file_package_parts(path, base)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base_module = _resolve_import_from(node, file_parts)
            if base_module is not None:
                names.add(base_module)
                for alias in node.names:
                    names.add(f"{base_module}.{alias.name}")
    return names


PURE_MODULES = (
    SRC / "conductor" / "contracts.py",
    SRC / "conductor" / "intake.py",
    SRC / "policy" / "contracts.py",
    SRC / "policy" / "admission_contracts.py",
    SRC / "policy" / "admission.py",
    SRC / "policy" / "runtime_contracts.py",
    SRC / "policy" / "runtime_result.py",
    SRC / "policy" / "runtime_gate.py",
)


@pytest.mark.parametrize("path", PURE_MODULES, ids=lambda item: item.name)
def test_no_forbidden_framework_or_persistence_imports(path: Path) -> None:
    imported = _imported_modules(path)
    for name in imported:
        root = name.split(".")[0]
        assert root not in FORBIDDEN_IMPORT_ROOTS, f"{path.name} imports {name}"
        assert name not in FORBIDDEN_BLACKBREAD_MODULES, f"{path.name} imports {name}"


def test_intake_boundary_has_no_wall_clock_or_uuid_generation() -> None:
    source = (SRC / "conductor" / "intake.py").read_text(encoding="utf-8")
    for banned in ("datetime.now", "datetime.utcnow", "time.time", "uuid4", "uuid.uuid1"):
        assert banned not in source, f"intake must not call {banned}"


def test_admission_boundary_has_no_wall_clock_or_io() -> None:
    source = (SRC / "policy" / "admission.py").read_text(encoding="utf-8")
    for banned in ("datetime.now", "datetime.utcnow", "time.time", "open(", "getenv"):
        assert banned not in source, f"admission must not call {banned}"


def test_policy_contracts_does_not_depend_on_conductor_orchestration() -> None:
    imported = _imported_modules(SRC / "policy" / "contracts.py")
    assert "blackbread.conductor.intake" not in imported


def test_no_import_cycle_between_contracts() -> None:
    conductor_imports = _imported_modules(SRC / "conductor" / "contracts.py")
    assert not any(name.startswith("blackbread.policy") for name in conductor_imports)


def test_target_canonicalization_reuses_single_scope_authority() -> None:
    # The contract's scope authority is the pure leaf module, never the graph
    # read-model: importing a proposal contract must not drag graph.
    conductor_imports = _imported_modules(SRC / "conductor" / "contracts.py")
    assert "blackbread.scope.canonical" in conductor_imports
    assert not any(name.startswith("blackbread.graph") for name in conductor_imports)


def test_scope_authority_is_a_pure_leaf() -> None:
    # The single scope authority depends on no other blackbread package, so every
    # consumer (ledger, conductor, graph) can reuse it without a layer inversion.
    scope_imports = _imported_modules(SRC / "scope" / "canonical.py")
    assert not any(name.startswith("blackbread.") for name in scope_imports)


def test_ledger_catalog_reuses_the_scope_authority() -> None:
    catalog_imports = _imported_modules(SRC / "ledger" / "catalog.py")
    assert "blackbread.scope.canonical" in catalog_imports


def test_admission_contracts_reuse_conductor_types_without_graph_coupling() -> None:
    # The admission input contracts reuse the conductor's canonical scalar and target
    # types; they must not duplicate a scope authority nor drag the graph read-model.
    imported = _imported_modules(SRC / "policy" / "admission_contracts.py")
    assert "blackbread.conductor.contracts" in imported
    assert not any(name.startswith("blackbread.graph") for name in imported)


def test_runtime_gate_contracts_are_intentionally_unwired_and_non_authoritative() -> None:
    runtime_path = SRC / "policy" / "runtime_contracts.py"
    runtime_imports = _imported_modules(runtime_path)
    assert "blackbread.conductor.contracts" in runtime_imports
    assert "blackbread.conductor.intake" not in runtime_imports
    assert not any(name.startswith("blackbread.graph") for name in runtime_imports)
    for name in runtime_imports:
        assert name.split(".")[0] not in FORBIDDEN_IMPORT_ROOTS

    runtime_source = runtime_path.read_text(encoding="utf-8")
    assert "from blackbread.conductor import" not in runtime_source
    assert "conductor.intake" not in runtime_source

    gate_path = SRC / "policy" / "runtime_gate.py"
    for path in SRC.rglob("*.py"):
        if path in {runtime_path, gate_path}:
            continue
        assert "blackbread.policy.runtime_contracts" not in _imported_modules(path)

    intake_source = (SRC / "conductor" / "intake.py").read_text(encoding="utf-8")
    forbidden = ("ALLOW", "APPROVAL_REQUIRED", "lease_id", "work_order_id", "executable_token")
    for item in forbidden:
        assert item not in intake_source

    forbidden_fields = {"outcome", "decision_id", "lease_id", "work_order_id", "executable_token"}
    assert forbidden_fields.isdisjoint(runtime_contracts.RuntimeGateSnapshot.model_fields)


def test_runtime_gate_evaluator_is_intentionally_unwired_and_non_authoritative() -> None:
    gate_path = SRC / "policy" / "runtime_gate.py"
    result_path = SRC / "policy" / "runtime_result.py"
    gate_imports = _imported_modules(gate_path)
    assert "blackbread.policy.runtime_contracts" in gate_imports
    assert "blackbread.policy.runtime_result" in gate_imports
    assert "blackbread.conductor.intake" not in gate_imports

    isolated = {gate_path, result_path}
    for path in SRC.rglob("*.py"):
        if path in isolated:
            continue
        imports = _imported_modules(path)
        assert "blackbread.policy.runtime_gate" not in imports
        assert "blackbread.policy.runtime_result" not in imports

    forbidden = {
        "allow",
        "decision_id",
        "policy_decision_id",
        "lease_id",
        "work_order_id",
        "executable_token",
        "target_effect",
    }
    assert forbidden.isdisjoint(runtime_result.RuntimeGateResult.model_fields)
    assert "ALLOW" not in result_path.read_text(encoding="utf-8")


def test_imported_modules_resolves_absolute_package_level_imports(tmp_path: Path) -> None:
    # from blackbread.policy import runtime_gate must produce the full module path.
    base = tmp_path / "src" / "blackbread"
    pkg = base / "policy"
    pkg.mkdir(parents=True)
    file = pkg / "_test_absolute.py"
    file.write_text("from blackbread.policy import runtime_gate\n", encoding="utf-8")
    imported = _imported_modules(file, base=base)
    assert "blackbread.policy.runtime_gate" in imported
    assert "blackbread.policy" in imported


def test_imported_modules_resolves_dot_relative_imports(tmp_path: Path) -> None:
    # from . import runtime_gate in blackbread.policy must resolve to the full module.
    base = tmp_path / "src" / "blackbread"
    pkg = base / "policy"
    pkg.mkdir(parents=True)
    file = pkg / "_test_dot_relative.py"
    file.write_text("from . import runtime_gate\n", encoding="utf-8")
    imported = _imported_modules(file, base=base)
    assert "blackbread.policy.runtime_gate" in imported
    assert "blackbread.policy" in imported


def test_imported_modules_resolves_dotted_relative_imports(tmp_path: Path) -> None:
    # from .runtime_gate import evaluate_runtime_gates must resolve the submodule.
    base = tmp_path / "src" / "blackbread"
    pkg = base / "policy"
    pkg.mkdir(parents=True)
    file = pkg / "_test_dotted_relative.py"
    file.write_text("from .runtime_gate import evaluate_runtime_gates\n", encoding="utf-8")
    imported = _imported_modules(file, base=base)
    assert "blackbread.policy.runtime_gate" in imported


def test_imported_modules_resolves_parent_relative_imports(tmp_path: Path) -> None:
    # from .. import runtime_gate in a subpackage resolves to the parent package.
    base = tmp_path / "src" / "blackbread"
    subpkg = base / "policy" / "subpkg"
    subpkg.mkdir(parents=True)
    file = subpkg / "_test_parent_relative.py"
    file.write_text("from .. import runtime_gate\n", encoding="utf-8")
    imported = _imported_modules(file, base=base)
    assert "blackbread.policy.runtime_gate" in imported


def test_imported_modules_preserves_direct_import_statements(tmp_path: Path) -> None:
    # import blackbread.policy.runtime_gate is still detected.
    base = tmp_path / "src" / "blackbread"
    pkg = base / "policy"
    pkg.mkdir(parents=True)
    file = pkg / "_test_direct_import.py"
    file.write_text("import blackbread.policy.runtime_gate\n", encoding="utf-8")
    imported = _imported_modules(file, base=base)
    assert "blackbread.policy.runtime_gate" in imported


def test_imported_modules_does_not_falsely_reject_valid_imports(tmp_path: Path) -> None:
    # A mix of stdlib, relative, and absolute imports all resolve correctly.
    base = tmp_path / "src" / "blackbread"
    pkg = base / "policy"
    pkg.mkdir(parents=True)
    file = pkg / "_test_valid.py"
    file.write_text(
        "import os\n"
        "from . import runtime_gate\n"
        "from blackbread.conductor.contracts import ActionProposal\n",
        encoding="utf-8",
    )
    imported = _imported_modules(file, base=base)
    assert "os" in imported
    assert "blackbread.policy.runtime_gate" in imported
    assert "blackbread.conductor.contracts" in imported
    assert "blackbread.conductor.contracts.ActionProposal" in imported


def test_modules_import_without_side_effects() -> None:
    assert conductor_contracts.ACTION_PROPOSAL_SCHEMA == "conductor.action_proposal"
    assert callable(conductor_intake.evaluate_proposal)
    assert callable(policy_admission.evaluate_admission)
    assert callable(runtime_gate.evaluate_runtime_gates)
    assert policy_contracts.POLICY_DECISION_SCHEMA == "policy.decision"
    assert runtime_contracts.RUNTIME_GATE_SCHEMA == "policy.runtime.gate"
    assert runtime_result.RUNTIME_GATE_RESULT_SCHEMA == "policy.runtime.gate.result"
