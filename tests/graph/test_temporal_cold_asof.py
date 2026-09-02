from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from blackbread.graph.networkx_view import (
    build_temporal_networkx_view,
    load_temporal_networkx_view_as_of,
)
from blackbread.graph.temporal_reconstruction import load_temporal_projection_as_of
from blackbread.graph.temporal_replay import rebuild_temporal_projection
from blackbread.models.core import Engagement
from tests.graph.test_temporal_reconstruction import FIXED_TIME, GraphEvents, _publish_v2


async def test_as_of_selection_parity(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    first, second = await _publish_v2(session, engine, engagement, graph_events)

    t_early = FIXED_TIME + timedelta(days=1)
    t_late = FIXED_TIME + timedelta(days=3)

    cold_early = await load_temporal_projection_as_of(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id, as_of=t_early
    )
    assert cold_early is not None
    assert cold_early.effective_attestation_event_hash == first.event_hash

    replay_early = await rebuild_temporal_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id, as_of=t_early
    )
    assert (
        cold_early.effective_attestation_event_hash == replay_early.effective_attestation_event_hash
    )
    assert cold_early.effective_nodes == replay_early.effective_nodes
    assert cold_early.state_root == replay_early.state_root
    assert cold_early.as_of == replay_early.as_of

    cold_late = await load_temporal_projection_as_of(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id, as_of=t_late
    )
    assert cold_late is not None
    assert cold_late.effective_attestation_event_hash == second.event_hash

    replay_late = await rebuild_temporal_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id, as_of=t_late
    )
    assert (
        cold_late.effective_attestation_event_hash == replay_late.effective_attestation_event_hash
    )
    assert cold_late.effective_nodes == replay_late.effective_nodes
    assert cold_late.state_root == replay_late.state_root
    assert cold_late.as_of == replay_late.as_of


async def test_as_of_canonical_boundary(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    await _publish_v2(session, engine, engagement, graph_events)

    with pytest.raises(ValueError, match="as_of must be timezone-aware"):
        await load_temporal_projection_as_of(
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
            as_of=datetime.now(),
        )


async def test_networkx_cold_view_parity(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    await _publish_v2(session, engine, engagement, graph_events)
    t_late = FIXED_TIME + timedelta(days=3)

    nx_cold = await load_temporal_networkx_view_as_of(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id, as_of=t_late
    )
    assert nx_cold is not None
    assert nx_cold.number_of_edges() == 0
    assert nx_cold.graph["tenant_id"] == engagement.tenant_id
    assert nx_cold.graph["engagement_id"] == engagement.id

    replay_late = await rebuild_temporal_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id, as_of=t_late
    )
    nx_replay = build_temporal_networkx_view(replay_late)

    assert nx_cold.nodes == nx_replay.nodes
    assert nx_cold.edges == nx_replay.edges
    assert nx_cold.graph == nx_replay.graph


async def test_as_of_tenant_isolation(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    await _publish_v2(session, engine, engagement, graph_events)
    t_late = FIXED_TIME + timedelta(days=3)

    wrong_tenant = await load_temporal_projection_as_of(
        engine, tenant_id="wrong-tenant", engagement_id=engagement.id, as_of=t_late
    )
    assert wrong_tenant is None
