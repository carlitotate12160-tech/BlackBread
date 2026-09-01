from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from blackbread.graph.domain import GraphProjectionError, ScopeProjector
from blackbread.graph.state_root import (
    SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
    compute_temporal_state_root,
)
from blackbread.graph.temporal import (
    select_temporal_scope,
    validate_temporal_lineage,
)
from blackbread.graph.temporal_projection import (
    TemporalProjection,
    validate_temporal_projection,
)
from blackbread.ledger.verify import replay_verified_snapshot
from blackbread.tenancy import TenantContext, bind_tenant_context


async def rebuild_temporal_projection(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    engagement_id: UUID,
    as_of: datetime,
) -> TemporalProjection:
    projector = ScopeProjector()
    async with engine.connect() as acquired:
        connection = await acquired.execution_options(isolation_level="REPEATABLE READ")
        async with connection.begin():
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            await bind_tenant_context(connection, TenantContext(tenant_id))
            verification = await replay_verified_snapshot(
                connection,
                tenant_id=tenant_id,
                engagement_id=engagement_id,
                consumer=projector.consume,
            )
            if not verification.ok or verification.verified_head_hash is None:
                reason = verification.reason or "missing verified head"
                raise GraphProjectionError(f"ledger verification failed: {reason}")
    lineage_head = projector.lineage_head_hash
    if lineage_head is None:
        raise GraphProjectionError("verified ledger has no attestation")
    lineage = validate_temporal_lineage(projector.revisions, lineage_head_hash=lineage_head)
    selection = select_temporal_scope(
        lineage.revisions,
        as_of=as_of,
        lineage_head_hash=lineage.lineage_head_hash,
    )
    projection = TemporalProjection(
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        lineage=lineage,
        state_root=compute_temporal_state_root(tenant_id, engagement_id, lineage),
        versions=SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
        as_of=selection.as_of,
        effective_attestation_event_hash=selection.effective_attestation_event_hash,
        effective_nodes=selection.effective_nodes,
    )
    return validate_temporal_projection(projection)
