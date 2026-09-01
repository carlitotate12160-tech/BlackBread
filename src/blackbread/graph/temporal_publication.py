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


def validate_temporal_publication(pub: object) -> TemporalPublication:
    """Validate internal consistency of a TemporalPublication. Fail closed."""
    if not isinstance(pub, TemporalPublication):
        raise GraphProjectionError("invalid temporal publication")
    if not isinstance(pub.tenant_id, str) or not pub.tenant_id.strip():
        raise GraphProjectionError("invalid temporal publication tenant_id")
    if not isinstance(pub.engagement_id, UUID):
        raise GraphProjectionError("invalid temporal publication engagement_id")
    if not isinstance(pub.verified_event_count, int) or pub.verified_event_count < 1:
        raise GraphProjectionError("invalid temporal publication verified_event_count")
    if not _HEX64.fullmatch(pub.verified_head_hash or ""):
        raise GraphProjectionError("invalid temporal publication verified_head_hash")

    validate_temporal_lineage(
        pub.lineage.revisions, lineage_head_hash=pub.lineage.lineage_head_hash
    )
    if pub.versions != SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS:
        raise GraphProjectionError("unsupported temporal publication versions")
    if pub.state_root != compute_temporal_state_root(
        pub.tenant_id, pub.engagement_id, pub.lineage, versions=pub.versions
    ):
        raise GraphProjectionError("temporal publication state root is inconsistent")

    fg = pub.lineage.groups[-1]
    if fg.source_sequence > pub.verified_event_count:
        raise GraphProjectionError("lineage head exceeds verified anchor")
    expected_ids = {(r.node_id, r.scope_kind, r.canonical_value) for r in fg.revisions}
    if not isinstance(pub.structural_head_nodes, tuple) or len(pub.structural_head_nodes) != len(
        expected_ids
    ):
        raise GraphProjectionError("invalid structural head nodes")
    actual_ids: set[tuple[str, str, str]] = set()
    for n in pub.structural_head_nodes:
        if not isinstance(n, ScopeRoot):
            raise GraphProjectionError("invalid structural head node")
        iden = (n.node_id, n.scope_kind, n.canonical_value)
        if iden in actual_ids:
            raise GraphProjectionError("duplicate structural head node")
        actual_ids.add(iden)
    if actual_ids != expected_ids:
        raise GraphProjectionError("structural head nodes do not match lineage head")
    return pub
