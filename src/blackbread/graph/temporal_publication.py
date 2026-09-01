"""Durable temporal publication contract.

Pure domain types for persisting a verified temporal projection.
No SQL, ledger replay, as_of selection, NetworkX, or authorization.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple
from uuid import UUID

from blackbread.graph.domain import GraphProjectionError, ScopeRoot
from blackbread.graph.state_root import (
    SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
    TemporalStateRootVersions,
    compute_temporal_state_root,
)
from blackbread.graph.temporal import TemporalLineage, validate_temporal_lineage

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class TemporalPublication:
    """Immutable durable publication binding a verified ledger anchor to a temporal lineage."""

    tenant_id: str
    engagement_id: UUID
    verified_event_count: int
    verified_head_hash: str
    lineage: TemporalLineage
    state_root: str
    versions: TemporalStateRootVersions
    structural_head_nodes: tuple[ScopeRoot, ...]


class TemporalPublicationRead(NamedTuple):
    """Wrap a publication with ledger freshness."""

    publication: TemporalPublication
    is_current: bool


def _validate_anchor(publication: TemporalPublication) -> None:
    if not isinstance(publication.tenant_id, str) or not publication.tenant_id.strip():
        raise GraphProjectionError("invalid temporal publication tenant_id")
    if not isinstance(publication.engagement_id, UUID):
        raise GraphProjectionError("invalid temporal publication engagement_id")
    count_ok = isinstance(publication.verified_event_count, int)
    if not count_ok or publication.verified_event_count < 1:
        raise GraphProjectionError("invalid temporal publication verified_event_count")
    if not _HEX64.fullmatch(publication.verified_head_hash or ""):
        raise GraphProjectionError("invalid temporal publication verified_head_hash")


def _validate_head_membership(publication: TemporalPublication) -> None:
    final_group = publication.lineage.groups[-1]
    if final_group.source_sequence > publication.verified_event_count:
        raise GraphProjectionError("lineage head exceeds verified anchor")
    expected_ids = {
        (r.node_id, r.scope_kind, r.canonical_value) for r in final_group.revisions
    }
    if not isinstance(publication.structural_head_nodes, tuple):
        raise GraphProjectionError("invalid structural head nodes")
    if len(publication.structural_head_nodes) != len(expected_ids):
        raise GraphProjectionError("structural head node count mismatch")
    actual_ids: set[tuple[str, str, str]] = set()
    for node in publication.structural_head_nodes:
        if not isinstance(node, ScopeRoot):
            raise GraphProjectionError("invalid structural head node")
        identity = (node.node_id, node.scope_kind, node.canonical_value)
        if identity in actual_ids:
            raise GraphProjectionError("duplicate structural head node")
        actual_ids.add(identity)
    if actual_ids != expected_ids:
        raise GraphProjectionError("structural head nodes do not match lineage head")


def validate_temporal_publication(publication: object) -> TemporalPublication:
    """Validate internal consistency of a TemporalPublication. Fail closed."""
    if not isinstance(publication, TemporalPublication):
        raise GraphProjectionError("invalid temporal publication")
    _validate_anchor(publication)
    validate_temporal_lineage(
        publication.lineage.revisions,
        lineage_head_hash=publication.lineage.lineage_head_hash,
    )
    if publication.versions != SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS:
        raise GraphProjectionError("unsupported temporal publication versions")
    expected_root = compute_temporal_state_root(
        publication.tenant_id,
        publication.engagement_id,
        publication.lineage,
        versions=publication.versions,
    )
    if publication.state_root != expected_root:
        raise GraphProjectionError("temporal publication state root is inconsistent")
    _validate_head_membership(publication)
    return publication
