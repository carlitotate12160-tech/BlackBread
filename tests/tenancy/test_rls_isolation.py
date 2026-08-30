from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from blackbread.ledger import EventDraft, LedgerAccessError, append_event, verify_chain
from blackbread.models.core import Client, Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context, tenant_transaction

TENANT_SETTING = text("SELECT current_setting('blackbread.tenant_id', true)")


async def _new_engagement(factory: async_sessionmaker[AsyncSession], tenant_id: str) -> Engagement:
    async with factory() as session:
        await bind_tenant_context(session, TenantContext(tenant_id))
        client = Client(name="acme", tenant_id=tenant_id)
        session.add(client)
        await session.flush()
        engagement = Engagement(client_id=client.id, tenant_id=tenant_id, status="created")
        session.add(engagement)
        await session.commit()
        return engagement


def _draft(engagement: Engagement, marker: str) -> EventDraft:
    return EventDraft(
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        schema_name="test.rls",
        schema_version=1,
        producer="test-producer",
        payload={"marker": marker},
        occurred_at=datetime.now(UTC),
    )


async def _append_events(
    factory: async_sessionmaker[AsyncSession], engagement: Engagement, count: int
) -> None:
    async with factory() as session:
        await bind_tenant_context(session, TenantContext(engagement.tenant_id))
        for index in range(count):
            await append_event(
                session,
                _draft(engagement, f"e{index}"),
                tenant_context=TenantContext(engagement.tenant_id),
            )
        await session.commit()


async def test_protected_tables_force_row_level_security(session: AsyncSession) -> None:
    rows = (
        await session.execute(
            text(
                """
                SELECT relname, relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE relname IN ('engagements', 'agent_events')
                ORDER BY relname
                """
            )
        )
    ).all()
    security = {row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in rows}
    assert security["engagements"] == (True, True)
    assert security["agent_events"] == (True, True)


async def test_same_tenant_read_succeeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engagement = await _new_engagement(session_factory, "tenant-a")
    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-a"))
        visible = (await session.execute(select(Engagement.id))).scalars().all()
    assert visible == [engagement.id]


async def test_tenant_cannot_read_other_tenant_engagement(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    eng_a = await _new_engagement(session_factory, "tenant-a")
    eng_b = await _new_engagement(session_factory, "tenant-b")
    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-a"))
        visible = set((await session.execute(select(Engagement.id))).scalars().all())
    assert eng_a.id in visible
    assert eng_b.id not in visible


async def test_missing_context_returns_no_protected_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _new_engagement(session_factory, "tenant-a")
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))
        engagements = (await session.execute(select(Engagement.id))).scalars().all()
        events = (await session.execute(text("SELECT id FROM agent_events"))).all()
    assert engagements == []
    assert events == []


async def test_cross_tenant_insert_is_denied(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-a"))
        client = Client(name="acme", tenant_id="tenant-a")
        session.add(client)
        await session.flush()
        session.add(Engagement(client_id=client.id, tenant_id="tenant-b", status="created"))
        with pytest.raises(DBAPIError):
            await session.flush()
        await session.rollback()


async def test_tenant_cannot_read_other_tenant_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    eng_a = await _new_engagement(session_factory, "tenant-a")
    await _append_events(session_factory, eng_a, 2)
    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-b"))
        rows = (await session.execute(text("SELECT id FROM agent_events"))).all()
    assert rows == []


async def test_pooled_connection_does_not_inherit_previous_tenant(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    eng_a = await _new_engagement(session_factory, "tenant-a")
    eng_b = await _new_engagement(session_factory, "tenant-b")
    database_url = engine.url.render_as_string(hide_password=False)
    pinned = create_async_engine(database_url, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(pinned, expire_on_commit=False)
    try:
        async with factory() as first:
            await bind_tenant_context(first, TenantContext("tenant-a"))
            assert (await first.execute(select(func.count(Engagement.id)))).scalar_one() == 1
            await first.commit()

        async with factory() as second:
            await second.execute(text("SELECT 1"))
            leaked = (await second.execute(select(func.count(Engagement.id)))).scalar_one()
        assert leaked == 0

        async with factory() as third:
            await bind_tenant_context(third, TenantContext("tenant-b"))
            visible = set((await third.execute(select(Engagement.id))).scalars().all())
        assert visible == {eng_b.id}
        assert eng_a.id not in visible
    finally:
        await pinned.dispose()


async def test_rollback_clears_transaction_local_context(
    engine: AsyncEngine,
) -> None:
    database_url = engine.url.render_as_string(hide_password=False)
    pinned = create_async_engine(database_url, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(pinned, expire_on_commit=False)
    try:
        async with factory() as session:
            await bind_tenant_context(session, TenantContext("tenant-a"))
            assert (await session.execute(TENANT_SETTING)).scalar_one() == "tenant-a"
            await session.rollback()
            leaked = (await session.execute(TENANT_SETTING)).scalar_one()
        assert leaked in (None, "")
    finally:
        await pinned.dispose()


async def test_runtime_role_cannot_disable_row_level_security(
    session: AsyncSession,
) -> None:
    with pytest.raises((ProgrammingError, DBAPIError)):
        await session.execute(text("ALTER TABLE engagements DISABLE ROW LEVEL SECURITY"))
    await session.rollback()


async def test_same_tenant_append_advances_anchor_under_rls(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engagement = await _new_engagement(session_factory, "tenant-a")
    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-a"))
        event = await append_event(
            session, _draft(engagement, "first"), tenant_context=TenantContext("tenant-a")
        )
        await session.commit()

    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-a"))
        refreshed = (
            await session.execute(select(Engagement).where(Engagement.id == engagement.id))
        ).scalar_one()
        assert refreshed.ledger_event_count == 1
        assert refreshed.ledger_head_hash == event.event_hash


async def test_verify_chain_under_rls_returns_true_count(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engagement = await _new_engagement(session_factory, "tenant-a")
    await _append_events(session_factory, engagement, 3)
    result = await verify_chain(engine, tenant_id="tenant-a", engagement_id=engagement.id)
    assert result.ok is True
    assert result.verified_event_count == 3


async def test_verify_chain_cross_tenant_fails_closed(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engagement = await _new_engagement(session_factory, "tenant-a")
    await _append_events(session_factory, engagement, 2)
    with pytest.raises(LedgerAccessError):
        await verify_chain(engine, tenant_id="tenant-b", engagement_id=engagement.id)


async def test_tenant_transaction_binds_and_commits(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engagement = await _new_engagement(session_factory, "tenant-a")
    async with (
        session_factory() as session,
        tenant_transaction(session, TenantContext("tenant-a")) as bound,
    ):
        await append_event(
            bound, _draft(engagement, "tx"), tenant_context=TenantContext("tenant-a")
        )
    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-a"))
        count = (await session.execute(text("SELECT count(*) FROM agent_events"))).scalar_one()
    assert count == 1


async def test_cross_tenant_event_cannot_advance_other_tenant_head(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    victim = await _new_engagement(session_factory, "tenant-a")
    forged = EventDraft(
        tenant_id="tenant-b",
        engagement_id=victim.id,
        schema_name="test.rls",
        schema_version=1,
        producer="attacker",
        payload={"marker": "forged"},
        occurred_at=datetime.now(UTC),
    )
    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-b"))
        with pytest.raises(LedgerAccessError):
            await append_event(session, forged, tenant_context=TenantContext("tenant-b"))
        await session.rollback()

    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-a"))
        anchor = (
            await session.execute(
                select(Engagement.ledger_event_count).where(Engagement.id == victim.id)
            )
        ).scalar_one()
    assert anchor == 0
