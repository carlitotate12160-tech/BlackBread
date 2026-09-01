from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from blackbread.graph.domain import GraphProjectionError, ScopeRoot
from blackbread.graph.revision import ScopeRevision
from blackbread.graph.state_root import (
    TemporalStateRootVersions,
    compute_temporal_state_root,
)
from blackbread.graph.temporal import (
    TemporalLineage,
    select_temporal_scope,
)


@dataclass(frozen=True, slots=True)
class TemporalProjection:
    tenant_id: str
    engagement_id: UUID
    lineage: TemporalLineage
    state_root: str
    versions: TemporalStateRootVersions
    as_of: datetime
    effective_attestation_event_hash: str | None
    effective_nodes: tuple[ScopeRoot, ...]

    @property
    def lineage_head_hash(self) -> str:
        return self.lineage.lineage_head_hash

    @property
    def revisions(self) -> tuple[ScopeRevision, ...]:
        return self.lineage.revisions

    @property
    def has_effective_authority(self) -> bool:
        return self.effective_attestation_event_hash is not None


def _node_membership(nodes: object) -> dict[str, ScopeRoot]:
    if not isinstance(nodes, tuple):
        raise GraphProjectionError("temporal projection effective nodes are invalid")
    membership: dict[str, ScopeRoot] = {}
    for node in nodes:
        invalid = (
            not isinstance(node, ScopeRoot)
            or not isinstance(node.node_id, str)
            or node.node_id in membership
        )
        if invalid:
            raise GraphProjectionError("temporal projection effective nodes are invalid")
        membership[node.node_id] = node
    return membership


def validate_temporal_projection(projection: object) -> TemporalProjection:
    if not isinstance(projection, TemporalProjection):
        raise GraphProjectionError("invalid temporal projection")
    try:
        expected_root = compute_temporal_state_root(
            projection.tenant_id,
            projection.engagement_id,
            projection.lineage,
            versions=projection.versions,
        )
        selection = select_temporal_scope(
            projection.lineage.revisions,
            as_of=projection.as_of,
            lineage_head_hash=projection.lineage_head_hash,
        )
    except GraphProjectionError:
        raise
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        raise GraphProjectionError("invalid temporal projection") from exc
    if projection.state_root != expected_root:
        raise GraphProjectionError("temporal projection state root is inconsistent")
    canonical_as_of = (
        projection.as_of == selection.as_of and projection.as_of.utcoffset() == timedelta(0)
    )
    if not canonical_as_of:
        raise GraphProjectionError("temporal projection as_of is not canonical")
    if projection.effective_attestation_event_hash != selection.effective_attestation_event_hash:
        raise GraphProjectionError("temporal projection effective attestation is inconsistent")
    if _node_membership(projection.effective_nodes) != _node_membership(selection.effective_nodes):
        raise GraphProjectionError("temporal projection effective nodes are inconsistent")
    return projection
