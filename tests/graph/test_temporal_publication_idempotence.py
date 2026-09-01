"""Durable temporal publication idempotence and repair tests.

Real PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from blackbread.graph.temporal_persistence import _publish_temporal_publication
from blackbread.graph.temporal_publication import TemporalPublication
from blackbread.graph.temporal_replay import rebuild_and_publish_temporal_projection
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

TENANT = "idempotence-test-tenant"


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


async def _expected_head_rows(pub: TemporalPublication) -> set[tuple[str, str, str]]:
    final = pub.lineage.groups[-1]
    return {(rev.node_id, rev.revision_id, final.source_event_hash) for rev in final.revisions}


async def _delete_one_head(engine: AsyncEngine, pub: TemporalPublication) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"SET blackbread.tenant_id = '{pub.tenant_id}'"))
        await conn.execute(
            text(
                "DELETE FROM graph_temporal_head_nodes "
                "WHERE tenant_id = :tid AND engagement_id = :eid "
                "AND node_id = (SELECT node_id FROM graph_temporal_head_nodes "
                "WHERE tenant_id = :tid AND engagement_id = :eid LIMIT 1)"
            ),
            {"tid": pub.tenant_id, "eid": pub.engagement_id},
        )


async def _delete_all_heads(engine: AsyncEngine, pub: TemporalPublication) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"SET blackbread.tenant_id = '{pub.tenant_id}'"))
        await conn.execute(
            text(
                "DELETE FROM graph_temporal_head_nodes "
                "WHERE tenant_id = :tid AND engagement_id = :eid"
            ),
            {"tid": pub.tenant_id, "eid": pub.engagement_id},
        )


async def _head_rows(engine: AsyncEngine, pub: TemporalPublication) -> set[tuple[str, str, str]]:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET blackbread.tenant_id = '{pub.tenant_id}'"))
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT node_id, revision_id, source_event_hash "
                        "FROM graph_temporal_head_nodes "
                        "WHERE tenant_id = :tid AND engagement_id = :eid"
                    ),
                    {"tid": pub.tenant_id, "eid": pub.engagement_id},
                )
            )
            .mappings()
            .all()
        )
    return {(r["node_id"], r["revision_id"], r["source_event_hash"]) for r in rows}


class TestDurableIdempotence:
    async def test_republish_repairs_one_missing_head(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _attestation(root_domains=("example.com", "test.org"))
        await append_payload(session, fail_engagement, att)

        pub = await _published(engine, fail_engagement)
        expected = await _expected_head_rows(pub)

        await _delete_one_head(engine, pub)
        await _published(engine, fail_engagement)
        assert await _head_rows(engine, pub) == expected

    async def test_republish_repairs_all_missing_heads(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _attestation(root_domains=("example.com", "test.org"))
        await append_payload(session, fail_engagement, att)

        pub = await _published(engine, fail_engagement)
        expected = await _expected_head_rows(pub)

        await _delete_all_heads(engine, pub)
        await _published(engine, fail_engagement)
        assert await _head_rows(engine, pub) == expected

    async def test_injected_head_row_rejected_or_repaired(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _attestation(root_domains=("example.com",))
        await append_payload(session, fail_engagement, att)

        pub = await _published(engine, fail_engagement)
        expected = await _expected_head_rows(pub)

        async with engine.connect() as conn:
            await conn.execute(text(f"SET blackbread.tenant_id = '{pub.tenant_id}'"))
            with pytest.raises(Exception):  # noqa: B017
                await conn.execute(
                    text(
                        "INSERT INTO graph_temporal_head_nodes "
                        "(tenant_id, engagement_id, node_id, revision_id, source_event_hash) "
                        "VALUES (:tid, :eid, :nid, :rid, :seh)"
                    ),
                    {
                        "tid": pub.tenant_id,
                        "eid": pub.engagement_id,
                        "nid": "f" * 64,
                        "rid": "f" * 64,
                        "seh": "f" * 64,
                    },
                )

        await _published(engine, fail_engagement)
        assert await _head_rows(engine, pub) == expected

    async def test_no_op_anchor_advance_restores_exact_head(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _attestation(root_domains=("example.com", "test.org"))
        await append_payload(session, fail_engagement, att)

        pub = await _published(engine, fail_engagement)
        expected = await _expected_head_rows(pub)

        await _delete_all_heads(engine, pub)

        stopped = EngagementStopped(
            reason="operator_stop",
            stopped_by="op",
            disposition="graceful_stop",
        )
        await append_payload(session, fail_engagement, stopped)

        await rebuild_and_publish_temporal_projection(
            engine,
            tenant_id=fail_engagement.tenant_id,
            engagement_id=fail_engagement.id,
        )
        assert await _head_rows(engine, pub) == expected

    async def test_fully_consistent_republish_is_idempotent(
        self,
        fail_engagement: Engagement,
        session: AsyncSession,
        append_payload: object,
        engine: AsyncEngine,
    ) -> None:
        att = _attestation(root_domains=("example.com", "test.org"))
        await append_payload(session, fail_engagement, att)

        pub = await _published(engine, fail_engagement)

        result2 = await _publish_temporal_publication(engine, pub)
        assert result2.is_current is True
        assert await _head_rows(engine, pub) == await _expected_head_rows(pub)
