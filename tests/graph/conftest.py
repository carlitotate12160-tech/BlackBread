import asyncio
import hashlib
import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from blackbread.graph.domain import scope_root_id
from blackbread.ledger import EventDraft, EventEnvelope, EventPayload, append_event, to_draft
from blackbread.ledger.catalog import (
    EngagementAttested,
    EngagementMode,
    EngagementScope,
    EngagementStopped,
    default_registry,
)
from blackbread.ledger.event import AgentEvent
from blackbread.ledger.hashing import (
    GENESIS_PREV_HASH,
    HASH_ALGORITHM,
    HASH_VERSION,
    compute_payload_hash,
)
from blackbread.models.core import Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context

FIXED_TIME = datetime(2026, 8, 30, 12, tzinfo=UTC)
SCHEMA_TENANT = "schema-test-tenant"
AttestationFactory = Callable[..., EngagementAttested]
EventFactory = Callable[..., AgentEvent]
AppendPayload = Callable[[AsyncSession, Engagement, EventPayload], Awaitable[AgentEvent]]
AppendDraft = Callable[
    [AsyncSession, Engagement, str, int, dict[str, object]], Awaitable[AgentEvent]
]

TEST_MIGRATION_DATABASE_URL = os.environ.get(
    "BLACKBREAD_TEST_MIGRATION_DATABASE_URL",
    "postgresql+asyncpg://postgres@127.0.0.1:55432/blackbread_test",
)
TEST_RUNTIME_PASSWORD = os.environ.get(
    "BLACKBREAD_TEST_RUNTIME_PASSWORD",
    "blackbread_test_runtime",
)
ROOT = Path(__file__).parents[2]


@dataclass(frozen=True)
class GraphEvents:
    attestation: AttestationFactory
    append: AppendPayload
    draft: AppendDraft
    stopped: EngagementStopped


@pytest.fixture
def attestation_factory() -> AttestationFactory:
    def create(**scope_values: tuple[str, ...]) -> EngagementAttested:
        return EngagementAttested(
            manifest_hash="a" * 64,
            manifest_signature_ref="vault://manifest-signatures/one",
            attested_by="designated-user",
            mode=EngagementMode(
                knowledge="blind",
                execution="covert",
                tier="recon_only",
                pacing="short",
            ),
            scope=EngagementScope(**(scope_values or {"root_domains": ("example.com",)})),
            valid_from=FIXED_TIME,
            expires_at=FIXED_TIME + timedelta(days=7),
        )

    return create


@pytest.fixture
def event_factory() -> EventFactory:
    def create(payload: EventPayload, *, sequence: int = 1) -> AgentEvent:
        data = payload.to_ledger_payload()
        return AgentEvent(
            id=uuid.UUID(int=sequence),
            tenant_id="tenant-a",
            engagement_id=uuid.UUID(int=100),
            sequence=sequence,
            schema_name=payload.SCHEMA_NAME,
            schema_version=payload.SCHEMA_VERSION,
            producer="conductor",
            correlation_id=None,
            causation_id=None,
            occurred_at=FIXED_TIME,
            recorded_at=FIXED_TIME,
            payload=data,
            payload_hash=compute_payload_hash(data),
            prev_event_hash=GENESIS_PREV_HASH,
            event_hash=f"{sequence:064x}",
            hash_algorithm=HASH_ALGORITHM,
            hash_version=HASH_VERSION,
            sensitivity="internal",
            redaction_refs=[],
        )

    return create


@pytest.fixture
def append_payload() -> AppendPayload:
    async def append(
        session: AsyncSession,
        engagement: Engagement,
        payload: EventPayload,
    ) -> AgentEvent:
        await bind_tenant_context(session, TenantContext(engagement.tenant_id))
        event = await append_event(
            session,
            to_draft(
                payload,
                EventEnvelope(
                    tenant_id=engagement.tenant_id,
                    engagement_id=engagement.id,
                    producer="conductor",
                    occurred_at=FIXED_TIME,
                ),
                registry=default_registry(),
            ),
            tenant_context=TenantContext(engagement.tenant_id),
        )
        await session.commit()
        return event

    return append


@pytest.fixture
def append_draft() -> AppendDraft:
    async def append(
        session: AsyncSession,
        engagement: Engagement,
        schema_name: str,
        schema_version: int,
        payload: dict[str, object],
    ) -> AgentEvent:
        await bind_tenant_context(session, TenantContext(engagement.tenant_id))
        event = await append_event(
            session,
            EventDraft(
                tenant_id=engagement.tenant_id,
                engagement_id=engagement.id,
                schema_name=schema_name,
                schema_version=schema_version,
                producer="conductor",
                payload=payload,
                occurred_at=FIXED_TIME,
            ),
            tenant_context=TenantContext(engagement.tenant_id),
        )
        await session.commit()
        return event

    return append


@pytest.fixture
def stopped_event() -> EngagementStopped:
    return EngagementStopped(
        reason="operator_stop",
        stopped_by="operator-one",
        disposition="graceful_stop",
    )


@pytest.fixture
def graph_events(
    attestation_factory: AttestationFactory,
    append_payload: AppendPayload,
    append_draft: AppendDraft,
    stopped_event: EngagementStopped,
) -> GraphEvents:
    return GraphEvents(attestation_factory, append_payload, append_draft, stopped_event)


# ---------------------------------------------------------------------------
# Migration lifecycle isolation fixtures (separate temporary database)
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
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :db AND pid <> pg_backend_pid()"
                    ),
                    {"db": db_name},
                )
                await conn.execute(text(f"DROP DATABASE IF EXISTS {db_name}"))
        finally:
            await admin.dispose()

    asyncio.run(_setup())
    yield db_name
    asyncio.run(_teardown())


def _alembic_env(db_name: str) -> dict[str, str]:
    base_url = make_url(TEST_MIGRATION_DATABASE_URL)
    lifecycle_url = base_url.set(database=db_name)
    env = os.environ.copy()
    env["BLACKBREAD_DATABASE_URL"] = lifecycle_url.render_as_string(hide_password=False)
    return env


def _run_alembic(db_name: str, *args: str) -> None:
    env = _alembic_env(db_name)
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        check=True,
    )


@pytest_asyncio.fixture(scope="module")
async def lifecycle_runtime_engine(lifecycle_db: str) -> AsyncIterator[AsyncEngine]:
    """Runtime-role engine against the lifecycle temporary database."""
    base_url = make_url(TEST_MIGRATION_DATABASE_URL)
    runtime_url = base_url.set(
        database=lifecycle_db,
        username="blackbread_test_runtime",
        password=TEST_RUNTIME_PASSWORD,
    )
    engine = create_async_engine(runtime_url, poolclass=NullPool, pool_pre_ping=False)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def admin_engine(migrated_database: None) -> AsyncEngine:
    engine = create_async_engine(TEST_MIGRATION_DATABASE_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def runtime_engine(engine: AsyncEngine) -> AsyncEngine:
    return engine


async def _seed_engagement(admin: AsyncEngine, tenant_id: str, engagement_id: uuid.UUID) -> None:
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
    if schema_version == 2:
        payload["supersedes_event_hash"] = supersedes_event_hash or ("0" * 64)

    payload_json = json.dumps(payload, sort_keys=True, default=str)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()

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


async def _insert_revision(
    conn: AsyncEngine,
    tenant_id: str,
    eid: uuid.UUID,
    rev: object,
) -> None:
    """Insert a stable root and a temporal revision for a freshly seeded event."""
    node_id = scope_root_id(rev.scope_kind, rev.canonical_value)
    await conn.execute(
        text(
            "INSERT INTO graph_temporal_scope_roots "
            "(tenant_id, engagement_id, node_id, node_family, scope_kind, canonical_value) "
            "VALUES (:tid, :eid, :nid, 'ScopeRoot', :sk, :cv)"
        ),
        {
            "tid": tenant_id,
            "eid": eid,
            "nid": node_id,
            "sk": rev.scope_kind,
            "cv": rev.canonical_value,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO graph_temporal_scope_revisions "
            "(tenant_id, engagement_id, revision_id, node_id, scope_kind, canonical_value, "
            "manifest_hash, valid_from, valid_until, source_sequence, source_event_hash, "
            "source_schema_name, source_schema_version, predecessor_attestation_event_hash) "
            "VALUES (:tid, :eid, :rid, :nid, :sk, :cv, :mh, :vf, :vu, :seq, :eh, :sn, :sv, :pred)"
        ),
        {
            "tid": tenant_id,
            "eid": eid,
            "rid": rev.revision_id,
            "nid": node_id,
            "sk": rev.scope_kind,
            "cv": rev.canonical_value,
            "mh": rev.manifest_hash,
            "vf": rev.valid_from,
            "vu": rev.valid_until,
            "seq": rev.source_sequence,
            "eh": rev.source_event_hash,
            "sn": rev.source_schema_name,
            "sv": rev.source_schema_version,
            "pred": rev.predecessor_attestation_event_hash,
        },
    )
