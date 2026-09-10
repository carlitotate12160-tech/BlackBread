"""Schema, closed-vocabulary, range, idempotency, and composite-lineage constraint proofs (M1.4c1).

Every insert uses the admin engine that bypasses RLS, so a malformed row is rejected by a PostgreSQL
constraint rather than hidden by row-level security or stopped by Pydantic. Each rejection asserts
the specific expected constraint and proves the row does not exist afterward.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from blackbread.policy.decision_v2 import FINAL_OUTCOME_BY_REASON
from tests.policy._policy_record_builders import (
    decision_row,
    insert_decision,
    insert_proposal,
    proposal_row,
)
from tests.policy.conftest import seed_engagement

FINAL_OUTCOMES = frozenset(FINAL_OUTCOME_BY_REASON.values()) | {"ALLOW"}
HEX_ALT = "e" * 64


async def _fresh(engine: AsyncEngine) -> tuple[str, uuid.UUID]:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    engagement_id = uuid.uuid4()
    await seed_engagement(engine, tenant, engagement_id)
    return tenant, engagement_id


async def _commit_proposal(engine: AsyncEngine, **overrides: Any) -> dict[str, Any]:
    overrides.setdefault("idempotency_key", f"idem-{uuid.uuid4().hex[:12]}")
    row = proposal_row(proposal_id=uuid.uuid4(), **overrides)
    async with engine.begin() as conn:
        await insert_proposal(conn, row)
    return row


async def _reject(
    engine: AsyncEngine,
    insert: Callable[..., Awaitable[None]],
    row: dict[str, Any],
    constraint: str,
) -> None:
    with pytest.raises(IntegrityError) as excinfo:
        async with engine.begin() as conn:
            await insert(conn, row)
    assert constraint in str(excinfo.value.orig), str(excinfo.value)


async def _count(engine: AsyncEngine, table: str, tenant: str) -> int:
    async with engine.begin() as conn:
        value = await conn.scalar(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),  # noqa: S608
            {"t": tenant},
        )
    return int(value or 0)


async def test_valid_proposal_and_decision_insert(policy_admin_engine: AsyncEngine) -> None:
    tenant, engagement_id = await _fresh(policy_admin_engine)
    proposal = await _commit_proposal(
        policy_admin_engine, tenant_id=tenant, engagement_id=engagement_id
    )
    async with policy_admin_engine.begin() as conn:
        await insert_decision(conn, decision_row(proposal))
    assert await _count(policy_admin_engine, "action_proposals", tenant) == 1
    assert await _count(policy_admin_engine, "decision_records", tenant) == 1


async def test_all_released_outcome_reason_pairs_are_accepted(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant, engagement_id = await _fresh(policy_admin_engine)
    pairs: list[tuple[str, str | None]] = [("ALLOW", None)]
    pairs += [(outcome, reason) for reason, outcome in FINAL_OUTCOME_BY_REASON.items()]
    for outcome, reason in pairs:
        p = await _commit_proposal(
            policy_admin_engine, tenant_id=tenant, engagement_id=engagement_id
        )
        async with policy_admin_engine.begin() as conn:
            await insert_decision(conn, decision_row(p, build_outcome=outcome, build_reason=reason))
    assert await _count(policy_admin_engine, "decision_records", tenant) == len(pairs)


async def test_all_cross_category_outcome_reason_pairs_are_rejected(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant, engagement_id = await _fresh(policy_admin_engine)
    for reason, correct in FINAL_OUTCOME_BY_REASON.items():
        for wrong in FINAL_OUTCOMES - {correct}:
            p = await _commit_proposal(
                policy_admin_engine, tenant_id=tenant, engagement_id=engagement_id
            )
            bad = decision_row(p, outcome=wrong, reason_code=reason)
            await _reject(
                policy_admin_engine, insert_decision, bad, "ck_decision_records_outcome_reason"
            )
    # ALLOW must carry no reason; a non-ALLOW outcome must carry one.
    p_allow = await _commit_proposal(
        policy_admin_engine, tenant_id=tenant, engagement_id=engagement_id
    )
    await _reject(
        policy_admin_engine,
        insert_decision,
        decision_row(p_allow, outcome="ALLOW", reason_code="ADMISSION_DENIED"),
        "ck_decision_records_outcome_reason",
    )
    p_deny = await _commit_proposal(
        policy_admin_engine, tenant_id=tenant, engagement_id=engagement_id
    )
    await _reject(
        policy_admin_engine,
        insert_decision,
        decision_row(p_deny, outcome="DENY", reason_code=None),
        "ck_decision_records_outcome_reason",
    )
    assert await _count(policy_admin_engine, "decision_records", tenant) == 0


async def test_malformed_proposal_rows_are_rejected(policy_admin_engine: AsyncEngine) -> None:
    tenant, engagement_id = await _fresh(policy_admin_engine)
    base: dict[str, Any] = {"tenant_id": tenant, "engagement_id": engagement_id}
    cases = [
        ({"schema_version": 2}, "ck_action_proposals_schema_version"),
        ({"proposal_digest": "not-hex"}, "ck_action_proposals_proposal_digest"),
        ({"agent_role": "Overlord"}, "ck_action_proposals_agent_role"),
        ({"target_kind": "wildcard"}, "ck_action_proposals_target_kind"),
        ({"capability_id": "Bad.Capability"}, "ck_action_proposals_capability_id"),
        ({"input_schema_ref": "no-version"}, "ck_action_proposals_input_schema"),
        ({"target_identity_tier": "T9"}, "ck_action_proposals_identity_tier"),
        ({"risk": 1.5}, "ck_action_proposals_risk"),
        ({"deadline_seconds": 0}, "ck_action_proposals_deadline"),
        ({"parameters": ["not", "an", "object"]}, "ck_action_proposals_params"),
        ({"precondition_refs": {"not": "array"}}, "ck_action_proposals_precond"),
    ]
    for override, constraint in cases:
        row = proposal_row(proposal_id=uuid.uuid4(), **base, **override)
        await _reject(policy_admin_engine, insert_proposal, row, constraint)
    assert await _count(policy_admin_engine, "action_proposals", tenant) == 0


async def test_validity_window_requires_expiry_after_creation(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant, engagement_id = await _fresh(policy_admin_engine)
    row = proposal_row(proposal_id=uuid.uuid4(), tenant_id=tenant, engagement_id=engagement_id)
    row["expires_at"] = row["created_at"]
    await _reject(policy_admin_engine, insert_proposal, row, "ck_action_proposals_validity_window")


async def test_decision_lineage_rejects_digest_substitution(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant, engagement_id = await _fresh(policy_admin_engine)
    proposal = await _commit_proposal(
        policy_admin_engine, tenant_id=tenant, engagement_id=engagement_id
    )
    bad = decision_row(proposal, proposal_digest=HEX_ALT)
    await _reject(policy_admin_engine, insert_decision, bad, "fk_decision_records_proposal_lineage")


async def test_decision_lineage_rejects_graph_anchor_substitution(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant, engagement_id = await _fresh(policy_admin_engine)
    proposal = await _commit_proposal(
        policy_admin_engine, tenant_id=tenant, engagement_id=engagement_id
    )
    for field in (
        "graph_state_root",
        "graph_ledger_head_hash",
        "graph_state_root_version",
        "graph_projector_version",
        "graph_ledger_event_count",
    ):
        value = HEX_ALT if field in {"graph_state_root", "graph_ledger_head_hash"} else 999
        bad = decision_row(proposal, **{field: value})
        await _reject(
            policy_admin_engine, insert_decision, bad, "fk_decision_records_proposal_lineage"
        )


async def test_decision_lineage_rejects_same_id_different_proposal(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant, engagement_id = await _fresh(policy_admin_engine)
    proposal = await _commit_proposal(
        policy_admin_engine, tenant_id=tenant, engagement_id=engagement_id
    )
    # Same proposal_id, but a graph anchor from a different proposal: no matching candidate key.
    bad = decision_row(proposal, graph_state_root=HEX_ALT)
    await _reject(policy_admin_engine, insert_decision, bad, "fk_decision_records_proposal_lineage")


async def test_decision_lineage_rejects_cross_tenant_substitution(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant_a, engagement_a = await _fresh(policy_admin_engine)
    tenant_b, engagement_b = await _fresh(policy_admin_engine)
    proposal = await _commit_proposal(
        policy_admin_engine, tenant_id=tenant_a, engagement_id=engagement_a
    )
    # Tenant B / engagement B exist, but proposal A's identity is not present under them.
    bad = decision_row(proposal, tenant_id=tenant_b, engagement_id=engagement_b)
    await _reject(policy_admin_engine, insert_decision, bad, "fk_decision_records_proposal_lineage")


async def test_duplicate_idempotency_key_is_serialized_by_database(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant, engagement_id = await _fresh(policy_admin_engine)
    await _commit_proposal(
        policy_admin_engine, tenant_id=tenant, engagement_id=engagement_id, idempotency_key="idem-x"
    )
    duplicate = proposal_row(
        proposal_id=uuid.uuid4(),
        tenant_id=tenant,
        engagement_id=engagement_id,
        idempotency_key="idem-x",
    )
    await _reject(
        policy_admin_engine, insert_proposal, duplicate, "uq_action_proposals_idempotency"
    )
    assert await _count(policy_admin_engine, "action_proposals", tenant) == 1


async def test_duplicate_proposal_digest_is_serialized_by_database(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant, engagement_id = await _fresh(policy_admin_engine)
    await _commit_proposal(
        policy_admin_engine, tenant_id=tenant, engagement_id=engagement_id, proposal_digest="d" * 64
    )
    duplicate = proposal_row(
        proposal_id=uuid.uuid4(),
        tenant_id=tenant,
        engagement_id=engagement_id,
        idempotency_key="idem-other",
        proposal_digest="d" * 64,
    )
    await _reject(policy_admin_engine, insert_proposal, duplicate, "uq_action_proposals_digest")


async def test_duplicate_decision_digest_is_serialized_by_database(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant, engagement_id = await _fresh(policy_admin_engine)
    proposal = await _commit_proposal(
        policy_admin_engine, tenant_id=tenant, engagement_id=engagement_id
    )
    async with policy_admin_engine.begin() as conn:
        await insert_decision(conn, decision_row(proposal, decision_digest="f" * 64))
    duplicate = decision_row(proposal, decision_digest="f" * 64)
    await _reject(policy_admin_engine, insert_decision, duplicate, "uq_decision_records_digest")
    assert await _count(policy_admin_engine, "decision_records", tenant) == 1
