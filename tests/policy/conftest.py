"""Fixtures for M1.4c1 policy-record substrate tests.

Provides an admin (RLS-bypassing) engine and an engagement seed helper for the constraint,
isolation, and immutability suites, plus an isolated disposable-database lifecycle harness for the
migration lifecycle suite. The lifecycle harness never touches the shared development or Oracle
production database.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import (
    TEST_MIGRATION_DATABASE_URL,
    TEST_RUNTIME_PASSWORD,
)

ROOT = Path(__file__).parents[2]
GENESIS_HASH = "0" * 64


async def _ensure_roles() -> None:
    admin = create_async_engine(TEST_MIGRATION_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'blackbread_runtime')")
            )
            if not exists:
                await conn.execute(
                    text(
                        "CREATE ROLE blackbread_runtime NOLOGIN NOINHERIT NOSUPERUSER "
                        "NOCREATEDB NOCREATEROLE NOREPLICATION"
                    )
                )
            recorder_exists = await conn.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_roles "
                    "WHERE rolname = 'blackbread_policy_recorder')"
                )
            )
            if not recorder_exists:
                await conn.execute(
                    text(
                        "CREATE ROLE blackbread_policy_recorder NOLOGIN NOINHERIT NOSUPERUSER "
                        "NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION"
                    )
                )
            await conn.execute(text("DROP ROLE IF EXISTS blackbread_test_runtime"))
            create = await conn.scalar(
                text(
                    "SELECT format("
                    "'CREATE ROLE blackbread_test_runtime LOGIN NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOREPLICATION PASSWORD %L IN ROLE blackbread_runtime', "
                    "CAST(:password AS text))"
                ),
                {"password": TEST_RUNTIME_PASSWORD},
            )
            if not isinstance(create, str):
                raise RuntimeError("failed to construct the test runtime role")
            await conn.execute(text(create))
    finally:
        await admin.dispose()


@pytest.fixture(scope="module", autouse=True)
def ensure_runtime_role() -> None:
    asyncio.run(_ensure_roles())


@pytest_asyncio.fixture
async def policy_admin_engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    """Superuser engine on the shared test database; bypasses RLS for admin/migration proofs."""
    engine = create_async_engine(TEST_MIGRATION_DATABASE_URL, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


async def seed_engagement(engine: AsyncEngine, tenant_id: str, engagement_id: uuid.UUID) -> None:
    """Insert a client and engagement via the admin engine so records can reference them."""
    client_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO clients (id, name, tenant_id) VALUES (:id, :name, :tid) "
                "ON CONFLICT DO NOTHING"
            ),
            {"id": client_id, "name": "policy-record-client", "tid": tenant_id},
        )
        await conn.execute(
            text(
                "INSERT INTO engagements (id, client_id, tenant_id) "
                "VALUES (:id, :cid, :tid) ON CONFLICT DO NOTHING"
            ),
            {"id": engagement_id, "cid": client_id, "tid": tenant_id},
        )


async def seed_ledger_event(engine: AsyncEngine, tenant_id: str, engagement_id: uuid.UUID) -> str:
    """Append one shaped agent_events row, exercising the ≤0006 ledger advance trigger."""
    event_hash = uuid.uuid4().hex + uuid.uuid4().hex
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO agent_events (id, engagement_id, tenant_id, sequence, schema_name, "
                "schema_version, producer, occurred_at, recorded_at, payload, payload_hash, "
                "prev_event_hash, event_hash) VALUES (:id, :eid, :tid, 1, 'engagement.attested', "
                "1, 'conductor', now(), now(), CAST('{}' AS jsonb), :ph, :prev, :eh)"
            ),
            {
                "id": uuid.uuid4(),
                "eid": engagement_id,
                "tid": tenant_id,
                "ph": "a" * 64,
                "prev": GENESIS_HASH,
                "eh": event_hash,
            },
        )
    return event_hash


# ---------------------------------------------------------------------------
# Disposable-database migration lifecycle harness
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lifecycle_db() -> Iterator[str]:
    """Create and drop a private temporary database for destructive migration lifecycle tests."""
    db_name = f"blackbread_test_policy_{uuid.uuid4().hex[:8]}"

    async def _run(sql: str) -> None:
        admin = create_async_engine(TEST_MIGRATION_DATABASE_URL, isolation_level="AUTOCOMMIT")
        try:
            async with admin.connect() as conn:
                await conn.execute(text(sql))
        finally:
            await admin.dispose()

    asyncio.run(_run(f"CREATE DATABASE {db_name}"))
    yield db_name
    asyncio.run(
        _run(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "  # noqa: S608
            f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid()"
        )
    )
    asyncio.run(_run(f"DROP DATABASE IF EXISTS {db_name}"))


def run_alembic(db_name: str, *args: str) -> None:
    """Run an alembic command against the lifecycle database only."""
    env = os.environ.copy()
    env["BLACKBREAD_DATABASE_URL"] = (
        make_url(TEST_MIGRATION_DATABASE_URL)
        .set(database=db_name)
        .render_as_string(hide_password=False)
    )
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, check=True)


@pytest_asyncio.fixture(scope="module")
async def lifecycle_admin_engine(lifecycle_db: str) -> AsyncIterator[AsyncEngine]:
    """Superuser engine bound to the lifecycle database."""
    url = make_url(TEST_MIGRATION_DATABASE_URL).set(database=lifecycle_db)
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()
