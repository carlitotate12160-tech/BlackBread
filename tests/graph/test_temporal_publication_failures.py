"""Temporal publication failure, idempotence, and concurrency tests.

Real PostgreSQL. Tests use deterministic barriers, not sleeps.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from blackbread.graph.domain import GraphProjectionError, ScopeProjector
from blackbread.graph.state_root import (
    SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
    compute_temporal_state_root,
)
from blackbread.graph.temporal import validate_temporal_lineage
from blackbread.graph.temporal_persistence import _publish_temporal_publication, _TemporalStore
from blackbread.graph.temporal_publication import TemporalPublication, TemporalPublicationRead
from blackbread.graph.temporal_replay import rebuild_and_publish_temporal_projection
from blackbread.ledger import EventDraft, EventEnvelope, append_event, to_draft
from blackbread.ledger.catalog import (
    EngagementAttested,
    EngagementAttestedV2,
    EngagementMode,
    EngagementScope,
    default_registry,
)
from blackbread.ledger.errors import LedgerAccessError
from blackbread.ledger.event import AgentEvent
from blackbread.models.core import Client, Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context

FIXED_TIME = datetime(2026, 8, 30, 12, tzinfo=UTC)

TENANT = "fail-test-tenant"

_TABLE_EXISTS_QUERIES = {
    "graph_temporal_projection_snapshots": text(
        "SELECT 1 FROM graph_temporal_projection_snapshots "
        "WHERE tenant_id = :tid AND engagement_id = :eid"
    ),
    "graph_temporal_scope_roots": text(
        "SELECT 1 FROM graph_temporal_scope_roots WHERE tenant_id = :tid AND engagement_id = :eid"
    ),
    "graph_temporal_scope_revisions": text(
        "SELECT 1 FROM graph_temporal_scope_revisions "
        "WHERE tenant_id = :tid AND engagement_id = :eid"
    ),
    "graph_temporal_head_nodes": text(
        "SELECT 1 FROM graph_temporal_head_nodes WHERE tenant_id = :tid AND engagement_id = :eid"
    ),
}

_TABLE_COUNT_QUERIES = {
    "graph_temporal_projection_snapshots": text(
        "SELECT COUNT(*) FROM graph_temporal_projection_snapshots WHERE tenant_id = :tid"
    ),
    "graph_temporal_scope_roots": text(
        "SELECT COUNT(*) FROM graph_temporal_scope_roots WHERE tenant_id = :tid"
    ),
    "graph_temporal_scope_revisions": text(
        "SELECT COUNT(*) FROM graph_temporal_scope_revisions WHERE tenant_id = :tid"
    ),
    "graph_temporal_head_nodes": text(
        "SELECT COUNT(*) FROM graph_temporal_head_nodes WHERE tenant_id = :tid"
    ),
}


def _mode() -> EngagementMode:
    return EngagementMode(knowledge="blind", execution="covert", tier="recon_only", pacing="short")


def _attestation(**scope: tuple[str, ...]) -> EngagementAttested:
    return EngagementAttested(
        manifest_hash="a" * 64,
        manifest_signature_ref="vault://test",
        attested_by="tester",
        mode=_mode(),
        scope=EngagementScope(**(scope or {"root_domains": ("example.com",)})),
        valid_from=FIXED_TIME,
        expires_at=FIXED_TIME + timedelta(days=7),
    )


def _v2_attestation(supersedes: str, **scope: tuple[str, ...]) -> EngagementAttestedV2:
    return EngagementAttestedV2(
        manifest_hash="b" * 64,
        manifest_signature_ref="vault://test2",
        attested_by="tester",
        mode=_mode(),
        scope=EngagementScope(**(scope or {"root_domains": ("example.com",)})),
        valid_from=FIXED_TIME + timedelta(days=1),
        expires_at=FIXED_TIME + timedelta(days=14),
        supersedes_event_hash=supersedes,
    )


@pytest_asyncio.fixture
async def fail_engagement(session: AsyncSession) -> Engagement:
    await bind_tenant_context(session, TenantContext(TENANT))
    client = Client(name="acme", tenant_id=TENANT)
    session.add(client)
    await session.flush()
    engagement = Engagement(client_id=client.id, tenant_id=TENANT, status="created")
    session.add(engagement)
    await session.flush()
    await session.commit()
    return engagement


async def _published(
    engine: AsyncEngine,
    fail_engagement: Engagement,
) -> TemporalPublication:
    result = await rebuild_and_publish_temporal_projection(
        engine,
        tenant_id=fail_engagement.tenant_id,
        engagement_id=fail_engagement.id,
    )
    assert result.is_current is True
    return result.publication


async def _build_publication(event: AgentEvent, engagement: Engagement) -> TemporalPublication:
    projector = ScopeProjector()
    projector.consume(event)
    lineage = validate_temporal_lineage(
        projector.revisions, lineage_head_hash=projector.lineage_head_hash
    )
    return TemporalPublication(
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        verified_event_count=event.sequence,
        verified_head_hash=event.event_hash,
        lineage=lineage,
        state_root=compute_temporal_state_root(engagement.tenant_id, engagement.id, lineage),
        versions=SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
    )


class TestAnchorFailures:
    async def test_candidate_exceeds_live_anchor(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _attestation()
        await append_payload(session, fail_engagement, att)

        pub = await _published(engine, fail_engagement)
        forged = replace(pub, verified_event_count=999)
        with pytest.raises(GraphProjectionError, match="exceeds live"):
            await _publish_temporal_publication(engine, forged)

    async def test_same_count_different_hash(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _attestation()
        await append_payload(session, fail_engagement, att)

        pub = await _published(engine, fail_engagement)
        forged = replace(pub, verified_head_hash="f" * 64)
        with pytest.raises(GraphProjectionError, match="diverges"):
            await _publish_temporal_publication(engine, forged)

    async def test_anchor_regression(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _attestation()
        v1_event = await append_payload(session, fail_engagement, att)

        pub = await _published(engine, fail_engagement)

        v2 = _v2_attestation(v1_event.event_hash, root_domains=("example.com",))
        await append_payload(session, fail_engagement, v2)
        await _published(engine, fail_engagement)

        with pytest.raises(GraphProjectionError, match="regression"):
            await _publish_temporal_publication(engine, pub)


class TestDivergenceFailures:
    async def test_same_anchor_divergent_state_root(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _attestation()
        await append_payload(session, fail_engagement, att)

        await _published(engine, fail_engagement)

        pub = await _published(engine, fail_engagement)
        forged = replace(pub, state_root="e" * 64)
        with pytest.raises(GraphProjectionError, match="state root"):
            await _publish_temporal_publication(engine, forged)

    async def test_immutable_history_mismatch_fails_closed(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
        admin_session: AsyncSession,
    ) -> None:
        att = _attestation(root_domains=("example.com",))
        await append_payload(session, fail_engagement, att)

        pub = await _published(engine, fail_engagement)

        await bind_tenant_context(admin_session, TenantContext(TENANT))
        await admin_session.execute(
            text(
                "UPDATE graph_temporal_scope_revisions "
                "SET manifest_hash = :mh "
                "WHERE tenant_id = :tid AND engagement_id = :eid"
            ),
            {"mh": "b" * 64, "tid": TENANT, "eid": fail_engagement.id},
        )
        await admin_session.commit()

        with pytest.raises(GraphProjectionError, match="rewrites persisted revision"):
            await _publish_temporal_publication(engine, pub)


class TestUnsupportedEvents:
    async def test_unsupported_schema_writes_nothing(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        engine: AsyncEngine,
    ) -> None:
        """Unsupported event schema raises during replay, no publication written."""
        draft = EventDraft(
            tenant_id=fail_engagement.tenant_id,
            engagement_id=fail_engagement.id,
            schema_name="unsupported.event",
            schema_version=1,
            producer="conductor",
            payload={"data": "test"},
            occurred_at=FIXED_TIME,
        )
        await bind_tenant_context(session, TenantContext(fail_engagement.tenant_id))
        await append_event(session, draft, tenant_context=TenantContext(fail_engagement.tenant_id))
        await session.commit()

        with pytest.raises(GraphProjectionError):
            await rebuild_and_publish_temporal_projection(
                engine,
                tenant_id=fail_engagement.tenant_id,
                engagement_id=fail_engagement.id,
            )

        # Verify nothing was published
        async with engine.connect() as conn:
            await conn.execute(text(f"SET blackbread.tenant_id = '{fail_engagement.tenant_id}'"))
            for table, query in _TABLE_EXISTS_QUERIES.items():
                result = await conn.execute(
                    query, {"tid": fail_engagement.tenant_id, "eid": fail_engagement.id}
                )
                assert result.one_or_none() is None, f"partial data in {table}"


class TestConcurrency:
    async def test_concurrent_publishers_serialized(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        """Two concurrent publishers are serialized by the FOR UPDATE lock."""
        att = _attestation()
        await append_payload(session, fail_engagement, att)

        first_acquired = asyncio.Event()
        second_waiting = asyncio.Event()
        proceed = asyncio.Event()

        original = _TemporalStore.lock_anchor

        async def instrumented(self: _TemporalStore) -> tuple[int, str]:
            first_acquired.set()
            second_waiting.set()
            await proceed.wait()
            return await original(self)

        with mock.patch.object(_TemporalStore, "lock_anchor", instrumented):
            tasks = [
                asyncio.create_task(
                    rebuild_and_publish_temporal_projection(
                        engine,
                        tenant_id=fail_engagement.tenant_id,
                        engagement_id=fail_engagement.id,
                    )
                )
                for _ in range(2)
            ]
            await first_acquired.wait()
            await second_waiting.wait()
            proceed.set()
            results = await asyncio.gather(*tasks)

        assert all(isinstance(r, TemporalPublicationRead) for r in results)
        assert results[0].publication == results[1].publication
        assert results[0].is_current is True
        assert results[1].is_current is True

        async with engine.connect() as conn:
            await conn.execute(text(f"SET blackbread.tenant_id = '{fail_engagement.tenant_id}'"))
            snap = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM graph_temporal_projection_snapshots "
                        "WHERE tenant_id = :tid AND engagement_id = :eid"
                    ),
                    {"tid": fail_engagement.tenant_id, "eid": fail_engagement.id},
                )
            ).one_or_none()
            assert snap is not None


class TestRollbackCleanup:
    async def test_constraint_failure_no_partial_publication(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        """If publication fails mid-transaction, no partial data is left."""
        att = _attestation()
        event = await append_payload(session, fail_engagement, att)

        pub = await _build_publication(event, fail_engagement)
        forged = replace(pub, verified_event_count=999)
        with pytest.raises(GraphProjectionError):
            await _publish_temporal_publication(engine, forged)

        # Verify no partial data exists
        async with engine.connect() as conn:
            await conn.execute(text(f"SET blackbread.tenant_id = '{fail_engagement.tenant_id}'"))
            for table, query in _TABLE_EXISTS_QUERIES.items():
                result = await conn.execute(
                    query, {"tid": fail_engagement.tenant_id, "eid": fail_engagement.id}
                )
                assert result.one_or_none() is None, f"partial data in {table}"

    async def test_pool_connection_returned_after_failure(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        """Engine pool is not exhausted after a publication failure."""
        att = _attestation()
        event = await append_payload(session, fail_engagement, att)

        pub = await _build_publication(event, fail_engagement)
        forged = replace(pub, verified_event_count=999)

        for _ in range(5):
            with pytest.raises(GraphProjectionError):
                await _publish_temporal_publication(engine, forged)

        # Engine still usable
        async with engine.connect() as conn:
            result = await conn.scalar(text("SELECT 1"))
            assert result == 1

    async def test_wrong_tenant_writes_nothing(
        self,
        session: AsyncSession,
        engine: AsyncEngine,
    ) -> None:
        """Publication with wrong tenant_id fails and writes nothing."""
        correct_tenant = "correct-tenant"
        await bind_tenant_context(session, TenantContext(correct_tenant))
        client = Client(name="acme", tenant_id=correct_tenant)
        session.add(client)
        await session.flush()
        engagement = Engagement(
            client_id=client.id,
            tenant_id=correct_tenant,
            status="created",
        )
        session.add(engagement)
        await session.flush()
        await session.commit()

        att = _attestation()
        await bind_tenant_context(session, TenantContext(correct_tenant))
        await append_event(
            session,
            to_draft(
                att,
                EventEnvelope(
                    tenant_id=correct_tenant,
                    engagement_id=engagement.id,
                    producer="conductor",
                    occurred_at=FIXED_TIME,
                ),
                registry=default_registry(),
            ),
            tenant_context=TenantContext(correct_tenant),
        )
        await session.commit()

        result = await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=correct_tenant,
            engagement_id=engagement.id,
        )
        pub = result.publication
        wrong_state_root = compute_temporal_state_root(
            "wrong-tenant",
            engagement.id,
            pub.lineage,
        )
        forged = replace(
            pub,
            tenant_id="wrong-tenant",
            state_root=wrong_state_root,
        )

        with pytest.raises(LedgerAccessError, match="engagement unavailable"):
            await _publish_temporal_publication(engine, forged)

        # Nothing was written for the wrong tenant
        async with engine.connect() as conn:
            await conn.execute(text(f"SET blackbread.tenant_id = '{correct_tenant}'"))
            for table, query in _TABLE_COUNT_QUERIES.items():
                count = await conn.scalar(query, {"tid": "wrong-tenant"})
                assert count == 0, f"wrong-tenant data in {table}"
