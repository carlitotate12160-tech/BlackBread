from dataclasses import fields
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from blackbread.graph import domain
from blackbread.graph.domain import ScopeProjection, compute_state_root
from blackbread.ledger.errors import LedgerAccessError
from blackbread.tenancy import TenantContext, bind_tenant_context

_META = tuple(field.name for field in fields(ScopeProjection) if field.name != "nodes")
_META += ("ledger_hash_algorithm", "ledger_hash_version", "projector_version", "state_root_version")
_ROOT = tuple(field.name for field in fields(domain.ScopeRoot))
_SELECT_META = text(
    "SELECT * FROM graph_projection_snapshots "
    "WHERE tenant_id = :tenant_id AND engagement_id = :engagement_id"
)
_SELECT_NODES = text(
    "SELECT * FROM graph_nodes WHERE tenant_id = :tenant_id AND engagement_id = :engagement_id"
)
_UPSERT_META = text(
    "INSERT INTO graph_projection_snapshots (tenant_id, engagement_id, verified_event_count, "
    "verified_head_hash, state_root, ledger_hash_algorithm, ledger_hash_version, "
    "projector_version, state_root_version) VALUES (:tenant_id, :engagement_id, "
    ":verified_event_count, :verified_head_hash, :state_root, :ledger_hash_algorithm, "
    ":ledger_hash_version, :projector_version, :state_root_version) ON CONFLICT "
    "(tenant_id, engagement_id) DO UPDATE SET verified_event_count=EXCLUDED.verified_event_count, "
    "verified_head_hash = EXCLUDED.verified_head_hash, "
    "state_root = EXCLUDED.state_root, ledger_hash_algorithm = EXCLUDED.ledger_hash_algorithm, "
    "ledger_hash_version = EXCLUDED.ledger_hash_version, "
    "projector_version=EXCLUDED.projector_version, state_root_version=EXCLUDED.state_root_version"
)
_INSERT_NODES = text(
    "INSERT INTO graph_nodes (tenant_id, engagement_id, graph_version, node_id, scope_kind, "
    "canonical_value, manifest_hash, valid_from, valid_until, source_sequence, source_event_hash, "
    "node_family, authority, source_schema_name, source_schema_version) VALUES "
    "(:tenant_id, :engagement_id, :graph_version, :node_id, :scope_kind, :canonical_value, "
    ":manifest_hash, :valid_from, :valid_until, :source_sequence, :source_event_hash, "
    ":node_family, :authority, :source_schema_name, :source_schema_version)"
)
_DELETE_NODES = text(
    "DELETE FROM graph_nodes WHERE tenant_id = :tenant_id AND engagement_id = :engagement_id"
)
_ANCHOR = "SELECT ledger_event_count, ledger_head_hash FROM engagements WHERE tenant_id = "
_ANCHOR += ":tenant_id AND id = :engagement_id"


class _ProjectionStore:
    def __init__(self, connection: AsyncConnection, tenant_id: str, engagement_id: UUID) -> None:
        self.connection = connection
        self.key: dict[str, object] = {"tenant_id": tenant_id, "engagement_id": engagement_id}

    async def anchor(self, *, lock: bool = False) -> tuple[int, str]:
        query = text(_ANCHOR + (" FOR UPDATE" if lock else ""))
        row = (await self.connection.execute(query, self.key)).one_or_none()
        if row is None:
            raise LedgerAccessError("engagement is unavailable for the requested tenant")
        return row.ledger_event_count, row.ledger_head_hash

    async def node_rows(self) -> list[RowMapping]:
        return list((await self.connection.execute(_SELECT_NODES, self.key)).mappings().all())

    @staticmethod
    def node(row: RowMapping, graph_version: int) -> domain.ScopeRoot:
        if row["graph_version"] != graph_version:
            raise domain.GraphProjectionError("projection node metadata mismatch")
        return domain.ScopeRoot(**{field: row[field] for field in _ROOT})

    @staticmethod
    def root(projection: ScopeProjection) -> str:
        return compute_state_root(projection.tenant_id, projection.engagement_id, projection.nodes)

    async def read(self, anchor: tuple[int, str] | None = None) -> domain.ProjectionRead:
        current = anchor or await self.anchor()
        metadata = (await self.connection.execute(_SELECT_META, self.key)).mappings().one_or_none()
        if metadata is None:
            raise domain.ProjectionNotFoundError("scope projection is not published")
        rows = await self.node_rows()
        version = metadata["verified_event_count"]
        nodes = tuple(
            sorted((self.node(row, version) for row in rows), key=lambda node: node.node_id)
        )
        values = dict(metadata)
        if any(values.pop(field) != getattr(ScopeProjection, field) for field in _META[-4:]):
            raise domain.GraphProjectionError("persisted projection version is unsupported")
        projection = ScopeProjection(nodes=nodes, **values)
        if projection.state_root != self.root(projection):
            raise domain.GraphProjectionError("persisted projection state root mismatch")
        fresh = (projection.verified_event_count, projection.verified_head_hash) == current
        return domain.ProjectionRead(projection, fresh)

    @staticmethod
    def metadata(projection: domain.ScopeProjection) -> dict[str, object]:
        return {field: getattr(projection, field) for field in _META}

    def nodes(self, projection: domain.ScopeProjection) -> list[dict[str, object]]:
        common = {**self.key, "graph_version": projection.verified_event_count}
        return [
            {**common, **{field: getattr(node, field) for field in _ROOT}}
            for node in projection.nodes
        ]

    async def publish(self, projection: domain.ScopeProjection) -> None:
        if projection.state_root != self.root(projection):
            raise domain.GraphProjectionError("projection state root is invalid")
        anchor = await self.anchor(lock=True)
        try:
            existing = (await self.read(anchor)).projection
        except domain.ProjectionNotFoundError:
            existing = None
        if existing == projection:
            return
        existing_version = existing.verified_event_count if existing is not None else -1
        if existing_version >= projection.verified_event_count:
            raise domain.GraphProjectionError("projection anchor regression")
        await self.connection.execute(_DELETE_NODES, self.key)
        await self.connection.execute(_UPSERT_META, self.metadata(projection))
        if projection.nodes:
            await self.connection.execute(_INSERT_NODES, self.nodes(projection))


async def publish_scope_projection(engine: AsyncEngine, projection: domain.ScopeProjection) -> None:
    async with engine.begin() as connection:
        await bind_tenant_context(connection, TenantContext(projection.tenant_id))
        store = _ProjectionStore(connection, projection.tenant_id, projection.engagement_id)
        await store.publish(projection)


async def load_scope_projection(
    engine: AsyncEngine, *, tenant_id: str, engagement_id: UUID
) -> domain.ProjectionRead:
    async with engine.connect() as acquired:
        connection = await acquired.execution_options(isolation_level="REPEATABLE READ")
        async with connection.begin():
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            await bind_tenant_context(connection, TenantContext(tenant_id))
            return await _ProjectionStore(connection, tenant_id, engagement_id).read()
