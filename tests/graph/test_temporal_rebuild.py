from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Protocol
from unittest.mock import patch

import networkx as nx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from blackbread.graph.domain import GraphProjectionError, ProjectionNotFoundError, ScopeProjector
from blackbread.graph.networkx_view import build_temporal_networkx_view
from blackbread.graph.persistence import load_scope_projection
from blackbread.graph.replay import rebuild_scope_projection
from blackbread.graph.state_root import compute_temporal_state_root
from blackbread.graph.temporal_replay import rebuild_temporal_projection
from blackbread.ledger import EventPayload
from blackbread.ledger.catalog import EngagementAttested, EngagementAttestedV2, EngagementScope
from blackbread.ledger.event import AgentEvent
from blackbread.models.core import Engagement


class GraphEvents(Protocol):
    attestation: Callable[..., EngagementAttested]
    append: Callable[[AsyncSession, Engagement, EventPayload], Awaitable[AgentEvent]]
    stopped: EventPayload


def _replacement(
    base: EngagementAttested,
    predecessor: str,
    *,
    values: tuple[str, ...] = ("replacement.example",),
    valid_from: datetime | None = None,
    expires_at: datetime | None = None,
) -> EngagementAttestedV2:
    return EngagementAttestedV2(
        manifest_hash="b" * 64,
        manifest_signature_ref=base.manifest_signature_ref,
        attested_by=base.attested_by,
        mode=base.mode,
        scope=EngagementScope(root_domains=values),
        valid_from=valid_from or base.valid_from + timedelta(days=2),
        expires_at=expires_at or base.expires_at + timedelta(days=2),
        supersedes_event_hash=predecessor,
    )


async def _append_history(
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> tuple[EngagementAttested, AgentEvent, AgentEvent]:
    initial = graph_events.attestation(root_domains=("example.com", "removed.example"))
    first = await graph_events.append(session, engagement, initial)
    second = await graph_events.append(
        session,
        engagement,
        _replacement(initial, first.event_hash, values=("example.com", "new.example")),
    )
    return initial, first, second


async def test_cold_temporal_rebuild_is_deterministic_and_order_independent(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    initial, _, second = await _append_history(session, engagement, graph_events)
    as_of = initial.valid_from + timedelta(days=3)

    first = await rebuild_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        as_of=as_of,
    )
    repeated = await rebuild_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        as_of=as_of,
    )

    assert first == repeated
    assert first.lineage_head_hash == second.event_hash
    assert first.effective_attestation_event_hash == second.event_hash
    assert first.revisions == tuple(
        sorted(
            first.revisions, key=lambda item: (item.source_sequence, item.node_id, item.revision_id)
        )
    )

    stopped = await graph_events.append(session, engagement, graph_events.stopped)
    after_noop = await rebuild_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        as_of=as_of,
    )
    assert after_noop.state_root == first.state_root
    assert after_noop.effective_nodes == first.effective_nodes
    assert after_noop.verified_event_count == first.verified_event_count + 1
    assert after_noop.verified_head_hash == stopped.event_hash


async def test_temporal_rebuild_requires_explicit_as_of(
    engine: AsyncEngine,
    engagement: Engagement,
) -> None:
    with pytest.raises(TypeError):
        await rebuild_temporal_projection(
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )


async def test_temporal_rebuild_normalizes_equivalent_as_of_offsets(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    initial, _, _ = await _append_history(session, engagement, graph_events)
    as_of = initial.valid_from + timedelta(days=3)

    utc = await rebuild_temporal_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id, as_of=as_of
    )
    offset = await rebuild_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        as_of=as_of.astimezone(timezone(timedelta(hours=7))),
    )

    assert utc == offset


async def test_temporal_projection_keeps_full_history_and_complete_effective_group(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    initial, first, second = await _append_history(session, engagement, graph_events)

    projection = await rebuild_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        as_of=initial.valid_from + timedelta(days=3),
    )

    assert {revision.source_event_hash for revision in projection.revisions} == {
        first.event_hash,
        second.event_hash,
    }
    assert {node.canonical_value for node in projection.effective_nodes} == {
        "example.com",
        "new.example",
    }
    assert projection.has_effective_authority is True
    assert (
        compute_temporal_state_root(
            projection.tenant_id, projection.engagement_id, projection.lineage
        )
        == projection.state_root
    )


async def test_state_root_is_independent_of_temporal_rebuild_as_of(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    initial, first, second = await _append_history(session, engagement, graph_events)

    before = await rebuild_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        as_of=initial.valid_from + timedelta(days=1),
    )
    after = await rebuild_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        as_of=initial.valid_from + timedelta(days=3),
    )

    assert before.effective_attestation_event_hash == first.event_hash
    assert after.effective_attestation_event_hash == second.event_hash
    assert before.state_root == after.state_root


async def test_temporal_rebuild_preserves_verify_before_consume(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    await graph_events.append(session, engagement, graph_events.attestation())
    stopped = await graph_events.append(session, engagement, graph_events.stopped)
    await admin_session.execute(
        text("ALTER TABLE agent_events DISABLE TRIGGER agent_events_reject_mutation")
    )
    await admin_session.execute(
        AgentEvent.__table__.update()
        .where(AgentEvent.id == stopped.id)
        .values(payload={"bad": True})
    )
    await admin_session.execute(
        text("ALTER TABLE agent_events ENABLE TRIGGER agent_events_reject_mutation")
    )
    await admin_session.commit()
    consumed: list[int] = []
    original = ScopeProjector.consume

    def observe(projector: ScopeProjector, event: AgentEvent) -> None:
        consumed.append(event.sequence)
        original(projector, event)

    with (
        patch.object(ScopeProjector, "consume", observe),
        pytest.raises(GraphProjectionError, match="ledger verification failed"),
    ):
        await rebuild_temporal_projection(
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
            as_of=datetime(2026, 9, 1, tzinfo=UTC),
        )
    assert consumed == []


async def test_temporal_rebuild_replays_canonical_ledger_order(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    initial, _, _ = await _append_history(session, engagement, graph_events)
    consumed: list[int] = []
    original = ScopeProjector.consume

    def observe(projector: ScopeProjector, event: AgentEvent) -> None:
        consumed.append(event.sequence)
        original(projector, event)

    with patch.object(ScopeProjector, "consume", observe):
        await rebuild_temporal_projection(
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
            as_of=initial.valid_from + timedelta(days=3),
        )

    assert consumed == [1, 2]


async def test_temporal_rebuild_persists_nothing(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    initial, _, _ = await _append_history(session, engagement, graph_events)
    query = text(
        "SELECT (SELECT count(*) FROM graph_projection_snapshots WHERE engagement_id = :id), "
        "(SELECT count(*) FROM graph_nodes WHERE engagement_id = :id)"
    )
    before = (await admin_session.execute(query, {"id": engagement.id})).one()

    await rebuild_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        as_of=initial.valid_from + timedelta(days=3),
    )
    after = (await admin_session.execute(query, {"id": engagement.id})).one()

    assert before == after == (0, 0)


async def test_temporal_networkx_view_contains_only_effective_scope(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    initial, _, _ = await _append_history(session, engagement, graph_events)
    projection = await rebuild_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        as_of=initial.valid_from + timedelta(days=3),
    )

    graph = build_temporal_networkx_view(projection)

    assert set(graph.nodes) == {node.node_id for node in projection.effective_nodes}
    assert {attributes["canonical_value"] for _, attributes in graph.nodes(data=True)} == {
        "example.com",
        "new.example",
    }
    assert all(
        attributes["tenant_id"] == engagement.tenant_id for _, attributes in graph.nodes(data=True)
    )
    assert all(
        attributes["engagement_id"] == engagement.id for _, attributes in graph.nodes(data=True)
    )
    assert graph.graph == {
        "tenant_id": projection.tenant_id,
        "engagement_id": projection.engagement_id,
        "verified_event_count": projection.verified_event_count,
        "verified_head_hash": projection.verified_head_hash,
        "state_root": projection.state_root,
        "state_root_version": 2,
        "projector_version": 2,
        "scope_canonicalization_version": 1,
        "lineage_head_hash": projection.lineage_head_hash,
        "as_of": projection.as_of,
        "effective_attestation_event_hash": projection.effective_attestation_event_hash,
        "has_effective_authority": True,
    }


async def test_temporal_networkx_view_is_immutable_and_has_zero_edges(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    initial, _, _ = await _append_history(session, engagement, graph_events)
    projection = await rebuild_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        as_of=initial.valid_from + timedelta(days=3),
    )
    graph = build_temporal_networkx_view(projection)

    assert nx.is_frozen(graph)
    assert graph.number_of_edges() == 0
    with pytest.raises(nx.NetworkXError):
        graph.add_node("mutation")
    with pytest.raises(TypeError):
        graph.graph["state_root"] = "mutation"
    with pytest.raises(TypeError):
        graph.nodes[next(iter(graph.nodes))]["scope_kind"] = "mutation"


async def test_empty_authority_yields_empty_temporal_networkx_view(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    initial = graph_events.attestation()
    await graph_events.append(session, engagement, initial)
    projection = await rebuild_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        as_of=initial.expires_at,
    )

    graph = build_temporal_networkx_view(projection)

    assert projection.has_effective_authority is False
    assert graph.number_of_nodes() == 0
    assert graph.number_of_edges() == 0


async def test_temporal_rebuild_distinguishes_pre_activation_gap_and_no_reactivation(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    base = graph_events.attestation()
    initial = EngagementAttested(
        manifest_hash=base.manifest_hash,
        manifest_signature_ref=base.manifest_signature_ref,
        attested_by=base.attested_by,
        mode=base.mode,
        scope=base.scope,
        valid_from=base.valid_from,
        expires_at=base.valid_from + timedelta(days=4),
    )
    first = await graph_events.append(session, engagement, initial)
    successor = await graph_events.append(
        session,
        engagement,
        _replacement(
            initial,
            first.event_hash,
            valid_from=initial.valid_from + timedelta(days=8),
            expires_at=initial.valid_from + timedelta(days=10),
        ),
    )
    queries = (
        (initial.valid_from - timedelta(seconds=1), None),
        (initial.valid_from + timedelta(days=6), None),
        (initial.valid_from + timedelta(days=8), successor.event_hash),
        (initial.valid_from + timedelta(days=11), None),
    )

    for as_of, effective_hash in queries:
        projection = await rebuild_temporal_projection(
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
            as_of=as_of,
        )
        assert projection.effective_attestation_event_hash == effective_hash
        expected = {"replacement.example"} if effective_hash is not None else set()
        assert {node.canonical_value for node in projection.effective_nodes} == expected


async def test_networkx_effective_node_order_does_not_change_state_root(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    initial, _, _ = await _append_history(session, engagement, graph_events)
    projection = await rebuild_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        as_of=initial.valid_from + timedelta(days=3),
    )
    reordered = replace(projection, effective_nodes=tuple(reversed(projection.effective_nodes)))

    graph = build_temporal_networkx_view(reordered)

    assert graph.graph["state_root"] == projection.state_root
    assert reordered.state_root == projection.state_root


async def test_existing_v1_lone_attestation_publication_remains_unchanged(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    await graph_events.append(session, engagement, graph_events.attestation())

    rebuilt = await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    loaded = await load_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    assert loaded.projection == rebuilt
    assert loaded.is_current is True


async def test_existing_v2_head_publication_remains_blocked(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    await _append_history(session, engagement, graph_events)

    with pytest.raises(GraphProjectionError, match="GRAPH-GAP-001"):
        await rebuild_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )
    with pytest.raises(ProjectionNotFoundError):
        await load_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )
