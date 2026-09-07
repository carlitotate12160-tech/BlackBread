"""Structural boundaries: purity, forbidden dependencies, and no import cycle."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args

import pytest

import blackbread.conductor.contracts as conductor_contracts
import blackbread.conductor.intake as conductor_intake
import blackbread.policy.admission as policy_admission
import blackbread.policy.contracts as policy_contracts
from blackbread.policy import runtime_contracts, runtime_gate, runtime_result
from blackbread.policy.decision_v2 import (
    POLICY_DECISION_V2_SCHEMA,
    FinalDecisionOutcome,
    PolicyDecisionV2,
)
from blackbread.policy.evaluation import evaluate_policy

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

_PURITY_BANNED_CALLS = frozenset(
    {
        "datetime.now",
        "datetime.utcnow",
        "time.time",
        "time.monotonic",
        "time.sleep",
        "open(",
        "getenv",
        "environ",
        "os.system",
        "subprocess",
        "socket",
        "httpx",
        "requests",
        "uuid1",
        "uuid4",
    }
)


def _module_dotted_name(path: Path, *, source_root: Path = SRC) -> str:
    """Return the dotted module name for a source file under source_root."""
    relative = path.relative_to(source_root).with_suffix("")
    parts = list(relative.parts)
    return "blackbread." + ".".join(parts)


def _current_package(path: Path, *, source_root: Path = SRC) -> list[str]:
    """Return the package parts for a source file.

    The module filename is removed; only the containing package remains.
    Example: ``src/blackbread/policy/consumer.py`` → ``["blackbread", "policy"]``.
    """
    relative = path.relative_to(source_root).with_suffix("")
    parts = list(relative.parts)
    if len(parts) <= 1:
        return ["blackbread"]
    return ["blackbread", *parts[:-1]]


def _add_absolute_import_from(node: ast.ImportFrom, names: set[str]) -> None:
    """Add dotted names from an absolute ``from X import Y`` (level == 0)."""
    base = node.module
    if base is None:
        return
    names.add(base)
    for alias in node.names:
        if alias.name != "*":
            names.add(f"{base}.{alias.name}")


def _add_relative_import_from(
    node: ast.ImportFrom,
    path: Path,
    names: set[str],
    *,
    source_root: Path,
) -> None:
    """Add dotted names from a relative ``from .X import Y`` (level > 0).

    Resolves the current package from the file path, ascends ``level - 1``
    times, then appends ``node.module`` when present.  Imports that ascend
    beyond the ``blackbread`` package root are silently skipped rather than
    mapped to an invented module.
    """
    pkg_parts = _current_package(path, source_root=source_root)
    ascents = node.level - 1
    if ascents > 0 and len(pkg_parts) <= ascents:
        return
    resolved_parts = pkg_parts[: len(pkg_parts) - ascents] if ascents > 0 else pkg_parts
    if node.module is not None:
        resolved_parts = [*resolved_parts, node.module]
    base = ".".join(resolved_parts)
    names.add(base)
    for alias in node.names:
        if alias.name != "*":
            names.add(f"{base}.{alias.name}")


def _imported_modules(path: Path, *, source_root: Path = SRC) -> set[str]:
    """Extract all imported module names from a Python source file.

    Resolves relative imports (``from . import X``, ``from .X import Y``,
    ``from ..policy import Z``) to their absolute dotted names so that
    equivalent import forms are normalized and boundary tests cannot be
    bypassed by import syntax.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                _add_absolute_import_from(node, names)
            else:
                _add_relative_import_from(node, path, names, source_root=source_root)
    return names


PURE_MODULES = (
    SRC / "conductor" / "contracts.py",
    SRC / "conductor" / "intake.py",
    SRC / "policy" / "contracts.py",
    SRC / "policy" / "admission_contracts.py",
    SRC / "policy" / "admission.py",
    SRC / "policy" / "runtime_contracts.py",
    SRC / "policy" / "runtime_gate.py",
    SRC / "policy" / "runtime_result.py",
    SRC / "policy" / "decision_v2.py",
    SRC / "policy" / "evaluation.py",
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

    # The composed runtime-gate evaluator and final policy evaluator are legitimate consumers.
    gate_path = SRC / "policy" / "runtime_gate.py"
    eval_path = SRC / "policy" / "evaluation.py"
    for path in SRC.rglob("*.py"):
        if path in {runtime_path, gate_path, eval_path}:
            continue
        assert "blackbread.policy.runtime_contracts" not in _imported_modules(path)

    intake_source = (SRC / "conductor" / "intake.py").read_text(encoding="utf-8")
    forbidden = ("ALLOW", "APPROVAL_REQUIRED", "lease_id", "work_order_id", "executable_token")
    for item in forbidden:
        assert item not in intake_source

    forbidden_fields = {"outcome", "decision_id", "lease_id", "work_order_id", "executable_token"}
    assert forbidden_fields.isdisjoint(runtime_contracts.RuntimeGateSnapshot.model_fields)


def test_runtime_gate_evaluator_is_intentionally_unwired_and_non_authoritative() -> None:
    # The composed evaluator reuses admission and the runtime input/result contracts. It must not
    # reach orchestration, the graph read-model, or any framework/persistence, and must never depend
    # on the rejected serializable admission-to-runtime binding.
    gate_path = SRC / "policy" / "runtime_gate.py"
    result_path = SRC / "policy" / "runtime_result.py"
    gate_imports = _imported_modules(gate_path)
    assert "blackbread.policy.admission" in gate_imports
    assert "blackbread.policy.runtime_contracts" in gate_imports
    assert "blackbread.policy.runtime_result" in gate_imports
    assert "blackbread.conductor.intake" not in gate_imports
    assert "blackbread.policy.admission_runtime" not in gate_imports
    assert not any(name.startswith("blackbread.graph") for name in gate_imports)
    for name in (*gate_imports, *_imported_modules(result_path)):
        assert name.split(".")[0] not in FORBIDDEN_IMPORT_ROOTS
        assert name not in FORBIDDEN_BLACKBREAD_MODULES

    # Intentional non-wiring: no production entry point consumes the evaluator or its result yet.
    # M1.4b2c pure final policy evaluator is the authorized consumer of the runtime gate.
    # The decision_v2 object is allowed to import the reason vocabulary from runtime_result.
    eval_path = SRC / "policy" / "evaluation.py"
    decision_v2_path = SRC / "policy" / "decision_v2.py"

    isolated_gate = {gate_path, eval_path}
    isolated_result = {gate_path, result_path, eval_path, decision_v2_path}

    for path in SRC.rglob("*.py"):
        imports = _imported_modules(path)
        if path not in isolated_gate:
            assert "blackbread.policy.runtime_gate" not in imports
        if path not in isolated_result:
            assert "blackbread.policy.runtime_result" not in imports

    # The result grants no execution authority.
    forbidden = {
        "allow",
        "decision_id",
        "policy_decision_id",
        "lease_id",
        "work_order_id",
        "executable_token",
        "target_effect",
        "capability_activation",
    }
    assert forbidden.isdisjoint(runtime_result.RuntimeGateResult.model_fields)
    assert "ALLOW" not in get_args(runtime_result.RuntimeGateOutcome)


@pytest.mark.parametrize(
    "path",
    [SRC / "policy" / "decision_v2.py", SRC / "policy" / "evaluation.py"],
    ids=["decision_v2", "evaluation"],
)
def test_policy_v2_modules_are_pure(path: Path) -> None:
    """decision_v2 and evaluation must not touch framework, persistence, filesystem,
    environment, wall-clock, network, or UUID generation."""
    source = path.read_text(encoding="utf-8")
    for banned in _PURITY_BANNED_CALLS:
        assert banned not in source, f"{path.name} must not call {banned}"
    imported = _imported_modules(path)
    for name in imported:
        root = name.split(".")[0]
        assert root not in FORBIDDEN_IMPORT_ROOTS, f"{path.name} imports {name}"
        assert name not in FORBIDDEN_BLACKBREAD_MODULES, f"{path.name} imports {name}"


def test_imported_modules_resolves_equivalent_import_forms(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    """_imported_modules must normalize every equivalent import form to the
    same absolute dotted name so boundary tests cannot be bypassed by import
    syntax.  Uses synthetic source files — never real production modules — so
    the proof is independent of the import style currently used in the codebase.
    """
    root = tmp_path / "src" / "blackbread"
    (root / "policy").mkdir(parents=True)
    (root / "conductor").mkdir(parents=True)

    cases: list[tuple[str, Path, str, set[str], set[str]]] = [
        # (test_id, synthetic_path, source, required_present, required_absent)
        (
            "direct_import",
            root / "policy" / "consumer.py",
            "import blackbread.policy.evaluation\n",
            {"blackbread.policy.evaluation"},
            set(),
        ),
        (
            "package_qualified",
            root / "policy" / "consumer.py",
            "from blackbread.policy import evaluation\n",
            {"blackbread.policy.evaluation"},
            set(),
        ),
        (
            "relative_dot_import",
            root / "policy" / "consumer.py",
            "from . import evaluation\n",
            {"blackbread.policy.evaluation"},
            {"blackbread.policy.consumer.evaluation", "blackbread.policy.consumer"},
        ),
        (
            "relative_dot_module",
            root / "policy" / "consumer.py",
            "from .evaluation import evaluate_policy\n",
            {"blackbread.policy.evaluation"},
            {"blackbread.policy.consumer.evaluation", "blackbread.policy.consumer"},
        ),
        (
            "parent_relative",
            root / "conductor" / "consumer.py",
            "from ..policy import evaluation\n",
            {"blackbread.policy.evaluation"},
            set(),
        ),
        (
            "absolute_decision_v2",
            root / "conductor" / "consumer.py",
            "from blackbread.policy.decision_v2 import PolicyDecisionV2\n",
            {"blackbread.policy.decision_v2"},
            set(),
        ),
    ]

    for test_id, syn_path, source, required_present, required_absent in cases:
        syn_path.write_text(source, encoding="utf-8")
        imported = _imported_modules(syn_path, source_root=root)
        for expected in required_present:
            assert expected in imported, f"[{test_id}] expected {expected!r} in {imported}"
        for forbidden in required_absent:
            assert forbidden not in imported, f"[{test_id}] forbidden {forbidden!r} in {imported}"


def test_policy_evaluator_is_intentionally_unwired_and_non_authoritative() -> None:
    """The final policy evaluator and PolicyDecisionV2 are the authorized consumers
    of the runtime-gate evaluator and result.  No other production module may
    import them.  The decision grants no execution authority."""
    eval_path = SRC / "policy" / "evaluation.py"
    decision_v2_path = SRC / "policy" / "decision_v2.py"

    # evaluation imports runtime_gate, runtime_contracts, and decision_v2.
    eval_imports = _imported_modules(eval_path)
    assert "blackbread.policy.runtime_gate" in eval_imports
    assert "blackbread.policy.runtime_contracts" in eval_imports
    assert "blackbread.policy.decision_v2" in eval_imports

    # decision_v2 imports runtime_result for the reason vocabulary.
    decision_imports = _imported_modules(decision_v2_path)
    assert "blackbread.policy.runtime_result" in decision_imports

    # No other production module imports evaluation or decision_v2.
    for path in SRC.rglob("*.py"):
        if path in {eval_path, decision_v2_path}:
            continue
        imports = _imported_modules(path)
        assert "blackbread.policy.evaluation" not in imports, f"{path.name} imports evaluation"
        assert "blackbread.policy.decision_v2" not in imports, f"{path.name} imports decision_v2"

    # PolicyDecisionV2 has no lease, WorkOrder, token, activation, or target-effect field.
    forbidden_decision_fields = {
        "lease_id",
        "work_order_id",
        "executable_token",
        "activation",
        "target_effect",
        "capability_activation",
    }
    assert forbidden_decision_fields.isdisjoint(PolicyDecisionV2.model_fields)

    # PASSED_FOR_FINAL_DECISION is absent from FinalDecisionOutcome.
    assert "PASSED_FOR_FINAL_DECISION" not in get_args(FinalDecisionOutcome)

    # ALLOW is present but grants no execution authority.
    assert "ALLOW" in get_args(FinalDecisionOutcome)
    # ALLOW is a policy outcome only: no execution-token or activation field exists.
    for forbidden in ("lease_id", "work_order_id", "executable_token", "activation"):
        assert forbidden not in PolicyDecisionV2.model_fields


def test_modules_import_without_side_effects() -> None:
    assert conductor_contracts.ACTION_PROPOSAL_SCHEMA == "conductor.action_proposal"
    assert callable(conductor_intake.evaluate_proposal)
    assert callable(policy_admission.evaluate_admission)
    assert callable(runtime_gate.evaluate_runtime_gates)
    assert policy_contracts.POLICY_DECISION_SCHEMA == "policy.decision"
    assert runtime_contracts.RUNTIME_GATE_SCHEMA == "policy.runtime.gate"
    assert runtime_result.RUNTIME_GATE_RESULT_SCHEMA == "policy.runtime.gate.result"
    assert callable(evaluate_policy)
    assert POLICY_DECISION_V2_SCHEMA == "policy.decision"
