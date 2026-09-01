"""Normal temporal publication integration tests.

Real PostgreSQL. Tests use the rebuild_and_publish_temporal_projection entry point.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from blackbread.graph.domain import GraphProjectionError, ScopeProjector, scope_root_id
from blackbread.graph.state_root import SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS
from blackbread.graph.temporal import validate_temporal_lineage
from blackbread.graph.temporal_persistence import _publish_temporal_publication
from blackbread.graph.temporal_publication import (
    TemporalPublication,
    TemporalPublicationRead,
    validate_temporal_publication,
)
from blackbread.graph.temporal_replay import (
    rebuild_and_publish_temporal_projection,
    rebuild_temporal_projection,
)
from blackbread.ledger.catalog import (
    EngagementAttested,
    EngagementAttestedV2,
    EngagementMode,
    EngagementScope,
    EngagementStopped,
)
from blackbread.models.core import Client, Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context

FIXED_TIME = datetime(2026, 8, 30, 12, tzinfo=UTC)

TENANT = "pub-test-tenant"


def _mode() -> EngagementMode:
    return EngagementMode(knowledge="blind", execution="covert", tier="recon_only", pacing="short")


def _v1_attestation(**scope: tuple[str, ...]) -> EngagementAttested:
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
async def pub_engagement(session: AsyncSession) -> Engagement:
    await bind_tenant_context(session, TenantContext(TENANT))
    client = Client(name="acme", tenant_id=TENANT)
    session.add(client)
    await session.flush()
    engagement = Engagement(client_id=client.id, tenant_id=TENANT, status="created")
    session.add(engagement)
    await session.flush()
    await session.commit()
    return engagement


class TestPublicationContract:
    async def test_validate_rejects_non_publication(self) -> None:
        with pytest.raises(GraphProjectionError, match="invalid temporal publication"):
            validate_temporal_publication("not a publication")

    async def test_validate_rejects_wrong_state_root(
        self,
        pub_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _v1_attestation()
        event = await append_payload(session, pub_engagement, att)

        projector = ScopeProjector()
        projector.consume(event)
        lineage = validate_temporal_lineage(
            projector.revisions,
            lineage_head_hash=projector.lineage_head_hash,
        )
        pub = TemporalPublication(
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
            verified_event_count=1,
            verified_head_hash=event.event_hash,
            lineage=lineage,
            state_root="f" * 64,  # wrong
            versions=SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
        )
        with pytest.raises(GraphProjectionError, match="state root is inconsistent"):
            validate_temporal_publication(pub)

    async def test_publication_has_no_caller_supplied_structural_head(
        self,
        pub_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        """The contract has no independent caller-supplied structural-head claim."""
        att = _v1_attestation(root_domains=("example.com",))
        await append_payload(session, pub_engagement, att)

        result = await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )
        assert not hasattr(result.publication, "structural_head_nodes")

        final = result.publication.lineage.groups[-1]
        async with engine.connect() as conn:
            await conn.execute(text(f"SET blackbread.tenant_id = '{pub_engagement.tenant_id}'"))
            heads = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM graph_temporal_head_nodes "
                            "WHERE tenant_id = :tid AND engagement_id = :eid"
                        ),
                        {"tid": pub_engagement.tenant_id, "eid": pub_engagement.id},
                    )
                )
                .mappings()
                .all()
            )
        expected = {(h["node_id"], h["revision_id"], h["source_event_hash"]) for h in heads}
        assert expected == {
            (rev.node_id, rev.revision_id, final.source_event_hash) for rev in final.revisions
        }


class TestV1OnlyPublication:
    async def test_first_publication(
        self,
        pub_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _v1_attestation()
        await append_payload(session, pub_engagement, att)

        result = await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )
        assert isinstance(result, TemporalPublicationRead)
        assert result.is_current is True
        pub = result.publication
        assert pub.verified_event_count == 1
        assert pub.tenant_id == pub_engagement.tenant_id
        assert pub.engagement_id == pub_engagement.id

    async def test_snapshot_persisted(
        self,
        pub_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _v1_attestation()
        await append_payload(session, pub_engagement, att)

        result = await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )

        # Verify persisted snapshot
        async with engine.connect() as conn:
            await conn.execute(text(f"SET blackbread.tenant_id = '{pub_engagement.tenant_id}'"))
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM graph_temporal_projection_snapshots "
                            "WHERE tenant_id = :tid AND engagement_id = :eid"
                        ),
                        {"tid": pub_engagement.tenant_id, "eid": pub_engagement.id},
                    )
                )
                .mappings()
                .one()
            )
            assert row["verified_event_count"] == 1
            assert row["verified_head_hash"] == result.publication.verified_head_hash
            assert row["state_root"] == result.publication.state_root
            assert row["temporal_projector_version"] == 2
            assert row["state_root_version"] == 2

    async def test_idempotent_republish(
        self,
        pub_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _v1_attestation()
        await append_payload(session, pub_engagement, att)

        result1 = await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )
        result2 = await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )
        assert result1.publication == result2.publication
        assert result1.is_current is True
        assert result2.is_current is True

    async def test_structural_head_membership(
        self,
        pub_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _v1_attestation(root_domains=("example.com", "test.org"))
        await append_payload(session, pub_engagement, att)

        await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )

        # Verify head nodes in DB
        async with engine.connect() as conn:
            await conn.execute(text(f"SET blackbread.tenant_id = '{pub_engagement.tenant_id}'"))
            heads = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM graph_temporal_head_nodes "
                            "WHERE tenant_id = :tid AND engagement_id = :eid"
                        ),
                        {"tid": pub_engagement.tenant_id, "eid": pub_engagement.id},
                    )
                )
                .mappings()
                .all()
            )
            head_node_ids = {h["node_id"] for h in heads}
            expected_ids = {
                scope_root_id("root_domain", "example.com"),
                scope_root_id("root_domain", "test.org"),
            }
            assert head_node_ids == expected_ids


class TestV1ToV2Publication:
    async def test_v2_extension(
        self,
        pub_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        v1 = _v1_attestation()
        v1_event = await append_payload(session, pub_engagement, v1)

        # Publish first
        result1 = await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )
        assert result1.is_current is True

        # Extend with v2
        v2 = _v2_attestation(
            v1_event.event_hash,
            root_domains=("added.org", "example.com"),
        )
        await append_payload(session, pub_engagement, v2)

        result2 = await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )
        assert result2.is_current is True
        assert result2.publication.verified_event_count == 2
        assert result2.publication.state_root != result1.publication.state_root

    async def test_v2_scope_removal(
        self,
        pub_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        v1 = _v1_attestation(root_domains=("example.com", "old.org"))
        v1_event = await append_payload(session, pub_engagement, v1)

        await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )

        v2 = _v2_attestation(v1_event.event_hash, root_domains=("example.com",))
        await append_payload(session, pub_engagement, v2)

        result2 = await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )
        assert result2.is_current is True

        # Verify old.org stable root still exists, but head only has example.com
        async with engine.connect() as conn:
            await conn.execute(text(f"SET blackbread.tenant_id = '{pub_engagement.tenant_id}'"))
            roots = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM graph_temporal_scope_roots "
                            "WHERE tenant_id = :tid AND engagement_id = :eid"
                        ),
                        {"tid": pub_engagement.tenant_id, "eid": pub_engagement.id},
                    )
                )
                .mappings()
                .all()
            )
            root_values = {r["canonical_value"] for r in roots}
            assert root_values == {"example.com", "old.org"}

            heads = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM graph_temporal_head_nodes "
                            "WHERE tenant_id = :tid AND engagement_id = :eid"
                        ),
                        {"tid": pub_engagement.tenant_id, "eid": pub_engagement.id},
                    )
                )
                .mappings()
                .all()
            )
            head_ids = {h["node_id"] for h in heads}
            assert head_ids == {scope_root_id("root_domain", "example.com")}


class TestStateRootParity:
    async def test_state_root_matches_ephemeral_rebuild(
        self,
        pub_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:

        att = _v1_attestation()
        await append_payload(session, pub_engagement, att)

        pub_result = await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )
        ephemeral = await rebuild_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
            as_of=FIXED_TIME + timedelta(hours=1),
        )
        assert pub_result.publication.state_root == ephemeral.state_root


class TestStalePublicationSemantics:
    async def test_graph_neutral_anchor_advance_stays_current(
        self,
        pub_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:

        att = _v1_attestation()
        await append_payload(session, pub_engagement, att)

        result1 = await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )
        assert result1.is_current is True

        # Advance ledger with a non-graph event
        stopped = EngagementStopped(
            reason="operator_stop",
            stopped_by="op",
            disposition="graceful_stop",
        )
        await append_payload(session, pub_engagement, stopped)

        # Rebuild again — verified anchor is at event 2 now
        result2 = await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )
        # New publication is current because the graph head did not change
        assert result2.is_current is True

    async def test_stale_candidate_returns_is_current_false(
        self,
        pub_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _v1_attestation()
        v1_event = await append_payload(session, pub_engagement, att)

        result1 = await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=pub_engagement.tenant_id,
            engagement_id=pub_engagement.id,
        )
        assert result1.is_current is True

        # Advance ledger after the candidate is constructed
        stopped = EngagementStopped(
            reason="operator_stop",
            stopped_by="op",
            disposition="graceful_stop",
        )
        await append_payload(session, pub_engagement, stopped)

        # Re-publish the already-constructed v1 candidate
        stale = replace(
            result1.publication,
            verified_event_count=v1_event.sequence,
            verified_head_hash=v1_event.event_hash,
        )
        result2 = await _publish_temporal_publication(engine, stale)
        assert result2.is_current is False
