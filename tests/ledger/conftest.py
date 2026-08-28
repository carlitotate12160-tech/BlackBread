import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from blackbread.models.core import Client, Engagement

ROOT = Path(__file__).parents[2]
TEST_DATABASE_URL = os.environ.get(
    "BLACKBREAD_TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres@127.0.0.1:55432/blackbread_test",
)
TEST_DATABASE_NAME = "blackbread_test"


def _migration_environment() -> dict[str, str]:
    url = make_url(TEST_DATABASE_URL)
    if url.database != TEST_DATABASE_NAME:
        raise RuntimeError(f"ledger tests require database {TEST_DATABASE_NAME}")
    if url.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("ledger tests require a loopback PostgreSQL host")
    environment = os.environ.copy()
    environment["BLACKBREAD_DATABASE_URL"] = TEST_DATABASE_URL
    return environment


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[None]:
    environment = _migration_environment()
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


@pytest_asyncio.fixture
async def engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    created = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    async with created.begin() as connection:
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
    yield created
    await created.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as active:
        yield active


@pytest_asyncio.fixture
async def engagement(session: AsyncSession) -> Engagement:
    client = Client(name="acme")
    session.add(client)
    await session.flush()
    record = Engagement(client_id=client.id, tenant_id=str(client.id), status="created")
    session.add(record)
    await session.commit()
    return record
