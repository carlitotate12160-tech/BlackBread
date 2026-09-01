"""Migration 0006 schema, RLS, privilege, trigger, and constraint tests.

Uses real PostgreSQL. Migration lifecycle tests use a separate temporary database.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

TEST_MIGRATION_DATABASE_URL = os.environ.get(
    "BLACKBREAD_TEST_MIGRATION_DATABASE_URL",
    "postgresql+asyncpg://postgres@127.0.0.1:55432/blackbread_test",
)
TEST_RUNTIME_PASSWORD = os.environ.get(
    "BLACKBREAD_TEST_RUNTIME_PASSWORD",
    "blackbread_test_runtime",
)

ROOT = Path(__file__).parents[2]
FIXED_TIME = datetime(2026, 8, 30, 12, tzinfo=UTC)
TENANT = "schema-test-tenant"


# ---------------------------------------------------------------------------
# Migration lifecycle isolation fixture (separate temporary database)
# ---------------------------------------------------------------------------

def _temp_db_name() -> str:
    return f"blackbread_test_migration_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def lifecycle_db() -> Iterator[str]:
    """Create a separate temporary PostgreSQL database for lifecycle tests."""
    db_name = _temp_db_name()

    async def _setup() -> None:
        admin = create_async_engine(TEST_MIGRATION_DATABASE_URL, isolation_level="AUTOCOMMIT")
        try:
            async with admin.connect() as conn:
                await conn.execute(text(f"CREATE DATABASE {db_name}"))
        finally:
            await admin.dispose()

    async def _teardown() -> None:
        admin = create_async_engine(TEST_MIGRATION_DATABASE_URL, isolation_level="AUTOCOMMIT")
        try:
            async with admin.connect() as conn:
                await conn.execute(
                    text(
                        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "  # noqa: S608
                        f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid()"
                    )
                )
                await conn.execute(text(f"DROP DATABASE IF EXISTS {db_name}"))
        finally:
            await admin.dispose()

    asyncio.run(_setup())
    yield db_name
    asyncio.run(_teardown())


def _alembic_env(db_name: str) -> dict[str, str]:
    from sqlalchemy.engine import make_url  # noqa: PLC0415

    base_url = make_url(TEST_MIGRATION_DATABASE_URL)
    lifecycle_url = base_url.set(database=db_name)
    env = os.environ.copy()
    env["BLACKBREAD_DATABASE_URL"] = str(lifecycle_url)
    return env


def _run_alembic(db_name: str, *args: str) -> None:
    env = _alembic_env(db_name)
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        check=True,
    )


@pytest.fixture(scope="module")
def lifecycle_runtime_engine(lifecycle_db: str) -> Iterator[AsyncEngine]:
    """Runtime-role engine against the lifecycle temporary database."""
    from sqlalchemy.engine import make_url  # noqa: PLC0415

    base_url = make_url(TEST_MIGRATION_DATABASE_URL)
    runtime_url = base_url.set(
        database=lifecycle_db,
        username="blackbread_test_runtime",
        password=TEST_RUNTIME_PASSWORD,
    )
    engine = create_async_engine(str(runtime_url), pool_pre_ping=True)

    async def _dispose() -> None:
        await engine.dispose()

    yield engine
    asyncio.run(_dispose())


# ---------------------------------------------------------------------------
# Shared schema-test fixtures (uses the session migrated_database)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def admin_engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_MIGRATION_DATABASE_URL, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def runtime_engine(engine: AsyncEngine) -> AsyncEngine:
    return engine


async def _seed_engagement(
    admin: AsyncEngine, tenant_id: str, engagement_id: uuid.UUID,
) -> None:
    """Insert a client + engagement for testing via the admin connection."""
    client_id = uuid.uuid4()
    async with admin.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO clients (id, name, tenant_id) VALUES (:id, :name, :tid) "
                "ON CONFLICT DO NOTHING"
            ),
            {"id": client_id, "name": "test-client", "tid": tenant_id},
        )
        await conn.execute(
            text(
                "INSERT INTO engagements (id, client_id, tenant_id) "
                "VALUES (:id, :cid, :tid) ON CONFLICT DO NOTHING"
            ),
            {"id": engagement_id, "cid": client_id, "tid": tenant_id},
        )


async def _seed_attestation_event(  # noqa: PLR0913
    admin: AsyncEngine,
    tenant_id: str,
    engagement_id: uuid.UUID,
    *,
    sequence: int = 1,
    schema_version: int = 1,
    manifest_hash: str | None = None,
    valid_from: datetime | None = None,
    expires_at: datetime | None = None,
    scope: dict[str, object] | None = None,
    supersedes_event_hash: str | None = None,
) -> str:
    """Insert a raw attestation event and return its event_hash.

    Uses raw SQL and hashlib. Schema tests verify DDL constraints,
    not ledger chain integrity, so we don't need SealedEvent hashing.
    """
    import hashlib  # noqa: PLC0415
    import json  # noqa: PLC0415

    manifest = manifest_hash or ("a" * 64)
    vf = valid_from or FIXED_TIME
    ea = expires_at or (FIXED_TIME + timedelta(days=7))
    scope_data = scope or {"root_domains": ["example.com"]}

    payload: dict[str, object] = {
        "manifest_hash": manifest,
        "manifest_signature_ref": "vault://test",
        "attested_by": "tester",
        "mode": {
            "knowledge": "blind",
            "execution": "covert",
            "tier": "recon_only",
            "pacing": "short",
        },
        "scope": scope_data,
        "valid_from": vf.isoformat(),
        "expires_at": ea.isoformat(),
    }

    payload_json = json.dumps(payload, sort_keys=True, default=str)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()

    # For schema tests, use deterministic synthetic hashes unique per call
    prev_hash = "0" * 64
    nonce = uuid.uuid4().hex
    preimage = f"{prev_hash}:{payload_hash}:{engagement_id}:{nonce}:{sequence}"
    event_hash = hashlib.sha256(preimage.encode()).hexdigest()

    event_id = uuid.uuid4()
    async with admin.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO agent_events "
                "(id, engagement_id, tenant_id, sequence, schema_name, schema_version, "
                "producer, occurred_at, recorded_at, payload, payload_hash, "
                "prev_event_hash, event_hash) "
                "VALUES (:id, :eid, :tid, :seq, :sn, :sv, :prod, :oa, :ra, "
                "CAST(:payload AS jsonb), :ph, :pe, :eh)"
            ),
            {
                "id": event_id,
                "eid": engagement_id,
                "tid": tenant_id,
                "seq": sequence,
                "sn": "engagement.attested",
                "sv": schema_version,
                "prod": "conductor",
                "oa": FIXED_TIME,
                "ra": FIXED_TIME,
                "payload": payload_json,
                "ph": payload_hash,
                "pe": prev_hash,
                "eh": event_hash,
            },
        )
    return event_hash


# ---------------------------------------------------------------------------
# Migration lifecycle tests
# ---------------------------------------------------------------------------

class TestDeferredFK:
    async def test_snapshot_head_deferred_fk_accepted(
        self, admin_engine: AsyncEngine, runtime_engine: AsyncEngine,
    ) -> None:
        """Head nodes can be inserted in a deferred transaction with snapshot."""
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)
        event_hash = await _seed_attestation_event(admin_engine, TENANT, eid)

        from blackbread.graph.domain import scope_root_id  # noqa: PLC0415
        from blackbread.graph.revision import ScopeRevision  # noqa: PLC0415

        node_id = scope_root_id("root_domain", "example.com")
        rev = ScopeRevision(
            node_id=node_id, scope_kind="root_domain", canonical_value="example.com",
            manifest_hash="a" * 64, valid_from=FIXED_TIME,
            valid_until=FIXED_TIME + timedelta(days=7),
            source_sequence=1, source_event_hash=event_hash,
            source_schema_name="engagement.attested", source_schema_version=1,
            predecessor_attestation_event_hash=None,
        )

        async with runtime_engine.connect() as conn:
            await conn.execute(text(f"SET blackbread.tenant_id = '{TENANT}'"))
            await conn.execute(
                text("SET CONSTRAINTS fk_graph_temporal_head_lineage DEFERRED")
            )
            # Insert root
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_scope_roots "
                    "(tenant_id, engagement_id, node_id, node_family, "
                    "scope_kind, canonical_value) "
                    "VALUES (:tid, :eid, :nid, 'ScopeRoot', 'root_domain', 'example.com')"
                ),
                {"tid": TENANT, "eid": eid, "nid": node_id},
            )
            # Insert revision
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_scope_revisions "
                    "(tenant_id, engagement_id, revision_id, node_id, scope_kind, "
                    "canonical_value, manifest_hash, valid_from, valid_until, "
                    "source_sequence, source_event_hash, source_schema_name, "
                    "source_schema_version, predecessor_attestation_event_hash) "
                    "VALUES (:tid, :eid, :rid, :nid, 'root_domain', 'example.com', "
                    ":mh, :vf, :vu, 1, :eh, 'engagement.attested', 1, NULL)"
                ),
                {
                    "tid": TENANT, "eid": eid, "rid": rev.revision_id,
                    "nid": node_id, "mh": "a" * 64,
                    "vf": FIXED_TIME, "vu": FIXED_TIME + timedelta(days=7),
                    "eh": event_hash,
                },
            )
            # Insert snapshot
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_projection_snapshots "
                    "(tenant_id, engagement_id, verified_event_count, verified_head_hash, "
                    "ledger_hash_algorithm, ledger_hash_version, temporal_projector_version, "
                    "state_root_version, scope_canonicalization_version, state_root, "
                    "lineage_head_hash, lineage_head_sequence) "
                    "VALUES (:tid, :eid, 1, :eh, 'sha256', 1, 2, 2, 1, :sr, :eh, 1)"
                ),
                {"tid": TENANT, "eid": eid, "eh": event_hash, "sr": "b" * 64},
            )
            # Insert head node
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_head_nodes "
                    "(tenant_id, engagement_id, node_id, revision_id, source_event_hash) "
                    "VALUES (:tid, :eid, :nid, :rid, :seh)"
                ),
                {
                    "tid": TENANT, "eid": eid,
                    "nid": node_id, "rid": rev.revision_id,
                    "seh": event_hash,
                },
            )
            # Force immediate before commit
            await conn.execute(
                text("SET CONSTRAINTS fk_graph_temporal_head_lineage IMMEDIATE")
            )
            # commit succeeded — deferred FK passed

    async def test_head_wrong_source_rejected(
        self, admin_engine: AsyncEngine, runtime_engine: AsyncEngine,
    ) -> None:
        """Head node with wrong source_event_hash is rejected at commit."""
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)
        event_hash = await _seed_attestation_event(admin_engine, TENANT, eid)

        from blackbread.graph.domain import scope_root_id  # noqa: PLC0415
        from blackbread.graph.revision import ScopeRevision  # noqa: PLC0415

        node_id = scope_root_id("root_domain", "example.com")
        rev = ScopeRevision(
            node_id=node_id, scope_kind="root_domain", canonical_value="example.com",
            manifest_hash="a" * 64, valid_from=FIXED_TIME,
            valid_until=FIXED_TIME + timedelta(days=7),
            source_sequence=1, source_event_hash=event_hash,
            source_schema_name="engagement.attested", source_schema_version=1,
            predecessor_attestation_event_hash=None,
        )

        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_scope_roots "
                    "(tenant_id, engagement_id, node_id, node_family, "
                    "scope_kind, canonical_value) "
                    "VALUES (:tid, :eid, :nid, 'ScopeRoot', 'root_domain', 'example.com')"
                ),
                {"tid": TENANT, "eid": eid, "nid": node_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_scope_revisions "
                    "(tenant_id, engagement_id, revision_id, node_id, scope_kind, "
                    "canonical_value, manifest_hash, valid_from, valid_until, "
                    "source_sequence, source_event_hash, source_schema_name, "
                    "source_schema_version, predecessor_attestation_event_hash) "
                    "VALUES (:tid, :eid, :rid, :nid, 'root_domain', 'example.com', "
                    ":mh, :vf, :vu, 1, :eh, 'engagement.attested', 1, NULL)"
                ),
                {
                    "tid": TENANT, "eid": eid, "rid": rev.revision_id,
                    "nid": node_id, "mh": "a" * 64,
                    "vf": FIXED_TIME, "vu": FIXED_TIME + timedelta(days=7),
                    "eh": event_hash,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_projection_snapshots "
                    "(tenant_id, engagement_id, verified_event_count, verified_head_hash, "
                    "ledger_hash_algorithm, ledger_hash_version, temporal_projector_version, "
                    "state_root_version, scope_canonicalization_version, state_root, "
                    "lineage_head_hash, lineage_head_sequence) "
                    "VALUES (:tid, :eid, 1, :eh, 'sha256', 1, 2, 2, 1, :sr, :eh, 1)"
                ),
                {"tid": TENANT, "eid": eid, "eh": event_hash, "sr": "b" * 64},
            )

        # Try to insert head with wrong source_event_hash
        async with runtime_engine.connect() as conn:
            await conn.execute(text(f"SET blackbread.tenant_id = '{TENANT}'"))
            with pytest.raises(Exception):  # noqa: B017
                await conn.execute(
                    text("SET CONSTRAINTS fk_graph_temporal_head_lineage DEFERRED")
                )
                wrong_hash = "f" * 64
                await conn.execute(
                    text(
                        "INSERT INTO graph_temporal_head_nodes "
                        "(tenant_id, engagement_id, node_id, revision_id, source_event_hash) "
                        "VALUES (:tid, :eid, :nid, :rid, :seh)"
                    ),
                    {
                        "tid": TENANT, "eid": eid,
                        "nid": node_id, "rid": rev.revision_id,
                        "seh": wrong_hash,
                    },
                )
                await conn.execute(
                    text("SET CONSTRAINTS fk_graph_temporal_head_lineage IMMEDIATE")
                )
