"""Migration 0005/0006 temporal graph lifecycle tests."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from blackbread.graph.domain import scope_root_id
from blackbread.graph.revision import ScopeRevision
from tests.graph.conftest import (
    FIXED_TIME,
    TEST_MIGRATION_DATABASE_URL,
    TEST_RUNTIME_PASSWORD,
    _run_alembic,
    _seed_attestation_event,
    _seed_engagement,
)
from tests.graph.conftest import (
    SCHEMA_TENANT as TENANT,
)


async def _ensure_roles() -> None:
    admin = create_async_engine(TEST_MIGRATION_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            role_exists = await conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'blackbread_runtime')")
            )
            if not role_exists:
                await conn.execute(
                    text(
                        "CREATE ROLE blackbread_runtime NOLOGIN NOINHERIT NOSUPERUSER "
                        "NOCREATEDB NOCREATEROLE NOREPLICATION"
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


@asynccontextmanager
async def _admin_engine(db_name: str) -> AsyncIterator[AsyncEngine]:
    url = make_url(TEST_MIGRATION_DATABASE_URL).set(database=db_name)
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _seed_one_attestation(admin: AsyncEngine, tenant: str) -> tuple[uuid.UUID, str]:
    eid = uuid.uuid4()
    await _seed_engagement(admin, tenant, eid)
    event_hash = await _seed_attestation_event(admin, tenant, eid)
    return eid, event_hash


async def _insert_v1_graph(
    conn: AsyncConnection,
    tenant: str,
    eid: uuid.UUID,
    event_hash: str,
) -> None:
    node_id = scope_root_id("root_domain", "example.com")
    await conn.execute(
        text("SELECT set_config('blackbread.tenant_id', :tid, true)"),
        {"tid": tenant},
    )
    await conn.execute(
        text(
            "INSERT INTO graph_projection_snapshots "
            "(tenant_id, engagement_id, verified_event_count, verified_head_hash, "
            "ledger_hash_algorithm, ledger_hash_version, projector_version, "
            "state_root_version, state_root) "
            "VALUES (:tid, :eid, 1, :eh, 'sha256', 1, 1, 1, :sr)"
        ),
        {"tid": tenant, "eid": eid, "eh": event_hash, "sr": "b" * 64},
    )
    await conn.execute(
        text(
            "INSERT INTO graph_nodes "
            "(tenant_id, engagement_id, graph_version, node_id, node_family, scope_kind, "
            "canonical_value, authority, manifest_hash, valid_from, valid_until, "
            "source_sequence, source_event_hash, source_schema_name, source_schema_version) "
            "VALUES (:tid, :eid, 1, :nid, 'ScopeRoot', 'root_domain', "
            "'example.com', 'attested_scope', :mh, :vf, :vu, 1, :seh, "
            "'engagement.attested', 1)"
        ),
        {
            "tid": tenant,
            "eid": eid,
            "nid": node_id,
            "mh": "a" * 64,
            "vf": FIXED_TIME,
            "vu": FIXED_TIME + timedelta(days=7),
            "seh": event_hash,
        },
    )


async def _insert_v1_temporal(
    conn: AsyncConnection,
    tenant: str,
    eid: uuid.UUID,
    event_hash: str,
) -> None:
    node_id = scope_root_id("root_domain", "example.com")
    rev = ScopeRevision(
        node_id=node_id,
        scope_kind="root_domain",
        canonical_value="example.com",
        manifest_hash="a" * 64,
        valid_from=FIXED_TIME,
        valid_until=FIXED_TIME + timedelta(days=7),
        source_sequence=1,
        source_event_hash=event_hash,
        source_schema_name="engagement.attested",
        source_schema_version=1,
        predecessor_attestation_event_hash=None,
    )
    await conn.execute(
        text("SELECT set_config('blackbread.tenant_id', :tid, true)"),
        {"tid": tenant},
    )
    await conn.execute(
        text(
            "INSERT INTO graph_temporal_scope_roots "
            "(tenant_id, engagement_id, node_id, node_family, scope_kind, canonical_value) "
            "VALUES (:tid, :eid, :nid, 'ScopeRoot', 'root_domain', 'example.com')"
        ),
        {"tid": tenant, "eid": eid, "nid": node_id},
    )
    await conn.execute(
        text(
            "INSERT INTO graph_temporal_scope_revisions "
            "(tenant_id, engagement_id, revision_id, node_id, scope_kind, canonical_value, "
            "manifest_hash, valid_from, valid_until, source_sequence, source_event_hash, "
            "source_schema_name, source_schema_version, predecessor_attestation_event_hash) "
            "VALUES (:tid, :eid, :rid, :nid, 'root_domain', "
            "'example.com', :mh, :vf, :vu, 1, :seh, "
            "'engagement.attested', 1, NULL)"
        ),
        {
            "tid": tenant,
            "eid": eid,
            "rid": rev.revision_id,
            "nid": node_id,
            "mh": "a" * 64,
            "vf": FIXED_TIME,
            "vu": FIXED_TIME + timedelta(days=7),
            "seh": event_hash,
        },
    )


async def _count_0005(admin: AsyncEngine, tenant: str) -> tuple[int, int]:
    async with admin.begin() as conn:
        snapshots = await conn.scalar(
            text("SELECT count(*) FROM graph_projection_snapshots WHERE tenant_id = :tid"),
            {"tid": tenant},
        )
        nodes = await conn.scalar(
            text("SELECT count(*) FROM graph_nodes WHERE tenant_id = :tid"),
            {"tid": tenant},
        )
    return int(snapshots or 0), int(nodes or 0)


async def _temporal_tables_exist(admin: AsyncEngine) -> bool:
    async with admin.begin() as conn:
        row = await conn.execute(
            text(
                "SELECT to_regclass('public.graph_temporal_projection_snapshots') "
                "AS snapshots, "
                "to_regclass('public.graph_temporal_scope_roots') AS roots, "
                "to_regclass('public.graph_temporal_scope_revisions') AS revisions, "
                "to_regclass('public.graph_temporal_head_nodes') AS head_nodes"
            )
        )
        result = row.one()
    return any(
        value is not None
        for value in (result.snapshots, result.roots, result.revisions, result.head_nodes)
    )


async def _temporal_function_exists(admin: AsyncEngine) -> bool:
    async with admin.begin() as conn:
        row = await conn.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_proc "
                "WHERE proname = 'blackbread_require_attested_temporal_revision'"
                ") AS exists"
            )
        )
        return bool(row.one().exists)


class TestMigrationLifecycle:
    async def test_upgrade_0005_and_0006_idempotent(
        self,
        lifecycle_db: str,
        lifecycle_runtime_engine: AsyncEngine,
    ) -> None:
        _run_alembic(lifecycle_db, "downgrade", "base")
        _run_alembic(lifecycle_db, "upgrade", "0005")

        async with _admin_engine(lifecycle_db) as admin:
            eid, event_hash = await _seed_one_attestation(admin, TENANT)
            async with lifecycle_runtime_engine.begin() as conn:
                await _insert_v1_graph(conn, TENANT, eid, event_hash)

        _run_alembic(lifecycle_db, "upgrade", "0006")

        async with _admin_engine(lifecycle_db) as admin:
            snapshots, nodes = await _count_0005(admin, TENANT)
            assert snapshots == 1
            assert nodes == 1

        _run_alembic(lifecycle_db, "downgrade", "0005")

        async with _admin_engine(lifecycle_db) as admin:
            assert not (await _temporal_tables_exist(admin))
            assert not (await _temporal_function_exists(admin))

        _run_alembic(lifecycle_db, "upgrade", "0006")

    async def test_0006_rls_and_runtime_role_isolation(
        self,
        lifecycle_db: str,
        lifecycle_runtime_engine: AsyncEngine,
    ) -> None:
        _run_alembic(lifecycle_db, "downgrade", "base")
        _run_alembic(lifecycle_db, "upgrade", "0006")

        tenants = ("tenant-a", "tenant-b")
        async with _admin_engine(lifecycle_db) as admin:
            seeded = {t: await _seed_one_attestation(admin, t) for t in tenants}

        for tenant, (eid, event_hash) in seeded.items():
            async with lifecycle_runtime_engine.begin() as conn:
                await _insert_v1_temporal(conn, tenant, eid, event_hash)

        for tenant in tenants:
            async with lifecycle_runtime_engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('blackbread.tenant_id', :tid, true)"),
                    {"tid": tenant},
                )
                count = await conn.scalar(
                    text(
                        "SELECT count(*) FROM graph_temporal_scope_revisions WHERE tenant_id = :tid"
                    ),
                    {"tid": tenant},
                )
                assert int(count or 0) == 1

        async with lifecycle_runtime_engine.begin() as conn:
            await conn.execute(text("SELECT set_config('blackbread.tenant_id', '', true)"))
            count = await conn.scalar(text("SELECT count(*) FROM graph_temporal_scope_revisions"))
            assert int(count or 0) == 0

    async def test_downgrade_0005_preserves_0005_behavior(
        self,
        lifecycle_db: str,
        lifecycle_runtime_engine: AsyncEngine,
    ) -> None:
        _run_alembic(lifecycle_db, "downgrade", "base")
        _run_alembic(lifecycle_db, "upgrade", "0006")
        _run_alembic(lifecycle_db, "downgrade", "0005")

        async with _admin_engine(lifecycle_db) as admin:
            eid, event_hash = await _seed_one_attestation(admin, TENANT)

        async with lifecycle_runtime_engine.begin() as conn:
            await _insert_v1_graph(conn, TENANT, eid, event_hash)
            count = await conn.scalar(
                text("SELECT count(*) FROM graph_nodes WHERE tenant_id = :tid"),
                {"tid": TENANT},
            )
            assert int(count or 0) == 1

        other_id = scope_root_id("root_domain", "other.com")
        async with lifecycle_runtime_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('blackbread.tenant_id', :tid, true)"),
                {"tid": TENANT},
            )
            with pytest.raises(IntegrityError, match="graph node is not exactly bound"):
                await conn.execute(
                    text(
                        "INSERT INTO graph_nodes "
                        "(tenant_id, engagement_id, graph_version, node_id, node_family, "
                        "scope_kind, canonical_value, authority, manifest_hash, valid_from, "
                        "valid_until, source_sequence, source_event_hash, source_schema_name, "
                        "source_schema_version) "
                        "VALUES (:tid, :eid, 1, :nid, 'ScopeRoot', 'root_domain', 'other.com', "
                        "'attested_scope', :mh, :vf, :vu, 1, :seh, 'engagement.attested', 1)"
                    ),
                    {
                        "tid": TENANT,
                        "eid": eid,
                        "nid": other_id,
                        "mh": "a" * 64,
                        "vf": FIXED_TIME,
                        "vu": FIXED_TIME + timedelta(days=7),
                        "seh": event_hash,
                    },
                )
