"""M1.4c2b0 exact decision-event lineage: identity, derivation, and envelope invariants.

Every test starts from one coherent proposal + decision (the ``lineage_base`` fixture), mutates a
single envelope field or the recorder context, and asserts the exact PostgreSQL invariant that
rejects it. Inserts impersonate the inert ``blackbread_policy_recorder`` role on the superuser
admin engine. Run against real PostgreSQL 17.
"""

from __future__ import annotations

import copy
import uuid
from datetime import timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from blackbread.ledger.append import append_event
from blackbread.ledger.schema import EventEnvelope, to_draft
from blackbread.ledger.verify import verify_chain
from blackbread.policy.evaluation_facts import PolicyDecisionRecorded, policy_decision_registry
from blackbread.tenancy import TenantContext
from tests.policy.conftest import (
    LINEAGE_TENANT,
    assert_recorder_insert_rejected,
    insert_event_as_recorder,
    reset_policy_state,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
async def _clean_policy_state(policy_admin_engine):
    """Leave the policy tables empty after each test in this module."""
    yield
    await reset_policy_state(policy_admin_engine)


def _event(base: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    event = copy.deepcopy(base["event"])
    event.update(overrides)
    return event


# ── Valid linked event ───────────────────────────────────────────────────────


async def test_valid_policy_event_accepted(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    await insert_event_as_recorder(policy_admin_engine, lineage_base["event"])


async def test_trigger_derives_policy_decision_id_from_causation(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    """append_event() supplies no policy_decision_id; the trigger derives it from causation_id.

    The committed row must carry the exact stored decision_id, read back from the database rather
    than from the ORM object the BEFORE trigger never touched.
    """
    event = _event(lineage_base, policy_decision_id=None)
    await insert_event_as_recorder(policy_admin_engine, event)
    async with policy_admin_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": LINEAGE_TENANT}
        )
        row = (
            await conn.execute(
                text(
                    "SELECT policy_decision_id, causation_id FROM agent_events "
                    "WHERE schema_name = 'policy.decision.recorded' AND tenant_id = :t"
                ),
                {"t": LINEAGE_TENANT},
            )
        ).one()
    assert row[0] == row[1] == lineage_base["decision"]["decision_id"]


async def test_append_event_derived_lineage_verifies(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    """The real append_event path produces a chain-verifiable policy event.

    ``EventDraft`` (and therefore ``append_event``) has no ``policy_decision_id`` input. The draft
    is built exactly as the c2a producer builds it, appended as the recorder, and then:
      * the committed row carries the trigger-derived ``policy_decision_id`` equal to the stored
        ``decision_id`` (and to the hash-covered ``causation_id``);
      * ``verify_chain`` succeeds, proving ``policy_decision_id`` sits outside the sealed preimage
        while the fields that bind it (``causation_id``, ``payload_hash``) remain hash-covered.
    """
    proposal, decision = lineage_base["proposal"], lineage_base["decision"]
    engagement_id = lineage_base["engagement_id"]
    payload = policy_decision_registry().parse(
        PolicyDecisionRecorded.SCHEMA_NAME,
        PolicyDecisionRecorded.SCHEMA_VERSION,
        lineage_base["event"]["payload"],
    )
    envelope = EventEnvelope(
        tenant_id=LINEAGE_TENANT,
        engagement_id=engagement_id,
        producer="policy-record-transaction.v1",
        occurred_at=decision["decided_at"],
        sensitivity="internal",
        correlation_id=proposal["proposal_id"],
        causation_id=decision["decision_id"],
        redaction_refs=(),
    )
    draft = to_draft(payload, envelope, registry=policy_decision_registry())
    assert not hasattr(draft, "policy_decision_id")

    factory = async_sessionmaker(policy_admin_engine, expire_on_commit=False)
    async with factory() as recorder_session:
        await recorder_session.execute(text("SET ROLE blackbread_policy_recorder"))
        await append_event(recorder_session, draft, tenant_context=TenantContext(LINEAGE_TENANT))
        await recorder_session.commit()

    async with policy_admin_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": LINEAGE_TENANT}
        )
        stored = (
            await conn.execute(
                text(
                    "SELECT policy_decision_id, causation_id FROM agent_events "
                    "WHERE schema_name = 'policy.decision.recorded' AND tenant_id = :t"
                ),
                {"t": LINEAGE_TENANT},
            )
        ).one()
    assert stored[0] == stored[1] == decision["decision_id"]

    result = await verify_chain(
        policy_admin_engine, tenant_id=LINEAGE_TENANT, engagement_id=engagement_id
    )
    assert result.ok is True


# ── Recorder namespace restriction ───────────────────────────────────────────


async def test_recorder_rejects_non_policy_event(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    """The recorder may only write policy.decision.recorded."""
    event = _event(
        lineage_base,
        schema_name="engagement.attested",
        schema_version=1,
        policy_decision_id=None,
        correlation_id=None,
        causation_id=None,
        payload={},
    )
    await assert_recorder_insert_rejected(
        policy_admin_engine, event, match="may only insert policy.decision.recorded"
    )


async def test_policy_event_version_two_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    await assert_recorder_insert_rejected(
        policy_admin_engine, _event(lineage_base, schema_version=2), match="schema_version 1"
    )


# ── Lineage identity ─────────────────────────────────────────────────────────


async def test_null_causation_id_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    await assert_recorder_insert_rejected(
        policy_admin_engine,
        _event(lineage_base, causation_id=None, policy_decision_id=None),
        match="non-null causation_id",
    )


async def test_explicit_policy_decision_id_mismatch_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    await assert_recorder_insert_rejected(
        policy_admin_engine,
        _event(lineage_base, policy_decision_id=uuid.uuid4()),
        match="policy_decision_id must equal causation_id",
    )


async def test_causation_decision_a_payload_decision_b_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    """Causation names decision A while the payload names decision B."""
    event = copy.deepcopy(lineage_base["event"])
    event["payload"]["decision_id"] = str(uuid.uuid4())
    await assert_recorder_insert_rejected(
        policy_admin_engine, event, match="payload does not match the stored decision lineage"
    )


# ── Envelope mutations (one field at a time) ─────────────────────────────────


async def test_envelope_wrong_tenant(policy_admin_engine: AsyncEngine, lineage_base: dict) -> None:
    await assert_recorder_insert_rejected(
        policy_admin_engine,
        _event(lineage_base, tenant_id="other-tenant"),
        match="tenant_id does not match the session tenant",
    )


async def test_envelope_wrong_engagement(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    await assert_recorder_insert_rejected(
        policy_admin_engine,
        _event(lineage_base, engagement_id=uuid.uuid4()),
        match="referenced decision not found",
    )


async def test_envelope_wrong_producer(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    await assert_recorder_insert_rejected(
        policy_admin_engine,
        _event(lineage_base, producer="forged.v1"),
        match="producer must be policy-record-transaction.v1",
    )


async def test_envelope_wrong_correlation_id(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    await assert_recorder_insert_rejected(
        policy_admin_engine,
        _event(lineage_base, correlation_id=uuid.uuid4()),
        match="correlation_id must equal proposal_id",
    )


async def test_envelope_wrong_occurred_at(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    decided = lineage_base["decision"]["decided_at"]
    await assert_recorder_insert_rejected(
        policy_admin_engine,
        _event(lineage_base, occurred_at=decided + timedelta(hours=1)),
        match="occurred_at must equal decided_at",
    )


async def test_envelope_occurred_at_offset_same_instant_accepted(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    """occurred_at is timestamptz: the same instant in +01:00 normalizes and is accepted."""
    decided = lineage_base["decision"]["decided_at"]
    shifted = decided.astimezone(timezone(timedelta(hours=1)))
    await insert_event_as_recorder(policy_admin_engine, _event(lineage_base, occurred_at=shifted))


async def test_envelope_wrong_sensitivity(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    await assert_recorder_insert_rejected(
        policy_admin_engine,
        _event(lineage_base, sensitivity="restricted"),
        match="sensitivity must be internal",
    )


async def test_envelope_non_empty_redaction_refs(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    await assert_recorder_insert_rejected(
        policy_admin_engine,
        _event(lineage_base, redaction_refs=["ref"]),
        match="redaction_refs must be empty",
    )
