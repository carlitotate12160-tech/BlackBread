"""Intentional non-wiring proofs for the M1.4c1 substrate and M1.4c2b0b recorder authority.

Combines source inspection (no production importer or reader, no exposed execution surface, no
public PolicyDecisionV2 writer, and no production assumption of the reserved recorder identity or
the evaluation-facts producer) with a behavioral runtime write-denial test. M1.4c2b1 owns the first
production writer that composes evaluate_policy() with persistence and ledger publication in one
authenticated transaction; nothing in this slice reaches the recorder authority from production.
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
from tests.policy._policy_record_builders import (
    decision_row,
    insert_decision,
    insert_proposal,
    proposal_row,
)
from tests.policy.conftest import seed_engagement

PROD_ROOT = Path(__file__).parents[2] / "src" / "blackbread"
MAPPING_FILE = PROD_ROOT / "models" / "policy_records.py"
FACTS_FILE = PROD_ROOT / "policy" / "evaluation_facts.py"
RECORDER_ROLE = "blackbread_policy_recorder"
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


def test_no_production_module_reads_the_tables() -> None:
    # The mapping module defines the tables; every other production module must not name them.
    offenders = [
        str(path.relative_to(PROD_ROOT))
        for path in _production_sources()
        if path != MAPPING_FILE
        for table in ("action_proposals", "decision_records")
        if table in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"production modules reference the tables: {offenders}"


def test_no_production_module_assumes_the_recorder_or_facts_writer() -> None:
    # M1.4c2b0b non-wiring: no production entry point may name the reserved recorder identity or
    # import the evaluation-facts producer as a writer. The recorder is exercised only by tests and
    # the future b1 transaction; evaluation_facts remains an island until M1.4c2b1 consumes it.
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


def test_no_production_writer_accepts_policy_decision_v2() -> None:
    # The only production module importing PolicyDecisionV2 for persistence would also import the
    # mapping; the import proof above shows none does. Belt-and-suspenders: the mapping module holds
    # no policy import and no evaluator call, so it cannot accept or persist a decision.
    source = MAPPING_FILE.read_text(encoding="utf-8")
    assert "from blackbread.policy" not in source
    assert "import decision_v2" not in source
    assert "evaluate_policy(" not in source


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
