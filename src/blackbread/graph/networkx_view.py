from dataclasses import asdict
from types import MappingProxyType

import networkx as nx

from blackbread.graph.domain import ScopeProjection

_GRAPH_FIELDS = tuple(field for field in ScopeProjection.__annotations__ if field != "nodes")


def build_networkx_view(projection: ScopeProjection) -> "nx.DiGraph[str]":
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.graph.update({field: getattr(projection, field) for field in _GRAPH_FIELDS})
    binding = {"tenant_id": projection.tenant_id, "engagement_id": projection.engagement_id}
    for node in projection.nodes:
        graph.add_node(node.node_id, **binding, **asdict(node))
    object.__setattr__(graph, "graph", MappingProxyType(graph.graph))
    nodes = {key: MappingProxyType(value) for key, value in vars(graph)["_node"].items()}
    object.__setattr__(graph, "_node", MappingProxyType(nodes))
    nx.freeze(graph)
    return graph
