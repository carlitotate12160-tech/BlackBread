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


def test_modules_import_without_side_effects() -> None:
    assert conductor_contracts.ACTION_PROPOSAL_SCHEMA == "conductor.action_proposal"
    assert callable(conductor_intake.evaluate_proposal)
    assert policy_contracts.POLICY_DECISION_SCHEMA == "policy.decision"
