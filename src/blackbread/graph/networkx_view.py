from dataclasses import asdict
from types import MappingProxyType

import networkx as nx

from blackbread.graph.domain import ScopeProjection
from blackbread.graph.temporal_projection import (
    TemporalProjection,
    validate_temporal_projection,
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
            "verified_event_count": projection.verified_event_count,
            "verified_head_hash": projection.verified_head_hash,
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
