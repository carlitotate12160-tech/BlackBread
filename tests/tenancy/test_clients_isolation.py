import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from blackbread.models.core import Client, Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context
from blackbread.tenancy.client_backfill import (
    AmbiguousClientTenantError,
    resolve_client_tenants,
)


async def _new_client(factory: async_sessionmaker[AsyncSession], tenant_id: str) -> Client:
    async with factory() as session:
        await bind_tenant_context(session, TenantContext(tenant_id))
        client = Client(name="acme", tenant_id=tenant_id)
        session.add(client)
        await session.commit()
        return client


async def test_clients_force_row_level_security(session: AsyncSession) -> None:
    row = (
        await session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE relname = 'clients'"
            )
        )
    ).one()
    assert (row.relrowsecurity, row.relforcerowsecurity) == (True, True)


async def test_tenant_cannot_read_other_tenant_clients(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client_a = await _new_client(session_factory, "tenant-a")
    client_b = await _new_client(session_factory, "tenant-b")
    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-a"))
        visible = set((await session.execute(select(Client.id))).scalars().all())
    assert client_a.id in visible
    assert client_b.id not in visible


async def test_missing_context_hides_all_clients(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _new_client(session_factory, "tenant-a")
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))
        count = (await session.execute(select(func.count(Client.id)))).scalar_one()
    assert count == 0


async def test_tenant_cannot_insert_client_for_other_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await bind_tenant_context(session, TenantContext("tenant-a"))
        session.add(Client(name="acme", tenant_id="tenant-b"))
        with pytest.raises(DBAPIError):
            await session.flush()
        await session.rollback()


async def test_engagement_cannot_reference_other_tenant_client(
    session_factory: async_sessionmaker[AsyncSession],
    admin_session: AsyncSession,
) -> None:
    client_a = await _new_client(session_factory, "tenant-a")
    with pytest.raises(IntegrityError):
        await admin_session.execute(
            Engagement.__table__.insert().values(
                id=uuid.uuid4(),
                client_id=client_a.id,
                tenant_id="tenant-b",
                status="created",
            )
        )
    await admin_session.rollback()


def test_backfill_resolves_single_tenant_client() -> None:
    client_id = uuid.uuid4()
    assignments = resolve_client_tenants([(client_id, "tenant-a"), (client_id, "tenant-a")])
    assert assignments == {client_id: "tenant-a"}


def test_backfill_rejects_multiple_tenant_client() -> None:
    client_id = uuid.uuid4()
    with pytest.raises(AmbiguousClientTenantError):
        resolve_client_tenants([(client_id, "tenant-a"), (client_id, "tenant-b")])


def test_backfill_rejects_client_without_tenant() -> None:
    client_id = uuid.uuid4()
    with pytest.raises(AmbiguousClientTenantError):
        resolve_client_tenants([], orphan_client_ids=[client_id])
