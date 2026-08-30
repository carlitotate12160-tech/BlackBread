import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from blackbread.ledger import EventDraft, append_event
from blackbread.models.core import Client, Engagement
from blackbread.tenancy import (
    TenantContext,
    TenantContextError,
    bind_tenant_context,
    tenant_transaction,
)

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
        schema_name="test.binding",
        schema_version=1,
        producer="test-producer",
        payload={"marker": marker},
        occurred_at=datetime.now(UTC),
    )


async def test_identical_rebind_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-a"))
        await bind_tenant_context(session, TenantContext("tenant-a"))
        assert (await session.execute(TENANT_SETTING)).scalar_one() == "tenant-a"
        await session.rollback()


async def test_rebind_to_different_tenant_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-a"))
        with pytest.raises(TenantContextError):
            await bind_tenant_context(session, TenantContext("tenant-b"))
        assert (await session.execute(TENANT_SETTING)).scalar_one() == "tenant-a"
        await session.rollback()


async def test_rebind_allowed_in_a_fresh_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-a"))
        await session.rollback()
        await bind_tenant_context(session, TenantContext("tenant-b"))
        assert (await session.execute(TENANT_SETTING)).scalar_one() == "tenant-b"
        await session.rollback()


async def test_tenant_transaction_rolls_back_and_clears_on_error(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engagement = await _new_engagement(session_factory, "tenant-a")

    class _BoomError(RuntimeError):
        pass

    async with session_factory() as session:
        with pytest.raises(_BoomError):
            async with tenant_transaction(session, TenantContext("tenant-a")) as bound:
                await append_event(
                    bound, _draft(engagement, "doomed"), tenant_context=TenantContext("tenant-a")
                )
                raise _BoomError
        leaked = (await session.execute(TENANT_SETTING)).scalar_one()
        assert leaked in (None, "")

    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-a"))
        count = (await session.execute(text("SELECT count(*) FROM agent_events"))).scalar_one()
    assert count == 0


async def test_tenant_transaction_cancellation_releases_pool(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engagement = await _new_engagement(session_factory, "tenant-a")
    database_url = engine.url.render_as_string(hide_password=False)
    pinned = create_async_engine(database_url, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(pinned, expire_on_commit=False)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def worker() -> None:
        async with (
            factory() as session,
            tenant_transaction(session, TenantContext("tenant-a")) as bound,
        ):
            await append_event(
                bound, _draft(engagement, "cancelled"), tenant_context=TenantContext("tenant-a")
            )
            entered.set()
            await release.wait()

    try:
        task = asyncio.create_task(worker())
        await asyncio.wait_for(entered.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async with factory() as session:
            await bind_tenant_context(session, TenantContext("tenant-a"))
            count = (
                await session.execute(select(func.count()).select_from(Engagement))
            ).scalar_one()
            leaked = (await session.execute(text("SELECT count(*) FROM agent_events"))).scalar_one()
        assert count == 1
        assert leaked == 0
        assert pinned.pool.checkedout() == 0
    finally:
        release.set()
        await pinned.dispose()
