from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from blackbread.graph import domain
from blackbread.graph.domain import compute_state_root
from blackbread.graph.persistence import publish_scope_projection
from blackbread.ledger.verify import replay_verified_snapshot
from blackbread.tenancy import TenantContext, bind_tenant_context


async def rebuild_scope_projection(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    engagement_id: UUID,
    projector_version: int = domain.PROJECTOR_VERSION,
    state_root_version: int = domain.STATE_ROOT_VERSION,
) -> domain.ScopeProjection:
    projector = domain.ScopeProjector(version=projector_version)
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
                raise domain.GraphProjectionError(f"ledger verification failed: {reason}")
    if not projector.nodes:
        raise domain.GraphProjectionError("verified ledger has no attestation")
    root = compute_state_root(tenant_id, engagement_id, projector.nodes, version=state_root_version)
    projection = domain.ScopeProjection(
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        verified_event_count=verification.verified_event_count,
        verified_head_hash=verification.verified_head_hash,
        state_root=root,
        nodes=projector.nodes,
    )
    await publish_scope_projection(engine, projection)
    return projection
