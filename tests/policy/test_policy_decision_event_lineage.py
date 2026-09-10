"""M1.4c2b0 exact decision-event lineage proofs.

Each test mutates ONE field at a time from a valid baseline and asserts the specific
PostgreSQL invariant rejects it. Run against real PostgreSQL 17.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime, timedelta, timezone
from tests.policy._lineage_fixtures import lineage_base, _assert_event_rejected, _mutate_payload
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from blackbread.ledger.hashing import (
    GENESIS_PREV_HASH,
    HASH_ALGORITHM,
    HASH_VERSION,
    canonical_timestamp,
    compute_event_hash,
    compute_payload_hash,
)
from tests.policy._policy_record_builders import (
    decision_row,
    insert_decision,
    insert_proposal,
    policy_event_row,
    proposal_row,
)

pytestmark = pytest.mark.anyio

TENANT = "lineage-test-tenant"


def _make_event_sql_params(
    event: dict[str, Any],
    engagement_id: uuid.UUID,
    *,
    sequence: int = 1,
    prev_hash: str = GENESIS_PREV_HASH,
) -> dict[str, Any]:
    """Build full agent_events SQL parameters from the builder event dict.

    Computes payload_hash, event_hash via the real hashing pipeline,
    then returns a dict suitable for parameterized INSERT.
    The trigger derives policy_decision_id from causation_id for policy events.
    """
    event_id = uuid.uuid4()
    now = datetime.now(UTC)
    payload = event["payload"]
    payload_hash = compute_payload_hash(payload)

    # Build a SealedEvent-compatible object for hash computation
    class _Hashable:
        pass

    h = _Hashable()
    h.id = event_id
    h.engagement_id = engagement_id
    h.tenant_id = event["tenant_id"]
    h.sequence = sequence
    h.schema_name = event["schema_name"]
    h.schema_version = event["schema_version"]
    h.producer = event["producer"]
    h.correlation_id = event.get("correlation_id")
    h.causation_id = event.get("causation_id")
    h.occurred_at = event["occurred_at"]
    h.recorded_at = now
    h.payload = payload
    h.payload_hash = payload_hash
    h.prev_event_hash = prev_hash
    h.event_hash = ""
    h.hash_algorithm = HASH_ALGORITHM
    h.hash_version = HASH_VERSION
    h.sensitivity = event.get("sensitivity", "internal")
    h.redaction_refs = event.get("redaction_refs", [])

    event_hash = compute_event_hash(h)

    return {
        "id": event_id,
        "engagement_id": engagement_id,
        "tenant_id": event["tenant_id"],
        "sequence": sequence,
        "schema_name": event["schema_name"],
        "schema_version": event["schema_version"],
        "producer": event["producer"],
        "correlation_id": event.get("correlation_id"),
        "causation_id": event.get("causation_id"),
        "occurred_at": event["occurred_at"],
        "recorded_at": now,
        "payload": json.dumps(payload),
        "payload_hash": payload_hash,
        "prev_event_hash": prev_hash,
        "event_hash": event_hash,
        "hash_algorithm": HASH_ALGORITHM,
        "hash_version": HASH_VERSION,
        "sensitivity": event.get("sensitivity", "internal"),
        "redaction_refs": json.dumps(event.get("redaction_refs", [])),
    }


_EVENT_INSERT = """
INSERT INTO agent_events (
    id, engagement_id, tenant_id, sequence,
    schema_name, schema_version, producer,
    correlation_id, causation_id,
    occurred_at, recorded_at,
    payload, payload_hash, prev_event_hash, event_hash,
    hash_algorithm, hash_version, sensitivity, redaction_refs
) VALUES (
    :id, :engagement_id, :tenant_id, :sequence,
    :schema_name, :schema_version, :producer,
    :correlation_id, :causation_id,
    :occurred_at, :recorded_at,
    :payload::jsonb, :payload_hash, :prev_event_hash, :event_hash,
    :hash_algorithm, :hash_version, :sensitivity, :redaction_refs::jsonb
)
"""


@pytest.fixture
async def _insert_event_as_recorder(
    session: AsyncSession,
    event: dict[str, Any],
    engagement_id: uuid.UUID,
    *,
    sequence: int = 1,
) -> None:
    """Insert an event via raw SQL as the recorder role."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from tests.conftest import TEST_MIGRATION_DATABASE_URL
    admin_url = TEST_MIGRATION_DATABASE_URL
    admin = create_async_engine(admin_url)
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f"SET LOCAL blackbread.tenant_id = '{TENANT}'"))
            await conn.execute(text("SET LOCAL ROLE blackbread_policy_recorder"))
            params = _make_event_sql_params(event, engagement_id, sequence=sequence)
            await conn.execute(text(_EVENT_INSERT), params)
    finally:
        await admin.dispose()


) -> None:
    """Assert that inserting the event as recorder fails."""
    with pytest.raises((IntegrityError, ProgrammingError)):
        await _insert_event_as_recorder(session, event, engagement_id)


# ────────────────────────────────────────────────────────────────────
# §C — Valid linked event accepted
# ────────────────────────────────────────────────────────────────────


async def test_valid_policy_event_accepted(session: AsyncSession, lineage_base: dict) -> None:
    """A coherent policy event inserted by the recorder succeeds."""
    await _insert_event_as_recorder(
        session, lineage_base["event"], lineage_base["engagement_id"]
    )


# ────────────────────────────────────────────────────────────────────
# §C — Recorder namespace restriction
# ────────────────────────────────────────────────────────────────────


async def test_recorder_cannot_insert_non_policy_event(
    session: AsyncSession, lineage_base: dict
) -> None:
    """Recorder inserting engagement.attested v1 is rejected by the trigger."""
    event = {**lineage_base["event"], "schema_name": "engagement.attested", "schema_version": 1}
    event["payload"] = {}
    # Remove policy-specific fields
    event.pop("correlation_id", None)
    event.pop("causation_id", None)
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


async def test_policy_event_v2_rejected(session: AsyncSession, lineage_base: dict) -> None:
    """policy.decision.recorded version 2 is rejected."""
    event = {**lineage_base["event"], "schema_version": 2}
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


# ────────────────────────────────────────────────────────────────────
# §1 — Trigger derives policy_decision_id from causation_id
# ────────────────────────────────────────────────────────────────────


async def test_trigger_derives_policy_decision_id(
    session: AsyncSession, lineage_base: dict
) -> None:
    """EventDraft has no policy_decision_id. Trigger derives it from causation_id."""
    await _insert_event_as_recorder(
        session, lineage_base["event"], lineage_base["engagement_id"]
    )
    # Verify the committed row has policy_decision_id = decision_id
    from sqlalchemy.ext.asyncio import create_async_engine
    from tests.conftest import TEST_MIGRATION_DATABASE_URL
    admin_url = TEST_MIGRATION_DATABASE_URL
    admin = create_async_engine(admin_url)
    try:
        async with admin.begin() as conn:
            row = (await conn.execute(
                text(
                    "SELECT policy_decision_id, causation_id "
                    "FROM agent_events "
                    "WHERE schema_name = 'policy.decision.recorded' "
                    "AND tenant_id = :tid"
                ),
                {"tid": TENANT},
            )).one()
            assert row[0] == row[1]
            assert row[0] == lineage_base["decision"]["decision_id"]
    finally:
        await admin.dispose()


async def test_null_causation_id_rejected(session: AsyncSession, lineage_base: dict) -> None:
    """Null causation_id with policy event is rejected."""
    event = {**lineage_base["event"], "causation_id": None}
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


async def test_explicit_policy_decision_id_mismatch_rejected(
    session: AsyncSession, lineage_base: dict
) -> None:
    """Explicit policy_decision_id different from causation_id is rejected."""
    # This test requires inserting with an explicit policy_decision_id via SQL
    from sqlalchemy.ext.asyncio import create_async_engine
    from tests.conftest import TEST_MIGRATION_DATABASE_URL
    admin_url = TEST_MIGRATION_DATABASE_URL
    admin = create_async_engine(admin_url)
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f"SET LOCAL blackbread.tenant_id = '{TENANT}'"))
            await conn.execute(text("SET LOCAL ROLE blackbread_policy_recorder"))
            params = _make_event_sql_params(
                lineage_base["event"], lineage_base["engagement_id"]
            )
            # Add explicit wrong policy_decision_id
            wrong_insert = _EVENT_INSERT.replace(
                "redaction_refs\n)",
                "redaction_refs, policy_decision_id\n)",
            ).replace(
                ":redaction_refs::jsonb\n)",
                ":redaction_refs::jsonb, :policy_decision_id\n)",
            )
            params["policy_decision_id"] = uuid.uuid4()
            with pytest.raises((IntegrityError, ProgrammingError)):
                await conn.execute(text(wrong_insert), params)
    finally:
        await admin.dispose()


# ────────────────────────────────────────────────────────────────────
# §D — Envelope mutation (one field at a time)
# ────────────────────────────────────────────────────────────────────


async def test_envelope_wrong_tenant(session: AsyncSession, lineage_base: dict) -> None:
    event = {**lineage_base["event"], "tenant_id": "wrong-tenant"}
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


async def test_envelope_wrong_engagement(session: AsyncSession, lineage_base: dict) -> None:
    event = {**lineage_base["event"], "engagement_id": uuid.uuid4()}
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


async def test_envelope_wrong_producer(session: AsyncSession, lineage_base: dict) -> None:
    event = {**lineage_base["event"], "producer": "wrong-producer.v1"}
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


async def test_envelope_wrong_correlation_id(session: AsyncSession, lineage_base: dict) -> None:
    event = {**lineage_base["event"], "correlation_id": uuid.uuid4()}
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


async def test_envelope_wrong_causation_id(session: AsyncSession, lineage_base: dict) -> None:
    event = {**lineage_base["event"], "causation_id": uuid.uuid4()}
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


async def test_envelope_wrong_occurred_at(session: AsyncSession, lineage_base: dict) -> None:
    event = {**lineage_base["event"], "occurred_at": datetime.now(UTC) + timedelta(hours=1)}
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


async def test_envelope_wrong_sensitivity(session: AsyncSession, lineage_base: dict) -> None:
    event = {**lineage_base["event"], "sensitivity": "public"}
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


async def test_envelope_non_empty_redaction_refs(session: AsyncSession, lineage_base: dict) -> None:
    event = {**lineage_base["event"], "redaction_refs": ["some-ref"]}
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


# ────────────────────────────────────────────────────────────────────
# §D — Payload value mutations (all 13 top-level keys)
# ────────────────────────────────────────────────────────────────────


