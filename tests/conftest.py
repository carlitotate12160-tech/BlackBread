import asyncio
import base64
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

os.environ.setdefault(
    "BLACKBREAD_ARTIFACT_KEY",
    base64.urlsafe_b64encode(bytes(range(32))).decode("ascii"),
)

from blackbread.models.core import Client, Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context

ROOT = Path(__file__).parents[1]
TEST_DATABASE_NAME = "blackbread_test"
TEST_DATABASE_URL = os.environ.get(
    "BLACKBREAD_TEST_DATABASE_URL",
    "postgresql+asyncpg://blackbread_test_runtime:blackbread_test_runtime"
    "@127.0.0.1:55432/blackbread_test",
)
TEST_MIGRATION_DATABASE_URL = os.environ.get(
    "BLACKBREAD_TEST_MIGRATION_DATABASE_URL",
    "postgresql+asyncpg://postgres@127.0.0.1:55432/blackbread_test",
)
TEST_RUNTIME_PASSWORD = os.environ.get(
    "BLACKBREAD_TEST_RUNTIME_PASSWORD",
    "blackbread_test_runtime",
)


def _validated_test_url(value: str) -> URL:
    url = make_url(value)
    if url.database != TEST_DATABASE_NAME:
        raise RuntimeError(f"ledger tests require database {TEST_DATABASE_NAME}")
    if url.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("ledger tests require a loopback PostgreSQL host")
    return url


def _migration_environment() -> dict[str, str]:
    _validated_test_url(TEST_DATABASE_URL)
    _validated_test_url(TEST_MIGRATION_DATABASE_URL)
    environment = os.environ.copy()
    environment["BLACKBREAD_DATABASE_URL"] = TEST_MIGRATION_DATABASE_URL
    return environment


async def _prepare_runtime_roles() -> None:
    admin = create_async_engine(TEST_MIGRATION_DATABASE_URL)
    try:
        async with admin.begin() as connection:
            role_exists = await connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'blackbread_runtime')")
            )
            if not role_exists:
                await connection.execute(
                    text(
                        "CREATE ROLE blackbread_runtime NOLOGIN NOINHERIT NOSUPERUSER "
                        "NOCREATEDB NOCREATEROLE NOREPLICATION"
                    )
                )
            await connection.execute(text("DROP ROLE IF EXISTS blackbread_test_runtime"))
            create_login = await connection.scalar(
                text(
                    "SELECT format("
                    "'CREATE ROLE blackbread_test_runtime LOGIN NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOREPLICATION PASSWORD %L IN ROLE blackbread_runtime', "
                    "CAST(:password AS text))"
                ),
                {"password": TEST_RUNTIME_PASSWORD},
            )
            if not isinstance(create_login, str):
                raise RuntimeError("failed to construct the test runtime role")
            await connection.execute(text(create_login))
    finally:
        await admin.dispose()


async def _drop_runtime_login() -> None:
    admin = create_async_engine(TEST_MIGRATION_DATABASE_URL)
    try:
        async with admin.begin() as connection:
            await connection.execute(text("DROP ROLE IF EXISTS blackbread_test_runtime"))
    finally:
        await admin.dispose()


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[None]:
    environment = _migration_environment()
    asyncio.run(_prepare_runtime_roles())
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    yield
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    asyncio.run(_drop_runtime_login())


@pytest_asyncio.fixture
async def engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    admin = create_async_engine(TEST_MIGRATION_DATABASE_URL, pool_pre_ping=True)
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text("ALTER TABLE agent_events DISABLE TRIGGER agent_events_reject_mutation")
            )
            await connection.execute(
                text("ALTER TABLE agent_events DISABLE TRIGGER agent_events_reject_truncate")
            )
            await connection.execute(text("TRUNCATE agent_events, engagements, clients"))
            await connection.execute(
                text("ALTER TABLE agent_events ENABLE TRIGGER agent_events_reject_mutation")
            )
            await connection.execute(
                text("ALTER TABLE agent_events ENABLE TRIGGER agent_events_reject_truncate")
            )
    finally:
        await admin.dispose()

    runtime = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield runtime
    await runtime.dispose()


@pytest_asyncio.fixture
async def admin_session(migrated_database: None) -> AsyncIterator[AsyncSession]:
    admin = create_async_engine(TEST_MIGRATION_DATABASE_URL, pool_pre_ping=True)
    factory = async_sessionmaker(admin, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await admin.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as active:
        yield active


async def bind_tenant(binder: AsyncSession, tenant_id: str) -> None:
    """Bind ``tenant_id`` to the binder's active transaction for a test."""

    await bind_tenant_context(binder, TenantContext(tenant_id))


async def create_engagement(
    session: AsyncSession,
    tenant_id: str,
    *,
    client: Client | None = None,
    status: str = "created",
) -> Engagement:
    """Insert a tenant-owned client and engagement under the bound tenant context."""

    await bind_tenant(session, tenant_id)
    if client is None:
        client = Client(name="acme", tenant_id=tenant_id)
        session.add(client)
        await session.flush()
    engagement = Engagement(client_id=client.id, tenant_id=tenant_id, status=status)
    session.add(engagement)
    await session.flush()
    return engagement


@pytest_asyncio.fixture
async def engagement(session: AsyncSession) -> Engagement:
    client_id = uuid.uuid4()
    tenant_id = str(client_id)
    await bind_tenant(session, tenant_id)
    client = Client(id=client_id, name="acme", tenant_id=tenant_id)
    session.add(client)
    await session.flush()
    record = await create_engagement(session, tenant_id, client=client)
    await session.commit()
    return record
