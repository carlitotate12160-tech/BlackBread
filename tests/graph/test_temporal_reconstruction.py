from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from blackbread.graph.domain import GraphProjectionError, scope_root_id
from blackbread.graph.replay import rebuild_scope_projection
from blackbread.graph.temporal_persistence import load_temporal_snapshot
from blackbread.graph.temporal_reconstruction import (
    load_temporal_projection,
)
from blackbread.graph.temporal_replay import (
    rebuild_and_publish_temporal_projection,
)
from blackbread.ledger import EventPayload
from blackbread.ledger.catalog import (
    EngagementAttested,
    EngagementAttestedV2,
    EngagementScope,
)
from blackbread.ledger.event import AgentEvent
from blackbread.models.core import Engagement

FIXED_TIME = datetime(2026, 8, 30, 12, tzinfo=UTC)


class GraphEvents(Protocol):
    attestation: Callable[..., EngagementAttested]
    append: Callable[[AsyncSession, Engagement, EventPayload], Awaitable[AgentEvent]]
    stopped: EventPayload


def _v2(base: EngagementAttested, predecessor: str) -> EngagementAttestedV2:
    return EngagementAttestedV2(
        manifest_hash="b" * 64,
        manifest_signature_ref=base.manifest_signature_ref,
        attested_by=base.attested_by,
        mode=base.mode,
        scope=EngagementScope(root_domains=("example.com", "new.example")),
        valid_from=base.valid_from + timedelta(days=2),
        expires_at=base.expires_at + timedelta(days=2),
        supersedes_event_hash=predecessor,
    )


async def _publish_v1(
    session: AsyncSession,
    engine: AsyncEngine,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> AgentEvent:
    att = graph_events.attestation(root_domains=("example.com",))
    event = await graph_events.append(session, engagement, att)
    await rebuild_and_publish_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    return event


async def _publish_v2(
    session: AsyncSession,
    engine: AsyncEngine,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> tuple[AgentEvent, AgentEvent]:
    att = graph_events.attestation(root_domains=("example.com", "removed.example"))
    first = await graph_events.append(session, engagement, att)
    v2 = _v2(att, first.event_hash)
    second = await graph_events.append(session, engagement, v2)
    await rebuild_and_publish_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    return first, second


async def test_cold_rebuild_v1(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    event = await _publish_v1(session, engine, engagement, graph_events)

    result = await load_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )

    assert result is not None
    assert (
        result.state_root
        == (
            await load_temporal_snapshot(
                engine,
                tenant_id=engagement.tenant_id,
                engagement_id=engagement.id,
            )
        ).snapshot["state_root"]
    )
    assert result.lineage_head_hash == event.event_hash
    head_revisions = result.lineage.groups[-1].revisions
    assert {r.node_id for r in head_revisions} == {scope_root_id("root_domain", "example.com")}


async def test_cold_rebuild_v2(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    _, second = await _publish_v2(session, engine, engagement, graph_events)

    result = await load_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )

    assert result is not None
    snap = await load_temporal_snapshot(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    assert result.state_root == snap.snapshot["state_root"]
    assert result.lineage_head_hash == second.event_hash
    head_revisions = result.lineage.groups[-1].revisions
    assert {r.canonical_value for r in head_revisions} == {
        "example.com",
        "new.example",
    }
    all_events = {r.source_event_hash for r in result.lineage.revisions}
    assert len(all_events) == 2


async def test_revision_durability(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    first, second = await _publish_v2(session, engine, engagement, graph_events)

    result = await load_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    assert result is not None
    revision_ids = {r.revision_id for r in result.lineage.revisions}
    assert len(revision_ids) >= 3

    first_revisions = [
        r for r in result.lineage.revisions if r.source_event_hash == first.event_hash
    ]
    second_revisions = [
        r for r in result.lineage.revisions if r.source_event_hash == second.event_hash
    ]
    assert len(first_revisions) >= 1
    assert len(second_revisions) >= 1

    victim = result.lineage.revisions[0]
    await admin_session.execute(
        text(
            "UPDATE graph_temporal_scope_revisions "
            "SET manifest_hash = :bad "
            "WHERE tenant_id = :tid AND engagement_id = :eid "
            "AND source_event_hash = :seh"
        ),
        {
            "bad": "f" * 64,
            "tid": engagement.tenant_id,
            "eid": engagement.id,
            "seh": victim.source_event_hash,
        },
    )
    await admin_session.commit()

    with pytest.raises(
        GraphProjectionError,
        match="recomputed state-root v2 does not match stored snapshot",
    ):
        await load_temporal_projection(
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )

    await admin_session.execute(
        text(
            "UPDATE graph_temporal_scope_revisions "
            "SET manifest_hash = :good "
            "WHERE tenant_id = :tid AND engagement_id = :eid "
            "AND source_event_hash = :seh"
        ),
        {
            "good": victim.manifest_hash,
            "tid": engagement.tenant_id,
            "eid": engagement.id,
            "seh": victim.source_event_hash,
        },
    )
    await admin_session.commit()

    restored = await load_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    assert restored is not None
    assert restored.state_root == result.state_root


async def test_state_root_tamper(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    await _publish_v2(session, engine, engagement, graph_events)

    original = await load_temporal_snapshot(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    assert original is not None
    good_root = original.snapshot["state_root"]

    await admin_session.execute(
        text(
            "UPDATE graph_temporal_projection_snapshots "
            "SET state_root = :bad "
            "WHERE tenant_id = :tid AND engagement_id = :eid"
        ),
        {
            "bad": "f" * 64,
            "tid": engagement.tenant_id,
            "eid": engagement.id,
        },
    )
    await admin_session.commit()

    with pytest.raises(
        GraphProjectionError,
        match="recomputed state-root v2 does not match stored snapshot",
    ):
        await load_temporal_projection(
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )

    await admin_session.execute(
        text(
            "UPDATE graph_temporal_projection_snapshots "
            "SET state_root = :good "
            "WHERE tenant_id = :tid AND engagement_id = :eid"
        ),
        {
            "good": good_root,
            "tid": engagement.tenant_id,
            "eid": engagement.id,
        },
    )
    await admin_session.commit()


async def test_real_cross_tenant_isolation(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    # A is real, published
    await _publish_v1(session, engine, engagement, graph_events)

    tenant_b = "tenant-b-real"
    eng_b_id = uuid.uuid4()

    dummy_hash = "a" * 64
    client_b_id = uuid.uuid4()

    await admin_session.execute(
        text(
            "INSERT INTO engagements (id, client_id, tenant_id, "
            "ledger_event_count, ledger_head_hash) "
            "VALUES (:eid, :cid, :tid, 0, 'dummy')"
        ),
        {"eid": eng_b_id, "cid": client_b_id, "tid": tenant_b},
    )

    # We must insert into graph_temporal_projection_snapshots directly to prove isolation
    await admin_session.execute(
        text(
            "INSERT INTO graph_temporal_projection_snapshots ("
            "tenant_id, engagement_id, verified_event_count, verified_head_hash, "
            "ledger_hash_algorithm, ledger_hash_version, temporal_projector_version, "
            "state_root_version, scope_canonicalization_version, state_root, "
            "lineage_head_hash, lineage_head_sequence) "
            "VALUES (:tid, :eid, 1, :hash, 'sha256', 1, 2, 2, 1, :hash, :hash, 1)"
        ),
        {"tid": tenant_b, "eid": eng_b_id, "hash": dummy_hash},
    )
    await admin_session.commit()

    # Admin verifies BOTH exist physically
    rows = (
        (
            await admin_session.execute(
                text("SELECT tenant_id, engagement_id FROM graph_temporal_projection_snapshots")
            )
        )
        .mappings()
        .all()
    )
    found = {(r["tenant_id"], r["engagement_id"]) for r in rows}
    assert (engagement.tenant_id, engagement.id) in found
    assert (tenant_b, eng_b_id) in found

    # B loading A's engagement -> None
    b_loads_a = await load_temporal_projection(
        engine, tenant_id=tenant_b, engagement_id=engagement.id
    )
    assert b_loads_a is None

    # A loading B's engagement -> None
    a_loads_b = await load_temporal_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=eng_b_id
    )
    assert a_loads_b is None


async def test_source_event_binding(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    first, second = await _publish_v2(session, engine, engagement, graph_events)

    result = await load_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    assert result is not None

    for revision in result.lineage.revisions:
        assert revision.source_schema_name == "engagement.attested"
        assert revision.source_schema_version in (1, 2)
        assert revision.source_event_hash in (
            first.event_hash,
            second.event_hash,
        )
        if revision.source_schema_version == 1:
            assert revision.predecessor_attestation_event_hash is None
        else:
            assert revision.predecessor_attestation_event_hash == first.event_hash

    v1_revisions = [r for r in result.lineage.revisions if r.source_event_hash == first.event_hash]
    for rev in v1_revisions:
        assert rev.source_sequence == first.sequence


async def test_v2_publishes_via_temporal_path(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    _, second = await _publish_v2(session, engine, engagement, graph_events)

    result = await load_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    assert result is not None
    assert (
        result.state_root
        == (
            await load_temporal_snapshot(
                engine,
                tenant_id=engagement.tenant_id,
                engagement_id=engagement.id,
            )
        ).snapshot["state_root"]
    )
    assert result.lineage_head_hash == second.event_hash
    assert result.verified_event_count >= 2
    assert result.verified_head_hash == second.event_hash


async def test_v1_scope_path_rejects_v2(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    att = graph_events.attestation(root_domains=("example.com", "removed.example"))
    first = await graph_events.append(session, engagement, att)
    await graph_events.append(session, engagement, _v2(att, first.event_hash))

    with pytest.raises(
        GraphProjectionError,
        match="v1 scope path does not accept v2 provenance",
    ):
        await rebuild_scope_projection(
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )


async def test_stable_roots_tamper(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    await _publish_v2(session, engine, engagement, graph_events)

    result = await load_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    assert result is not None
    assert len(result.lineage.revisions) > 0

    victim_rev = result.lineage.revisions[0]
    fake_node_id = "f" * 64

    # Insert an extra fake root to simulate a tamper
    await admin_session.execute(
        text(
            "INSERT INTO graph_temporal_scope_roots (tenant_id, engagement_id, node_id, "
            "node_family, scope_kind, canonical_value) "
            "VALUES (:tid, :eid, :nid, 'ScopeRoot', :skind, 'tampered.example')"
        ),
        {
            "tid": engagement.tenant_id,
            "eid": engagement.id,
            "nid": fake_node_id,
            "skind": victim_rev.scope_kind,
        },
    )
    await admin_session.commit()

    with pytest.raises(
        GraphProjectionError,
        match="reconstructed stable roots do not match lineage",
    ):
        await load_temporal_projection(
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )

    # Remove the fake root to restore integrity
    await admin_session.execute(
        text(
            "DELETE FROM graph_temporal_scope_roots "
            "WHERE tenant_id = :tid AND engagement_id = :eid "
            "AND node_id = :nid AND canonical_value = 'tampered.example'"
        ),
        {
            "tid": engagement.tenant_id,
            "eid": engagement.id,
            "nid": fake_node_id,
        },
    )
    await admin_session.commit()

    # Reconstruct again should succeed
    restored = await load_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    assert restored is not None
