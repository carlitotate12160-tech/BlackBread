import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from blackbread.ledger import EventDraft, LedgerAccessError, append_event
from blackbread.models.core import Client, Engagement
from blackbread.tenancy import TenantContext, TenantContextError, bind_tenant_context


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
        schema_name="test.append",
        schema_version=1,
        producer="test-producer",
        payload={"marker": marker},
        occurred_at=datetime.now(UTC),
    )


async def test_append_binds_context_without_caller_side_binding(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engagement = await _new_engagement(session_factory, "tenant-a")
    async with session_factory() as session:
        event = await append_event(
            session,
            _draft(engagement, "one"),
            tenant_context=TenantContext("tenant-a"),
        )
        await session.commit()
    assert event.sequence == 1


async def test_append_rejects_mismatched_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engagement = await _new_engagement(session_factory, "tenant-a")
    async with session_factory() as session:
        with pytest.raises(TenantContextError):
            await append_event(
                session,
                _draft(engagement, "bad"),
                tenant_context=TenantContext("tenant-b"),
            )
        await session.rollback()


async def test_append_requires_explicit_context() -> None:
    with pytest.raises(TypeError):
        await append_event(object(), object())  # type: ignore[call-arg]


async def test_append_context_unavailable_engagement_still_raises_access_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        draft = EventDraft(
            tenant_id="tenant-a",
            engagement_id=uuid.uuid4(),
            schema_name="test.append",
            schema_version=1,
            producer="test-producer",
            payload={"marker": "x"},
            occurred_at=datetime.now(UTC),
        )
        with pytest.raises(LedgerAccessError):
            await append_event(session, draft, tenant_context=TenantContext("tenant-a"))
        await session.rollback()


async def test_direct_protected_write_without_context_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    engagement = await _new_engagement(session_factory, "tenant-a")
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))
        anchor = (
            await session.execute(select(Engagement.id).where(Engagement.id == engagement.id))
        ).one_or_none()
    assert anchor is None
