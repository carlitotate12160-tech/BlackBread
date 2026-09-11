"""M1.4c2b0b real-PostgreSQL proof that policy-decision event lineage is database-enforced.

A ``policy.decision.recorded`` event is accepted only when the reserved recorder identity writes it,
the transaction-local tenant matches, and its envelope and payload agree exactly with the durable
``DecisionRecord`` and its ``ActionProposal``. The database derives ``policy_decision_id`` from the
event's ``causation_id``; a caller may not supply it. The mutation matrix drives every field the
trigger owns, plus cross-tenant substitution, duplicate publication, the reserved-writer boundary,
and a temporary-trigger-disable sensitivity proof, through the real ``bb-test-db`` PostgreSQL.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.policy._policy_record_authority_support import (
    LINEAGE_TRIGGER,
    RECORDER_ROLE,
    RUNTIME_ROLE,
    clear_policy_rows_before_base_downgrade,  # noqa: F401 -- session cleanup autouse fixture
    open_recorder_txn,
)
from tests.policy._policy_record_builders import (
    decision_event_payload,
    decision_event_row,
    decision_row,
    insert_agent_event,
    insert_decision,
    insert_proposal,
    proposal_row,
)
from tests.policy.conftest import seed_engagement

MutationBuilder = Callable[[dict[str, Any], dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]]


async def _seed(admin: AsyncEngine) -> tuple[str, uuid.UUID, dict[str, Any], dict[str, Any]]:
    """Seed one engagement, proposal, and coherent ALLOW decision; return the row pair."""
    tenant_id = f"tenant-{uuid.uuid4().hex[:12]}"
    engagement_id = uuid.uuid4()
    await seed_engagement(admin, tenant_id, engagement_id)
    proposal = proposal_row(
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        proposal_id=uuid.uuid4(),
        idempotency_key=f"idem-{uuid.uuid4().hex[:10]}",
    )
    decision = decision_row(proposal)
    async with admin.begin() as conn:
        await insert_proposal(conn, proposal)
        await insert_decision(conn, decision)
    return tenant_id, engagement_id, proposal, decision


async def _record(
    admin: AsyncEngine,
    tenant_id: str,
    row: dict[str, Any],
    *,
    role: str | None = RECORDER_ROLE,
    guc: str | None = None,
) -> None:
    """Insert an event row inside one transaction under the given writer identity and tenant GUC."""
    async with admin.connect() as conn:
        transaction = await conn.begin()
        try:
            await open_recorder_txn(conn, tenant_id if guc is None else guc, role=role or "")
            await insert_agent_event(conn, row)
            await transaction.commit()
        finally:
            if transaction.is_active:
                await transaction.rollback()


async def test_valid_policy_event_is_accepted_and_lineage_is_derived(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant_id, _engagement_id, proposal, decision = await _seed(policy_admin_engine)
    row = decision_event_row(proposal, decision)
    await _record(policy_admin_engine, tenant_id, row)

    async with policy_admin_engine.connect() as conn:
        derived = await conn.scalar(
            text("SELECT policy_decision_id FROM agent_events WHERE id = :id"), {"id": row["id"]}
        )
    assert derived == decision["decision_id"], "lineage must be derived from causation_id"


async def test_caller_supplied_lineage_is_rejected(policy_admin_engine: AsyncEngine) -> None:
    tenant_id, _engagement_id, proposal, decision = await _seed(policy_admin_engine)
    row = decision_event_row(proposal, decision, policy_decision_id=decision["decision_id"])
    with pytest.raises(DBAPIError):
        await _record(policy_admin_engine, tenant_id, row)


async def test_duplicate_event_for_one_decision_is_rejected(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant_id, _engagement_id, proposal, decision = await _seed(policy_admin_engine)
    first = decision_event_row(proposal, decision, sequence=1)
    await _record(policy_admin_engine, tenant_id, first)
    # A second reserved event for the same decision, correctly chained, still violates the partial
    # unique index that allows at most one policy event per decision.
    second = decision_event_row(proposal, decision, sequence=2, prev_event_hash=first["event_hash"])
    with pytest.raises(DBAPIError):
        await _record(policy_admin_engine, tenant_id, second)


async def test_cross_tenant_decision_reference_is_rejected(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant_a, _eng_a, proposal_a, decision_a = await _seed(policy_admin_engine)
    _tenant_b, _eng_b, _proposal_b, decision_b = await _seed(policy_admin_engine)
    # Tenant A's writer references tenant B's decision; RLS hides it from the recorder's SELECT.
    row = decision_event_row(proposal_a, decision_a, causation_id=decision_b["decision_id"])
    with pytest.raises(DBAPIError):
        await _record(policy_admin_engine, tenant_a, row)


async def test_tenant_guc_mismatch_is_rejected(policy_admin_engine: AsyncEngine) -> None:
    tenant_id, _engagement_id, proposal, decision = await _seed(policy_admin_engine)
    row = decision_event_row(proposal, decision)
    with pytest.raises(DBAPIError):
        await _record(policy_admin_engine, tenant_id, row, guc="tenant-someone-else")


async def test_ordinary_runtime_cannot_write_policy_event(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant_id, _engagement_id, proposal, decision = await _seed(policy_admin_engine)
    row = decision_event_row(proposal, decision)
    with pytest.raises(DBAPIError):
        await _record(policy_admin_engine, tenant_id, row, role=RUNTIME_ROLE)


async def test_superuser_is_not_the_reserved_writer(policy_admin_engine: AsyncEngine) -> None:
    tenant_id, _engagement_id, proposal, decision = await _seed(policy_admin_engine)
    row = decision_event_row(proposal, decision)
    with pytest.raises(DBAPIError):
        await _record(policy_admin_engine, tenant_id, row, role=None)


async def test_missing_decision_reference_is_rejected(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant_id, _engagement_id, proposal, decision = await _seed(policy_admin_engine)
    row = decision_event_row(proposal, decision, causation_id=uuid.uuid4())
    with pytest.raises(DBAPIError):
        await _record(policy_admin_engine, tenant_id, row)


async def test_non_policy_event_may_not_carry_lineage(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant_id, engagement_id, _proposal, decision = await _seed(policy_admin_engine)
    row = {
        "id": uuid.uuid4(),
        "engagement_id": engagement_id,
        "tenant_id": tenant_id,
        "sequence": 1,
        "schema_name": "engagement.attested",
        "schema_version": 1,
        "producer": "conductor",
        "occurred_at": decision["decided_at"],
        "recorded_at": decision["decided_at"],
        "payload": {},
        "payload_hash": "a" * 64,
        "prev_event_hash": "0" * 64,
        "event_hash": uuid.uuid4().hex + uuid.uuid4().hex,
        "policy_decision_id": decision["decision_id"],
    }
    with pytest.raises(DBAPIError):
        await _record(policy_admin_engine, tenant_id, row, role=None)


def _payload_mutation(**changes: Any) -> MutationBuilder:
    def build(proposal: dict[str, Any], decision: dict[str, Any]) -> tuple[dict[str, Any], dict]:
        payload = decision_event_payload(proposal, decision)
        payload.update(changes)
        return decision_event_row(proposal, decision, payload=payload), {}

    return build


def _graph_mutation(**changes: Any) -> MutationBuilder:
    def build(proposal: dict[str, Any], decision: dict[str, Any]) -> tuple[dict[str, Any], dict]:
        payload = decision_event_payload(proposal, decision)
        payload["graph_version"] = {**payload["graph_version"], **changes}
        return decision_event_row(proposal, decision, payload=payload), {}

    return build


def _drop_key(key: str) -> MutationBuilder:
    def build(proposal: dict[str, Any], decision: dict[str, Any]) -> tuple[dict[str, Any], dict]:
        payload = decision_event_payload(proposal, decision)
        payload.pop(key)
        return decision_event_row(proposal, decision, payload=payload), {}

    return build


def _envelope_mutation(**overrides: Any) -> MutationBuilder:
    def build(proposal: dict[str, Any], decision: dict[str, Any]) -> tuple[dict[str, Any], dict]:
        return decision_event_row(proposal, decision, **overrides), {}

    return build


_OTHER_TIME = datetime(2027, 1, 1, 0, 0, tzinfo=UTC)

_MUTATIONS: tuple[tuple[str, MutationBuilder], ...] = (
    ("outcome", _payload_mutation(outcome="DENY")),
    ("reason_code", _payload_mutation(reason_code="ADMISSION_DENIED")),
    ("decision_authority", _payload_mutation(decision_authority="policy.kernel.v1")),
    ("decision_schema_name", _payload_mutation(decision_schema_name="policy.other")),
    ("proposal_digest", _payload_mutation(proposal_digest="f" * 64)),
    ("decision_digest", _payload_mutation(decision_digest="f" * 64)),
    ("runtime_digest", _payload_mutation(runtime_gate_result_digest="f" * 64)),
    ("idempotency_key", _payload_mutation(idempotency_key="tampered-key")),
    ("proposal_id", _payload_mutation(proposal_id=str(uuid.uuid4()))),
    ("decision_id", _payload_mutation(decision_id=str(uuid.uuid4()))),
    ("decided_at", _payload_mutation(decided_at="2027-01-01T00:00:00Z")),
    ("float_schema_version", _payload_mutation(decision_schema_version=2.0)),
    # JSON null reaches the trigger as SQL NULL via ->>; every canonical-integer field must reject
    # it rather than evaluate the check to NULL and skip the rejection branch.
    ("null_schema_version", _payload_mutation(decision_schema_version=None)),
    ("graph_state_root", _graph_mutation(state_root="f" * 64)),
    ("graph_head_hash", _graph_mutation(ledger_head_hash="f" * 64)),
    ("float_ledger_count", _graph_mutation(ledger_event_count=7.0)),
    ("null_state_root_version", _graph_mutation(state_root_version=None)),
    ("null_projector_version", _graph_mutation(projector_version=None)),
    ("null_ledger_event_count", _graph_mutation(ledger_event_count=None)),
    ("nested_scalar", _payload_mutation(outcome={"nested": "object"})),
    ("nested_graph_extra", _graph_mutation(unexpected="x")),
    ("extra_key", _payload_mutation(unexpected_field="x")),
    ("missing_decided_at", _drop_key("decided_at")),
    ("missing_graph_version", _drop_key("graph_version")),
    ("wrong_producer", _envelope_mutation(producer="evil-writer.v1")),
    ("wrong_sensitivity", _envelope_mutation(sensitivity="public")),
    ("wrong_redaction_refs", _envelope_mutation(redaction_refs=["leak"])),
    ("occurred_at_mismatch", _envelope_mutation(occurred_at=_OTHER_TIME)),
    ("unsupported_version", _envelope_mutation(schema_version=2)),
)


@pytest.mark.parametrize(("label", "builder"), _MUTATIONS, ids=[m[0] for m in _MUTATIONS])
async def test_payload_and_envelope_mutations_are_rejected(
    policy_admin_engine: AsyncEngine, label: str, builder: MutationBuilder
) -> None:
    tenant_id, _engagement_id, proposal, decision = await _seed(policy_admin_engine)
    row, record_kwargs = builder(proposal, decision)
    with pytest.raises(DBAPIError):
        await _record(policy_admin_engine, tenant_id, row, **record_kwargs)


async def test_empty_payload_is_rejected(policy_admin_engine: AsyncEngine) -> None:
    tenant_id, _engagement_id, proposal, decision = await _seed(policy_admin_engine)
    row = decision_event_row(proposal, decision, payload={})
    with pytest.raises(DBAPIError):
        await _record(policy_admin_engine, tenant_id, row)


async def test_trigger_is_the_load_bearing_oracle(policy_admin_engine: AsyncEngine) -> None:
    """Temporary-mutation sensitivity: with the validation trigger disabled a forged payload is
    accepted (proving the trigger, not another constraint, owns payload integrity); the DDL and the
    forged row are rolled back and the real trigger then rejects the same mutation."""
    tenant_id, _engagement_id, proposal, decision = await _seed(policy_admin_engine)
    forged = decision_event_payload(proposal, decision)
    forged["decision_digest"] = "f" * 64
    async with policy_admin_engine.connect() as conn:
        transaction = await conn.begin()
        # Disable only the new trigger; supply the lineage the trigger would otherwise derive so the
        # CHECK and FK still pass, isolating the trigger as the payload-integrity oracle.
        await conn.execute(text(f"ALTER TABLE agent_events DISABLE TRIGGER {LINEAGE_TRIGGER}"))
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant_id}
        )
        forged_row = decision_event_row(
            proposal, decision, payload=forged, policy_decision_id=decision["decision_id"]
        )
        await insert_agent_event(conn, forged_row)
        accepted = await conn.scalar(
            text("SELECT count(*) FROM agent_events WHERE id = :id"), {"id": forged_row["id"]}
        )
        assert accepted == 1, "with the trigger disabled the forged payload must be accepted"
        await transaction.rollback()

    with pytest.raises(DBAPIError):
        await _record(
            policy_admin_engine,
            tenant_id,
            decision_event_row(proposal, decision, payload=forged),
        )
