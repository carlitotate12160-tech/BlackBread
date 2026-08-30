import asyncio
import uuid
from datetime import UTC, datetime
from types import MappingProxyType

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blackbread.ledger import EventDraft, LedgerAccessError, append_event, verify_chain
from blackbread.ledger.event import GENESIS_PREV_HASH, AgentEvent
from blackbread.models.core import Client, Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context


async def _bind(binder: AsyncSession, tenant_id: str) -> None:
    await bind_tenant_context(binder, TenantContext(tenant_id))


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
    await _bind(session, engagement.tenant_id)
    return await append_event(
        session, _draft(engagement, marker), tenant_context=TenantContext(engagement.tenant_id)
    )


async def _seed_engagement(factory: async_sessionmaker[AsyncSession], tenant_id: str) -> Engagement:
    async with factory() as setup:
        await _bind(setup, tenant_id)
        client = Client(name="acme", tenant_id=tenant_id)
        setup.add(client)
        await setup.flush()
        engagement = Engagement(client_id=client.id, tenant_id=tenant_id)
        setup.add(engagement)
        await setup.commit()
        return engagement


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
    await _bind(session, engagement.tenant_id)
    await session.refresh(engagement)
    assert engagement.ledger_event_count == 3
    assert engagement.ledger_head_hash == third.event_hash


async def test_mutated_source_payload_cannot_bypass_validated_snapshot(
    session: AsyncSession,
    engagement: Engagement,
) -> None:
    source: dict[str, object] = {"marker": "validated"}
    draft = EventDraft(
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        schema_name="test.snapshot",
        schema_version=1,
        producer="test-producer",
        payload=source,
        occurred_at=datetime.now(UTC),
    )
    source["oversized"] = "x" * 1_048_577

    await _bind(session, engagement.tenant_id)
    event = await append_event(session, draft, tenant_context=TenantContext(engagement.tenant_id))
    await session.commit()

    assert event.payload == {"marker": "validated"}
    assert "oversized" not in event.payload


async def test_mapping_and_stable_float_round_trip_through_jsonb(
    engine: AsyncEngine,
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
    await _bind(session, engagement.tenant_id)
    event = await append_event(session, draft, tenant_context=TenantContext(engagement.tenant_id))
    event_id = event.id
    await session.commit()
    session.expunge_all()

    await _bind(session, engagement.tenant_id)
    reloaded = (
        await session.execute(select(AgentEvent).where(AgentEvent.id == event_id))
    ).scalar_one()
    result = await verify_chain(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )

    assert reloaded.payload == {"score": 1.5, "nested": {"marker": "x"}}
    assert result.ok is True
    assert result.event_count == 1


async def test_verify_passes_for_untampered_chain(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
) -> None:
    for marker in ("a", "b", "c", "d"):
        await _append(session, engagement, marker)
    await session.commit()

    result = await verify_chain(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )

    assert result.ok is True
    assert result.event_count == 4
    assert result.broken_at_sequence is None


@pytest.mark.parametrize(
    "case",
    [
        ("payload", {"marker": "TAMPERED"}, "payload hash mismatch"),
        ("prev_event_hash", "f" * 64, "broken prev-hash link"),
        ("event_hash", "a" * 64, "event hash mismatch"),
        ("sensitivity", "restricted", "event hash mismatch"),
        ("redaction_refs", ["artifact://redacted/2"], "event hash mismatch"),
    ],
)
async def test_verify_detects_tamper(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    case: tuple[str, object, str],
) -> None:
    column, value, reason = case
    await _append(session, engagement, "a")
    target = await _append(session, engagement, "b")
    await _append(session, engagement, "c")
    await session.commit()

    await _corrupt(
        admin_session,
        AgentEvent.__table__.update().where(AgentEvent.id == target.id).values({column: value}),
    )
    result = await verify_chain(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )

    assert result.ok is False
    assert result.broken_at_sequence == 2
    assert result.reason == reason


async def test_append_and_verify_fail_closed_for_wrong_tenant(
    engine: AsyncEngine,
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
        await append_event(session, wrong, tenant_context=TenantContext("tenant-other"))
    with pytest.raises(LedgerAccessError):
        await verify_chain(
            engine,
            tenant_id="tenant-other",
            engagement_id=engagement.id,
        )


async def test_missing_engagement_fails_closed(
    engine: AsyncEngine,
    session: AsyncSession,
) -> None:
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
            tenant_context=TenantContext("tenant-a"),
        )
    with pytest.raises(LedgerAccessError):
        await verify_chain(
            engine,
            tenant_id="tenant-a",
            engagement_id=engagement_id,
        )


async def test_two_engagements_have_independent_chains(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    eng_a = await _seed_engagement(session_factory, "tenant-a")
    eng_b = await _seed_engagement(session_factory, "tenant-b")

    async with session_factory() as active:
        await _bind(active, "tenant-a")
        for marker in ("a1", "a2"):
            await append_event(
                active, _draft(eng_a, marker), tenant_context=TenantContext("tenant-a")
            )
        await active.commit()

    async with session_factory() as active:
        await _bind(active, "tenant-b")
        first_b = await append_event(
            active, _draft(eng_b, "b1"), tenant_context=TenantContext("tenant-b")
        )
        await active.commit()
        assert first_b.sequence == 1
        assert first_b.prev_event_hash == GENESIS_PREV_HASH

    async with session_factory() as active:
        result_a = await verify_chain(
            engine,
            tenant_id=eng_a.tenant_id,
            engagement_id=eng_a.id,
        )
        result_b = await verify_chain(
            engine,
            tenant_id=eng_b.tenant_id,
            engagement_id=eng_b.id,
        )
        assert result_a.event_count == 2
        assert result_b.event_count == 1


async def test_concurrent_appends_serialize_without_gaps(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engagement = await _seed_engagement(session_factory, "tenant-c")

    async def append_one(marker: str) -> None:
        async with session_factory() as active:
            await _bind(active, "tenant-c")
            await append_event(
                active, _draft(engagement, marker), tenant_context=TenantContext("tenant-c")
            )
            await active.commit()

    await asyncio.gather(*(append_one(f"m{index}") for index in range(10)))

    async with session_factory() as active:
        await _bind(active, "tenant-c")
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
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )
        assert result.ok is True


async def test_verify_detects_deleted_middle_event(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
) -> None:
    await _append(session, engagement, "a")
    middle = await _append(session, engagement, "b")
    await _append(session, engagement, "c")
    await session.commit()

    await admin_session.execute(DISABLE_MUTATION_TRIGGER)
    await admin_session.execute(AgentEvent.__table__.delete().where(AgentEvent.id == middle.id))
    await admin_session.execute(ENABLE_MUTATION_TRIGGER)
    await admin_session.commit()

    result = await verify_chain(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    assert result.ok is False
    assert result.broken_at_sequence == 3
    assert result.reason == "non-contiguous sequence"


async def test_verify_detects_deleted_tail_event(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
) -> None:
    await _append(session, engagement, "a")
    await _append(session, engagement, "b")
    last = await _append(session, engagement, "c")
    await session.commit()

    await _corrupt(
        admin_session,
        AgentEvent.__table__.delete().where(AgentEvent.id == last.id),
    )
    result = await verify_chain(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )

    assert result.ok is False
    assert result.event_count == 2
    assert result.broken_at_sequence == 3
    assert result.reason == "anchored event count mismatch"


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

    with pytest.raises(DBAPIError, match="permission denied"):
        await session.execute(statement)
    await session.rollback()


async def test_composite_foreign_key_rejects_tenant_drift(
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
) -> None:
    event = await _append(session, engagement, "a")
    await session.commit()

    await admin_session.execute(DISABLE_MUTATION_TRIGGER)
    with pytest.raises(IntegrityError):
        await admin_session.execute(
            AgentEvent.__table__.update()
            .where(AgentEvent.id == event.id)
            .values(tenant_id="tenant-other")
        )
    await admin_session.rollback()


async def test_runtime_role_cannot_disable_integrity_triggers(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError, match=r"must be owner|permission denied"):
        await session.execute(DISABLE_MUTATION_TRIGGER)
    await session.rollback()


async def test_runtime_role_cannot_change_engagement_lock_sentinel(
    session: AsyncSession,
    engagement: Engagement,
) -> None:
    await _bind(session, engagement.tenant_id)
    with pytest.raises(IntegrityError, match="ck_engagements_ledger_lock_token"):
        await session.execute(
            Engagement.__table__.update()
            .where(Engagement.id == engagement.id)
            .values(ledger_lock_token=1)
        )
    await session.rollback()


async def test_runtime_role_has_only_required_table_privileges(session: AsyncSession) -> None:
    row = (
        await session.execute(
            text(
                """
                SELECT
                    current_user,
                    pg_get_userbyid(c.relowner) AS table_owner,
                    has_table_privilege(current_user, 'agent_events', 'SELECT') AS can_select,
                    has_table_privilege(current_user, 'agent_events', 'INSERT') AS can_insert,
                    has_table_privilege(current_user, 'agent_events', 'UPDATE') AS can_update,
                    has_table_privilege(current_user, 'agent_events', 'DELETE') AS can_delete,
                    has_table_privilege(current_user, 'agent_events', 'TRUNCATE') AS can_truncate,
                    has_table_privilege(
                        current_user, 'engagements', 'UPDATE'
                    ) AS can_update_engagement,
                    has_column_privilege(
                        current_user, 'engagements', 'ledger_lock_token', 'UPDATE'
                    ) AS can_lock_engagement,
                    has_column_privilege(
                        current_user, 'engagements', 'tenant_id', 'UPDATE'
                    ) AS can_update_engagement_tenant,
                    has_column_privilege(
                        current_user, 'engagements', 'ledger_event_count', 'UPDATE'
                    ) AS can_update_ledger_count,
                    has_column_privilege(
                        current_user, 'engagements', 'ledger_head_hash', 'UPDATE'
                    ) AS can_update_ledger_head
                FROM pg_class AS c
                WHERE c.oid = 'agent_events'::regclass
                """
            )
        )
    ).one()

    assert row.current_user == "blackbread_test_runtime"
    assert row.table_owner != row.current_user
    assert row.can_select is True
    assert row.can_insert is True
    assert row.can_update is False
    assert row.can_delete is False
    assert row.can_truncate is False
    assert row.can_update_engagement is False
    assert row.can_lock_engagement is True
    assert row.can_update_engagement_tenant is False
    assert row.can_update_ledger_count is False
    assert row.can_update_ledger_head is False


async def test_runtime_group_has_no_parent_memberships(session: AsyncSession) -> None:
    parent_roles = (
        (
            await session.execute(
                text(
                    """
                    SELECT parent.rolname
                    FROM pg_auth_members AS membership
                    JOIN pg_roles AS runtime ON runtime.oid = membership.member
                    JOIN pg_roles AS parent ON parent.oid = membership.roleid
                    WHERE runtime.rolname = 'blackbread_runtime'
                    """
                )
            )
        )
        .scalars()
        .all()
    )

    assert parent_roles == []


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

    assert triggers == {
        "agent_events_advance_head",
        "agent_events_reject_mutation",
        "agent_events_reject_truncate",
    }
    assert "fk_agent_events_engagement_tenant" in constraints
    assert "ck_agent_events_event_hash_hex" in constraints
