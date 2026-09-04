"""Structural boundaries: purity, forbidden dependencies, and no import cycle."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import blackbread.conductor.contracts as conductor_contracts
import blackbread.conductor.intake as conductor_intake
import blackbread.policy.contracts as policy_contracts

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


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


PURE_MODULES = (
    SRC / "conductor" / "contracts.py",
    SRC / "conductor" / "intake.py",
    SRC / "policy" / "contracts.py",
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


def test_modules_import_without_side_effects() -> None:
    assert conductor_contracts.ACTION_PROPOSAL_SCHEMA == "conductor.action_proposal"
    assert callable(conductor_intake.evaluate_proposal)
    assert policy_contracts.POLICY_DECISION_SCHEMA == "policy.decision"
