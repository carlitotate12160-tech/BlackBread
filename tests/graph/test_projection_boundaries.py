from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from blackbread.graph.domain import (
    GraphProjectionError,
    ProjectionNotFoundError,
    ScopeProjection,
    ScopeProjector,
    compute_state_root,
    scope_root_id,
)
from blackbread.graph.persistence import load_scope_projection, publish_scope_projection
from blackbread.graph.replay import rebuild_scope_projection
from blackbread.ledger.event import AgentEvent
from blackbread.models.core import Engagement


async def test_publication_rejects_nodes_not_exactly_attested(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    event = await graph_events.append(session, engagement, graph_events.attestation())
    projector = ScopeProjector()
    projector.consume(event)
    original = projector.nodes[0]
    forged_nodes = (
        replace(
            original,
            node_id=scope_root_id("root_domain", "forged.example.com"),
            canonical_value="forged.example.com",
        ),
        replace(original, manifest_hash="b" * 64),
        replace(original, valid_from=original.valid_from + timedelta(hours=1)),
    )

    for forged_node in forged_nodes:
        nodes = (forged_node,)
        forged = ScopeProjection(
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
            verified_event_count=1,
            verified_head_hash=event.event_hash,
            state_root=compute_state_root(engagement.tenant_id, engagement.id, nodes),
            nodes=nodes,
        )
        with pytest.raises(IntegrityError, match="not exactly bound"):
            await publish_scope_projection(engine, forged)

    with pytest.raises(ProjectionNotFoundError, match="scope projection is not published"):
        await load_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )


async def test_projector_receives_no_events_before_failed_snapshot_verdict(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events,
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
    original_consume = ScopeProjector.consume

    def observe_consume(projector: ScopeProjector, event: AgentEvent) -> None:
        consumed.append(event.sequence)
        original_consume(projector, event)

    with (
        patch.object(ScopeProjector, "consume", observe_consume),
        pytest.raises(GraphProjectionError, match="ledger verification failed"),
    ):
        await rebuild_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )

    assert consumed == []
