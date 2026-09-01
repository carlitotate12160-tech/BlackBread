from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from blackbread.graph.domain import GraphProjectionError, ScopeProjector, ScopeRoot
from blackbread.graph.state_root import (
    SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
    compute_temporal_state_root,
)
from blackbread.graph.temporal import (
    TemporalLineage,
    select_temporal_scope,
    validate_temporal_lineage,
)
from blackbread.graph.temporal_persistence import _publish_temporal_publication
from blackbread.graph.temporal_projection import (
    TemporalProjection,
    validate_temporal_projection,
)
from blackbread.graph.temporal_publication import (
    TemporalPublication,
    TemporalPublicationRead,
    validate_temporal_publication,
)
from blackbread.ledger.verify import ChainVerification, replay_verified_snapshot
from blackbread.tenancy import TenantContext, bind_tenant_context


async def _verify_and_reconstruct_lineage(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    engagement_id: UUID,
) -> tuple[ChainVerification, TemporalLineage]:
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
    return verification, lineage


async def rebuild_temporal_projection(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    engagement_id: UUID,
    as_of: datetime,
) -> TemporalProjection:
    _ver, lineage = await _verify_and_reconstruct_lineage(
        engine, tenant_id=tenant_id, engagement_id=engagement_id
    )
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


async def rebuild_and_publish_temporal_projection(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    engagement_id: UUID,
) -> TemporalPublicationRead:
    """Verified replay -> construct TemporalPublication -> persist durably."""
    verification, lineage = await _verify_and_reconstruct_lineage(
        engine, tenant_id=tenant_id, engagement_id=engagement_id
    )
    state_root = compute_temporal_state_root(tenant_id, engagement_id, lineage)
    final_group = lineage.groups[-1]
    structural_head_nodes = tuple(
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
    assert verification.verified_head_hash is not None
    publication = TemporalPublication(
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        verified_event_count=verification.event_count,
        verified_head_hash=verification.verified_head_hash,
        lineage=lineage,
        state_root=state_root,
        versions=SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
        structural_head_nodes=structural_head_nodes,
    )
    validate_temporal_publication(publication)
    return await _publish_temporal_publication(engine, publication)
