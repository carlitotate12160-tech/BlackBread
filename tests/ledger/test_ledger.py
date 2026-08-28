import asyncio
import uuid
from datetime import UTC, datetime
from types import MappingProxyType

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from blackbread.ledger import EventDraft, LedgerAccessError, append_event, verify_chain
from blackbread.ledger.event import GENESIS_PREV_HASH, AgentEvent
from blackbread.models.core import Client, Engagement

DISABLE_MUTATION_TRIGGER = text(
    "ALTER TABLE agent_events DISABLE TRIGGER agent_events_reject_mutation"
)
ENABLE_MUTATION_TRIGGER = text(
    "ALTER TABLE agent_events ENABLE TRIGGER agent_events_reject_mutation"
)


def _draft(engagement: Engagement, marker: str) -> EventDraft:
    return EventDraft(
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        schema_name="test.event",
        schema_version=1,
        producer="test-producer",
        payload={
            "marker": marker,
            "count": 3,
            "nested": {"a": [1, 2, 3], "ok": True, "missing": None},
            "note": "unicodé",
        },
        occurred_at=datetime.now(UTC),
        redaction_refs=["artifact://redacted/1"],
    )


async def _append(session: AsyncSession, engagement: Engagement, marker: str) -> AgentEvent:
    return await append_event(session, _draft(engagement, marker))


async def _corrupt(session: AsyncSession, statement: object) -> None:
    await session.execute(DISABLE_MUTATION_TRIGGER)
    await session.execute(statement)
    await session.execute(ENABLE_MUTATION_TRIGGER)
    await session.commit()


async def test_append_builds_genesis_linked_chain(
    session: AsyncSession,
    engagement: Engagement,
) -> None:
    first = await _append(session, engagement, "a")
    second = await _append(session, engagement, "b")
    third = await _append(session, engagement, "c")
    await session.commit()

    assert [first.sequence, second.sequence, third.sequence] == [1, 2, 3]
    assert first.prev_event_hash == GENESIS_PREV_HASH
    assert second.prev_event_hash == first.event_hash
    assert third.prev_event_hash == second.event_hash
    assert first.tenant_id == engagement.tenant_id
    assert len({first.event_hash, second.event_hash, third.event_hash}) == 3


async def test_mapping_and_stable_float_round_trip_through_jsonb(
    session: AsyncSession,
    engagement: Engagement,
) -> None:
    draft = EventDraft(
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        schema_name="test.numeric",
        schema_version=1,
        producer="test-producer",
        payload=MappingProxyType({"score": 1.5, "nested": MappingProxyType({"marker": "x"})}),
        occurred_at=datetime.now(UTC),
    )
    event = await append_event(session, draft)
    event_id = event.id
    await session.commit()
    session.expunge_all()

    reloaded = (
        await session.execute(select(AgentEvent).where(AgentEvent.id == event_id))
    ).scalar_one()
    result = await verify_chain(
        session,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )

    assert reloaded.payload == {"score": 1.5, "nested": {"marker": "x"}}
    assert result.ok is True
    assert result.event_count == 1


async def test_verify_passes_for_untampered_chain(
    session: AsyncSession,
    engagement: Engagement,
) -> None:
    for marker in ("a", "b", "c", "d"):
        await _append(session, engagement, marker)
    await session.commit()

    result = await verify_chain(
        session,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )

    assert result.ok is True
    assert result.event_count == 4
    assert result.broken_at_sequence is None


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        ("payload", {"marker": "TAMPERED"}, "payload hash mismatch"),
        ("prev_event_hash", "f" * 64, "broken prev-hash link"),
        ("event_hash", "a" * 64, "event hash mismatch"),
        ("sensitivity", "restricted", "event hash mismatch"),
        ("redaction_refs", ["artifact://redacted/2"], "event hash mismatch"),
    ],
)
async def test_verify_detects_tamper(
    session: AsyncSession,
    engagement: Engagement,
    column: str,
    value: object,
    reason: str,
) -> None:
    await _append(session, engagement, "a")
    target = await _append(session, engagement, "b")
    await _append(session, engagement, "c")
    await session.commit()

    await _corrupt(
        session,
        AgentEvent.__table__.update().where(AgentEvent.id == target.id).values({column: value}),
    )
    result = await verify_chain(
        session,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )

    assert result.ok is False
    assert result.broken_at_sequence == 2
    assert result.reason == reason


async def test_append_and_verify_fail_closed_for_wrong_tenant(
    session: AsyncSession,
    engagement: Engagement,
) -> None:
    draft = _draft(engagement, "a")
    wrong = EventDraft(
        tenant_id="tenant-other",
        engagement_id=draft.engagement_id,
        schema_name=draft.schema_name,
        schema_version=draft.schema_version,
        producer=draft.producer,
        payload=draft.payload,
        occurred_at=draft.occurred_at,
    )

    with pytest.raises(LedgerAccessError):
        await append_event(session, wrong)
    with pytest.raises(LedgerAccessError):
        await verify_chain(
            session,
            tenant_id="tenant-other",
            engagement_id=engagement.id,
        )


async def test_missing_engagement_fails_closed(session: AsyncSession) -> None:
    engagement_id = uuid.uuid4()
    with pytest.raises(LedgerAccessError):
        await append_event(
            session,
            EventDraft(
                tenant_id="tenant-a",
                engagement_id=engagement_id,
                schema_name="test.event",
                schema_version=1,
                producer="test-producer",
                payload={"marker": "x"},
                occurred_at=datetime.now(UTC),
            ),
        )
    with pytest.raises(LedgerAccessError):
        await verify_chain(
            session,
            tenant_id="tenant-a",
            engagement_id=engagement_id,
        )


async def test_two_engagements_have_independent_chains(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as setup:
        client = Client(name="acme")
        setup.add(client)
        await setup.flush()
        eng_a = Engagement(client_id=client.id, tenant_id="tenant-a")
        eng_b = Engagement(client_id=client.id, tenant_id="tenant-b")
        setup.add_all([eng_a, eng_b])
        await setup.commit()

    async with session_factory() as active:
        for marker in ("a1", "a2"):
            await append_event(active, _draft(eng_a, marker))
        await active.commit()

    async with session_factory() as active:
        first_b = await append_event(active, _draft(eng_b, "b1"))
        await active.commit()
        assert first_b.sequence == 1
        assert first_b.prev_event_hash == GENESIS_PREV_HASH

    async with session_factory() as active:
        result_a = await verify_chain(
            active,
            tenant_id=eng_a.tenant_id,
            engagement_id=eng_a.id,
        )
        result_b = await verify_chain(
            active,
            tenant_id=eng_b.tenant_id,
            engagement_id=eng_b.id,
        )
        assert result_a.event_count == 2
        assert result_b.event_count == 1


async def test_concurrent_appends_serialize_without_gaps(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as setup:
        client = Client(name="acme")
        setup.add(client)
        await setup.flush()
        engagement = Engagement(client_id=client.id, tenant_id="tenant-c")
        setup.add(engagement)
        await setup.commit()

    async def append_one(marker: str) -> None:
        async with session_factory() as active:
            await append_event(active, _draft(engagement, marker))
            await active.commit()

    await asyncio.gather(*(append_one(f"m{index}") for index in range(10)))

    async with session_factory() as active:
        rows = (
            (
                await active.execute(
                    select(AgentEvent)
                    .where(
                        AgentEvent.engagement_id == engagement.id,
                        AgentEvent.tenant_id == engagement.tenant_id,
                    )
                    .order_by(AgentEvent.sequence)
                )
            )
            .scalars()
            .all()
        )
        assert [row.sequence for row in rows] == list(range(1, 11))
        result = await verify_chain(
            active,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )
        assert result.ok is True


async def test_verify_detects_deleted_middle_event(
    session: AsyncSession,
    engagement: Engagement,
) -> None:
    await _append(session, engagement, "a")
    middle = await _append(session, engagement, "b")
    await _append(session, engagement, "c")
    await session.commit()

    await session.execute(DISABLE_MUTATION_TRIGGER)
    await session.execute(AgentEvent.__table__.delete().where(AgentEvent.id == middle.id))
    await session.execute(ENABLE_MUTATION_TRIGGER)
    await session.commit()

    result = await verify_chain(
        session,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    assert result.ok is False
    assert result.broken_at_sequence == 3
    assert result.reason == "non-contiguous sequence"


@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
async def test_database_rejects_event_mutation(
    session: AsyncSession,
    engagement: Engagement,
    operation: str,
) -> None:
    event = await _append(session, engagement, "a")
    await session.commit()

    if operation == "update":
        events = AgentEvent.__table__
        statement = events.update().where(AgentEvent.id == event.id).values(producer="x")
    elif operation == "delete":
        statement = AgentEvent.__table__.delete().where(AgentEvent.id == event.id)
    else:
        statement = text("TRUNCATE agent_events")

    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(statement)
    await session.rollback()


async def test_composite_foreign_key_rejects_tenant_drift(
    session: AsyncSession,
    engagement: Engagement,
) -> None:
    event = await _append(session, engagement, "a")
    await session.commit()

    await session.execute(DISABLE_MUTATION_TRIGGER)
    with pytest.raises(IntegrityError):
        await session.execute(
            AgentEvent.__table__.update()
            .where(AgentEvent.id == event.id)
            .values(tenant_id="tenant-other")
        )
        await session.flush()
    await session.rollback()


async def test_migration_installs_integrity_controls(session: AsyncSession) -> None:
    triggers = set(
        (
            await session.execute(
                text(
                    """
                    SELECT tgname
                    FROM pg_trigger
                    WHERE tgrelid = 'agent_events'::regclass
                      AND NOT tgisinternal
                    """
                )
            )
        )
        .scalars()
        .all()
    )
    constraints = set(
        (
            await session.execute(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'agent_events'::regclass
                    """
                )
            )
        )
        .scalars()
        .all()
    )

    assert triggers == {"agent_events_reject_mutation", "agent_events_reject_truncate"}
    assert "fk_agent_events_engagement_tenant" in constraints
    assert "ck_agent_events_event_hash_hex" in constraints
