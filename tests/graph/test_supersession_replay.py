from collections.abc import Awaitable, Callable
from typing import Protocol

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from blackbread.graph.domain import GraphProjectionError, ProjectionNotFoundError
from blackbread.graph.persistence import load_scope_projection
from blackbread.graph.replay import rebuild_scope_projection
from blackbread.ledger import EventPayload
from blackbread.ledger.catalog import EngagementAttested, EngagementAttestedV2
from blackbread.ledger.event import AgentEvent
from blackbread.models.core import Engagement


class GraphEvents(Protocol):
    attestation: Callable[..., EngagementAttested]
    append: Callable[[AsyncSession, Engagement, EventPayload], Awaitable[AgentEvent]]


async def test_v2_ledger_head_fails_before_v1_only_projection_publication(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    initial = await graph_events.append(session, engagement, graph_events.attestation())
    replacement = graph_events.attestation(root_domains=("replacement.example",))
    await graph_events.append(
        session,
        engagement,
        EngagementAttestedV2(
            manifest_hash=replacement.manifest_hash,
            manifest_signature_ref=replacement.manifest_signature_ref,
            attested_by=replacement.attested_by,
            mode=replacement.mode,
            scope=replacement.scope,
            valid_from=replacement.valid_from,
            expires_at=replacement.expires_at,
            supersedes_event_hash=initial.event_hash,
        ),
    )

    with pytest.raises(GraphProjectionError, match="v1 scope path does not accept v2 provenance"):
        await rebuild_scope_projection(
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )
    with pytest.raises(ProjectionNotFoundError):
        await load_scope_projection(
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )
