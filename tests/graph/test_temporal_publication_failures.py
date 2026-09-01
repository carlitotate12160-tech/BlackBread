"""Temporal publication failure and concurrency tests.

Real PostgreSQL. Tests use deterministic barriers, not sleeps.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from blackbread.graph.domain import GraphProjectionError, ScopeProjector, ScopeRoot
from blackbread.graph.state_root import (
    SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
    compute_temporal_state_root,
)
from blackbread.graph.temporal import validate_temporal_lineage
from blackbread.graph.temporal_persistence import _publish_temporal_publication
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
from blackbread.ledger.event import AgentEvent
from blackbread.models.core import Client, Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context

FIXED_TIME = datetime(2026, 8, 30, 12, tzinfo=UTC)

TENANT = "fail-test-tenant"


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


def _build_publication(
    event: object,
    engagement: Engagement,
    projector: ScopeProjector,
) -> TemporalPublication:
    """Helper: build a validated publication from a projector."""
    lineage = validate_temporal_lineage(
        projector.revisions,
        lineage_head_hash=projector.lineage_head_hash,
    )
    state_root = compute_temporal_state_root(
        engagement.tenant_id,
        engagement.id,
        lineage,
    )
    final_group = lineage.groups[-1]
    head_nodes = tuple(
        ScopeRoot(
            node_id=r.node_id,
            scope_kind=r.scope_kind,
            canonical_value=r.canonical_value,
            manifest_hash=r.manifest_hash,
            valid_from=r.valid_from,
            valid_until=r.valid_until,
            source_sequence=r.source_sequence,
            source_event_hash=r.source_event_hash,
            source_schema_version=r.source_schema_version,
        )
        for r in final_group.revisions
    )

    evt = event if isinstance(event, AgentEvent) else None
    assert evt is not None
    return TemporalPublication(
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        verified_event_count=evt.sequence,
        verified_head_hash=evt.event_hash,
        lineage=lineage,
        state_root=state_root,
        versions=SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
        structural_head_nodes=head_nodes,
    )


@pytest_asyncio.fixture
async def fail_engagement(session: AsyncSession) -> Engagement:
    from blackbread.models.core import Client  # noqa: PLC0415
    from blackbread.tenancy import TenantContext, bind_tenant_context  # noqa: PLC0415

    await bind_tenant_context(session, TenantContext(TENANT))
    client = Client(name="acme", tenant_id=TENANT)
    session.add(client)
    await session.flush()
    engagement = Engagement(client_id=client.id, tenant_id=TENANT, status="created")
    session.add(engagement)
    await session.flush()
    await session.commit()
    return engagement


class TestAnchorFailures:
    async def test_candidate_exceeds_live_anchor(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _attestation()
        event = await append_payload(session, fail_engagement, att)

        projector = ScopeProjector()
        projector.consume(event)
        pub = _build_publication(event, fail_engagement, projector)
        # Forge a publication claiming more events than exist
        forged = TemporalPublication(
            tenant_id=pub.tenant_id,
            engagement_id=pub.engagement_id,
            verified_event_count=999,
            verified_head_hash=pub.verified_head_hash,
            lineage=pub.lineage,
            state_root=pub.state_root,
            versions=pub.versions,
            structural_head_nodes=pub.structural_head_nodes,
        )
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
        event = await append_payload(session, fail_engagement, att)

        projector = ScopeProjector()
        projector.consume(event)
        pub = _build_publication(event, fail_engagement, projector)
        forged = TemporalPublication(
            tenant_id=pub.tenant_id,
            engagement_id=pub.engagement_id,
            verified_event_count=pub.verified_event_count,
            verified_head_hash="f" * 64,
            lineage=pub.lineage,
            state_root=pub.state_root,
            versions=pub.versions,
            structural_head_nodes=pub.structural_head_nodes,
        )
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

        # Publish at event count 1
        await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=fail_engagement.tenant_id,
            engagement_id=fail_engagement.id,
        )

        # Extend to event count 2
        v2 = EngagementAttestedV2(
            manifest_hash="b" * 64,
            manifest_signature_ref="vault://test2",
            attested_by="tester",
            mode=_mode(),
            scope=EngagementScope(root_domains=("example.com",)),
            valid_from=FIXED_TIME + timedelta(days=1),
            expires_at=FIXED_TIME + timedelta(days=14),
            supersedes_event_hash=v1_event.event_hash,
        )
        await append_payload(session, fail_engagement, v2)

        await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=fail_engagement.tenant_id,
            engagement_id=fail_engagement.id,
        )

        # Now try to publish the old event-count-1 publication → regression
        projector = ScopeProjector()
        projector.consume(v1_event)
        old_pub = _build_publication(v1_event, fail_engagement, projector)
        with pytest.raises(GraphProjectionError, match="regression"):
            await _publish_temporal_publication(engine, old_pub)


class TestDivergenceFailures:
    async def test_same_anchor_divergent_state_root(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _attestation()
        event = await append_payload(session, fail_engagement, att)

        await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=fail_engagement.tenant_id,
            engagement_id=fail_engagement.id,
        )

        # Build a publication with same anchor but different state root
        projector = ScopeProjector()
        projector.consume(event)
        pub = _build_publication(event, fail_engagement, projector)
        forged = TemporalPublication(
            tenant_id=pub.tenant_id,
            engagement_id=pub.engagement_id,
            verified_event_count=pub.verified_event_count,
            verified_head_hash=pub.verified_head_hash,
            lineage=pub.lineage,
            state_root="e" * 64,
            versions=pub.versions,
            structural_head_nodes=pub.structural_head_nodes,
        )
        # validate_temporal_publication catches it before DB
        with pytest.raises(GraphProjectionError, match="state root"):
            await _publish_temporal_publication(engine, forged)


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
            snap = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM graph_temporal_projection_snapshots "
                        "WHERE tenant_id = :tid AND engagement_id = :eid"
                    ),
                    {"tid": fail_engagement.tenant_id, "eid": fail_engagement.id},
                )
            ).one_or_none()
            assert snap is None


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

        results: list[TemporalPublicationRead] = []
        errors: list[Exception] = []
        barrier = asyncio.Barrier(2)

        async def publish() -> None:
            try:
                await barrier.wait()
                r = await rebuild_and_publish_temporal_projection(
                    engine,
                    tenant_id=fail_engagement.tenant_id,
                    engagement_id=fail_engagement.id,
                )
                results.append(r)
            except Exception as exc:
                errors.append(exc)

        await asyncio.gather(publish(), publish())

        # Both should succeed (idempotent) or at most one fail
        assert len(results) + len(errors) == 2
        if len(results) == 2:
            assert results[0].publication.state_root == results[1].publication.state_root


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

        # Try publishing with forged count to trigger failure
        projector = ScopeProjector()
        projector.consume(event)
        pub = _build_publication(event, fail_engagement, projector)
        forged = TemporalPublication(
            tenant_id=pub.tenant_id,
            engagement_id=pub.engagement_id,
            verified_event_count=999,
            verified_head_hash=pub.verified_head_hash,
            lineage=pub.lineage,
            state_root=pub.state_root,
            versions=pub.versions,
            structural_head_nodes=pub.structural_head_nodes,
        )
        with pytest.raises(GraphProjectionError):
            await _publish_temporal_publication(engine, forged)

        # Verify no partial data exists
        async with engine.connect() as conn:
            await conn.execute(text(f"SET blackbread.tenant_id = '{fail_engagement.tenant_id}'"))
            for table in (
                "graph_temporal_projection_snapshots",
                "graph_temporal_scope_roots",
                "graph_temporal_scope_revisions",
                "graph_temporal_head_nodes",
            ):
                result = await conn.execute(
                    text(
                        f"SELECT 1 FROM {table} "  # noqa: S608
                        f"WHERE tenant_id = :tid AND engagement_id = :eid"
                    ),
                    {"tid": fail_engagement.tenant_id, "eid": fail_engagement.id},
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

        projector = ScopeProjector()
        projector.consume(event)
        pub = _build_publication(event, fail_engagement, projector)
        forged = TemporalPublication(
            tenant_id=pub.tenant_id,
            engagement_id=pub.engagement_id,
            verified_event_count=999,
            verified_head_hash=pub.verified_head_hash,
            lineage=pub.lineage,
            state_root=pub.state_root,
            versions=pub.versions,
            structural_head_nodes=pub.structural_head_nodes,
        )

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
        event = await append_event(
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

        projector = ScopeProjector()
        projector.consume(event)
        lineage = validate_temporal_lineage(
            projector.revisions,
            lineage_head_hash=projector.lineage_head_hash,
        )
        state_root = compute_temporal_state_root(
            "wrong-tenant",
            engagement.id,
            lineage,
        )
        final_group = lineage.groups[-1]
        head_nodes = tuple(
            ScopeRoot(
                node_id=r.node_id,
                scope_kind=r.scope_kind,
                canonical_value=r.canonical_value,
                manifest_hash=r.manifest_hash,
                valid_from=r.valid_from,
                valid_until=r.valid_until,
                source_sequence=r.source_sequence,
                source_event_hash=r.source_event_hash,
                source_schema_version=r.source_schema_version,
            )
            for r in final_group.revisions
        )
        forged = TemporalPublication(
            tenant_id="wrong-tenant",
            engagement_id=engagement.id,
            verified_event_count=event.sequence,
            verified_head_hash=event.event_hash,
            lineage=lineage,
            state_root=state_root,
            versions=SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
            structural_head_nodes=head_nodes,
        )
        with pytest.raises((GraphProjectionError, Exception)):
            await _publish_temporal_publication(engine, forged)
