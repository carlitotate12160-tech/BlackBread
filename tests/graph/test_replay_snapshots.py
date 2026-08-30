import asyncio

import networkx as nx
import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from blackbread.graph.domain import PROJECTOR_VERSION, STATE_ROOT_VERSION
from blackbread.graph.networkx_view import build_networkx_view
from blackbread.graph.persistence import load_scope_projection
from blackbread.graph.replay import rebuild_scope_projection
from blackbread.models.core import Engagement


def _pause_first_stream(
    monkeypatch: pytest.MonkeyPatch,
    entered: asyncio.Event,
    resume: asyncio.Event,
) -> None:
    original = AsyncConnection.stream
    first = True

    async def paused(
        connection: AsyncConnection,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal first
        if first:
            first = False
            entered.set()
            await resume.wait()
        return await original(connection, *args, **kwargs)

    monkeypatch.setattr(AsyncConnection, "stream", paused)


async def test_replay_of_same_verified_ledger_is_idempotent(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    await graph_events.append(session, engagement, graph_events.attestation())

    first = await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    second = await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    assert first == second
    assert first.state_root == second.state_root
    assert len(first.nodes) == 1


async def test_projection_metadata_records_exact_verified_anchor(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    event = await graph_events.append(session, engagement, graph_events.attestation())

    projection = await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    stored = await load_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    assert projection.tenant_id == engagement.tenant_id
    assert projection.engagement_id == engagement.id
    assert projection.verified_event_count == 1
    assert projection.verified_head_hash == event.event_hash
    assert projection.projector_version == PROJECTOR_VERSION
    assert projection.state_root_version == STATE_ROOT_VERSION
    assert projection.ledger_hash_algorithm == "sha256"
    assert projection.ledger_hash_version == 1
    assert stored.projection == projection
    assert stored.is_current is True


async def test_networkx_rebuild_matches_persisted_canonical_projection(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    await graph_events.append(
        session,
        engagement,
        graph_events.attestation(
            root_domains=("example.com",),
            exact_hosts=("api.example.com",),
            exact_addresses=("192.0.2.10",),
            cloud_tenants=("aws:123456789012",),
        ),
    )
    await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    stored = await load_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    graph = build_networkx_view(stored.projection)

    assert set(graph.nodes) == {node.node_id for node in stored.projection.nodes}
    assert graph.number_of_edges() == 0
    assert graph.graph["state_root"] == stored.projection.state_root
    assert {
        (attributes["scope_kind"], attributes["canonical_value"])
        for _, attributes in graph.nodes(data=True)
    } == {(node.scope_kind, node.canonical_value) for node in stored.projection.nodes}
    assert nx.is_frozen(graph)
    with pytest.raises(nx.NetworkXError):
        graph.add_node("mutation")
    with pytest.raises(TypeError):
        graph.graph["state_root"] = "mutated"
    with pytest.raises(TypeError):
        graph.nodes[next(iter(graph.nodes))]["scope_kind"] = "mutated"


async def test_concurrent_append_cannot_mix_verified_projection_snapshot(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attested = await graph_events.append(session, engagement, graph_events.attestation())
    stream_entered = asyncio.Event()
    resume_stream = asyncio.Event()
    _pause_first_stream(monkeypatch, stream_entered, resume_stream)
    rebuilding = asyncio.create_task(
        rebuild_scope_projection(
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )
    )
    await asyncio.wait_for(stream_entered.wait(), timeout=2)

    await graph_events.append(session, engagement, graph_events.stopped)
    resume_stream.set()
    projection = await rebuilding
    monkeypatch.undo()
    stored = await load_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    assert projection.verified_event_count == 1
    assert projection.verified_head_hash == attested.event_hash
    assert stored.projection == projection
    assert stored.is_current is False


async def test_later_noop_event_makes_snapshot_stale_without_changing_graph_root(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    await graph_events.append(session, engagement, graph_events.attestation())
    original = await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    stopped = await graph_events.append(session, engagement, graph_events.stopped)
    stale = await load_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    refreshed = await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    assert stale.is_current is False
    assert stale.projection == original
    assert refreshed.verified_event_count == 2
    assert refreshed.verified_head_hash == stopped.event_hash
    assert refreshed.nodes == original.nodes
    assert refreshed.state_root == original.state_root
