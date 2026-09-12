"""Dormant-substrate non-wiring proofs for M1.4c2b1a.

M1.4c2b1a adds the strict storage/routine-invocation module ``blackbread.policy.recording_store``
and migration 0010, but ships them *dormant*: no production entry point imports the store, the store
wires no evaluation, names no recorder identity, and exposes no execution authority. The composed
public boundary (``recording.py``) that would call ``evaluate_persistence_facts`` and reach the
recorder routine is exclusively M1.4c2b1b scope and does not exist in this slice. These source- and
behaviour-level proofs pin that dormancy; ``ALLOW`` remains only a Policy outcome, never execution.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

import blackbread.models as models_pkg
from blackbread.models.policy_records import ActionProposalRecord, DecisionRecord
from blackbread.policy import recording_store
from tests.policy._policy_record_builders import (
    decision_row,
    insert_decision,
    insert_proposal,
    proposal_row,
)
from tests.policy.conftest import seed_engagement

PROD_ROOT = Path(__file__).parents[2] / "src" / "blackbread"
MAPPING_FILE = PROD_ROOT / "models" / "policy_records.py"
STORE_FILE = PROD_ROOT / "policy" / "recording_store.py"
FACTS_FILE = PROD_ROOT / "policy" / "evaluation_facts.py"
RECORDER_ROLE = "blackbread_policy_recorder"
# The authorized readers of the durable record tables: the ORM mapping that defines them and the
# dormant store that projects rows for the recorder routine. Nothing else may name them.
AUTHORIZED_TABLE_READERS = {MAPPING_FILE, STORE_FILE}
FORBIDDEN_SURFACE = {
    "authorize",
    "execute",
    "activate",
    "issue_lease",
    "lease",
    "work_order",
    "grant_execution",
}


def _production_sources() -> list[Path]:
    return [p for p in PROD_ROOT.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_production_module_imports_the_mapping() -> None:
    offenders = [
        str(path.relative_to(PROD_ROOT))
        for path in _production_sources()
        if "models.policy_records" in path.read_text(encoding="utf-8")
        or "models import policy_records" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"production modules import the substrate: {offenders}"


def test_only_the_mapping_and_dormant_store_reference_the_tables() -> None:
    # The mapping defines the tables and the dormant store projects rows for them; every other
    # production module must still not name them. This is the b1a evolution of the b0 no-reader
    # proof: the store is an authorized reference, not a wired entry point (proven separately).
    offenders = [
        str(path.relative_to(PROD_ROOT))
        for path in _production_sources()
        if path not in AUTHORIZED_TABLE_READERS
        for table in ("action_proposals", "decision_records")
        if table in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"unexpected production modules reference the tables: {offenders}"


def test_recording_store_is_not_wired_into_any_entry_point() -> None:
    # Dormant: no production module imports the store, so no code path can reach the recorder
    # routine. The composed boundary that imports it is M1.4c2b1b.
    offenders = [
        str(path.relative_to(PROD_ROOT))
        for path in _production_sources()
        if path != STORE_FILE
        and (
            "policy.recording_store" in path.read_text(encoding="utf-8")
            or "import recording_store" in path.read_text(encoding="utf-8")
        )
    ]
    assert offenders == [], f"production modules wire the dormant store: {offenders}"


def test_no_composed_recording_boundary_exists_yet() -> None:
    # The evaluate-and-record boundary (recording.py) is M1.4c2b1b; it must be absent here.
    assert not (PROD_ROOT / "policy" / "recording.py").exists()


def test_store_wires_no_evaluation_and_names_no_recorder_identity() -> None:
    source = STORE_FILE.read_text(encoding="utf-8")
    assert "evaluation_facts" not in source, "the dormant store must not wire evaluation facts"
    assert "evaluate_policy(" not in source and "evaluate_persistence_facts(" not in source
    assert RECORDER_ROLE not in source, "the store must not embed the reserved recorder role"


def test_no_production_module_assumes_the_recorder_or_facts_writer() -> None:
    # No production entry point may name the reserved recorder identity or import the
    # evaluation-facts producer as a writer. Both remain islands until M1.4c2b1b composes them.
    offenders = []
    for path in _production_sources():
        source = path.read_text(encoding="utf-8")
        if RECORDER_ROLE in source:
            offenders.append(f"{path.relative_to(PROD_ROOT)}:recorder")
        if path != FACTS_FILE and (
            "policy.evaluation_facts" in source or "import evaluation_facts" in source
        ):
            offenders.append(f"{path.relative_to(PROD_ROOT)}:evaluation_facts")
    assert offenders == [], f"production assumes the recorder or facts writer: {offenders}"


def test_mapping_is_not_re_exported_from_models_package() -> None:
    assert not hasattr(models_pkg, "ActionProposalRecord")
    assert not hasattr(models_pkg, "DecisionRecord")
    assert "ActionProposalRecord" not in getattr(models_pkg, "__all__", [])
    assert "DecisionRecord" not in getattr(models_pkg, "__all__", [])


def test_mappings_expose_no_execution_surface() -> None:
    for mapped in (ActionProposalRecord, DecisionRecord):
        exposed = {name for name in dir(mapped) if not name.startswith("_")}
        assert exposed.isdisjoint(FORBIDDEN_SURFACE), f"{mapped.__name__} exposes {exposed}"


def test_store_exposes_no_execution_surface() -> None:
    exposed = {name for name in dir(recording_store) if not name.startswith("_")}
    assert exposed.isdisjoint(FORBIDDEN_SURFACE), f"recording_store exposes {exposed}"


def test_no_production_writer_accepts_policy_decision_v2() -> None:
    # The mapping holds no policy import and no evaluator call, so it cannot accept or persist a
    # decision; the dormant store projects raw rows and imports no PolicyDecisionV2 contract.
    mapping_source = MAPPING_FILE.read_text(encoding="utf-8")
    assert "from blackbread.policy" not in mapping_source
    assert "import decision_v2" not in mapping_source
    assert "evaluate_policy(" not in mapping_source
    # The dormant store keeps the policy domain out of persistence: it imports no PolicyDecisionV2
    # contract (a docstring may explain why; an import may not).
    assert "from blackbread.policy.decision_v2" not in STORE_FILE.read_text(encoding="utf-8")


async def test_runtime_role_cannot_write_either_table(
    policy_admin_engine: AsyncEngine, engine: AsyncEngine
) -> None:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    engagement_id = uuid.uuid4()
    await seed_engagement(policy_admin_engine, tenant, engagement_id)
    proposal = proposal_row(proposal_id=uuid.uuid4(), tenant_id=tenant, engagement_id=engagement_id)

    for insert, row in ((insert_proposal, proposal), (insert_decision, decision_row(proposal))):
        with pytest.raises(ProgrammingError) as excinfo:
            async with engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
                )
                await insert(conn, row)
        assert "permission denied" in str(excinfo.value.orig).lower()
