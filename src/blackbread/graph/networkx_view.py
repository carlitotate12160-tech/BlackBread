from dataclasses import asdict
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncEngine

from blackbread.graph.domain import ScopeProjection
from blackbread.graph.temporal_projection import (
    TemporalProjection,
    validate_temporal_projection,
)
from blackbread.graph.temporal_reconstruction import (
    load_temporal_projection_as_of,
)

_GRAPH_FIELDS = tuple(field for field in ScopeProjection.__annotations__ if field != "nodes")


def _freeze(graph: "nx.DiGraph[str]") -> "nx.DiGraph[str]":
    object.__setattr__(graph, "graph", MappingProxyType(graph.graph))
    nodes = {key: MappingProxyType(value) for key, value in vars(graph)["_node"].items()}
    object.__setattr__(graph, "_node", MappingProxyType(nodes))
    nx.freeze(graph)
    return graph


def build_networkx_view(projection: ScopeProjection) -> "nx.DiGraph[str]":
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.graph.update({field: getattr(projection, field) for field in _GRAPH_FIELDS})
    binding = {"tenant_id": projection.tenant_id, "engagement_id": projection.engagement_id}
    for node in projection.nodes:
        graph.add_node(node.node_id, **binding, **asdict(node))
    return _freeze(graph)


def build_temporal_networkx_view(projection: TemporalProjection) -> "nx.DiGraph[str]":
    projection = validate_temporal_projection(projection)
    graph: nx.DiGraph[str] = nx.DiGraph()
    versions = projection.versions
    graph.graph.update(
        {
            "tenant_id": projection.tenant_id,
            "engagement_id": projection.engagement_id,
            "state_root": projection.state_root,
            "state_root_version": versions.state_root_version,
            "projector_version": versions.projector_version,
            "scope_canonicalization_version": versions.scope_canonicalization_version,
            "lineage_head_hash": projection.lineage_head_hash,
            "as_of": projection.as_of,
            "effective_attestation_event_hash": projection.effective_attestation_event_hash,
            "has_effective_authority": projection.has_effective_authority,
        }
    )
    binding = {"tenant_id": projection.tenant_id, "engagement_id": projection.engagement_id}
    for node in projection.effective_nodes:
        graph.add_node(node.node_id, **binding, **asdict(node))
    return _freeze(graph)


async def load_temporal_networkx_view_as_of(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    engagement_id: UUID,
    as_of: datetime,
) -> "nx.DiGraph[str] | None":
    projection = await load_temporal_projection_as_of(
        engine,
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        as_of=as_of,
    )
    if projection is None:
        return None
    return build_temporal_networkx_view(projection)
