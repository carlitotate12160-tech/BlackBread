from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple
from uuid import UUID

from blackbread.graph.domain import GraphProjectionError
from blackbread.graph.state_root import (
    SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
    TemporalStateRootVersions,
    compute_temporal_state_root,
)
from blackbread.graph.temporal import TemporalLineage, validate_temporal_lineage

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class TemporalPublication:
    tenant_id: str
    engagement_id: UUID
    verified_event_count: int
    verified_head_hash: str
    lineage: TemporalLineage
    state_root: str
    versions: TemporalStateRootVersions


class TemporalPublicationRead(NamedTuple):
    publication: TemporalPublication
    is_current: bool


def _validate_publication_identity(pub: TemporalPublication) -> None:
    if not isinstance(pub.tenant_id, str) or not pub.tenant_id.strip():
        raise GraphProjectionError("invalid temporal publication tenant_id")
    if not isinstance(pub.engagement_id, UUID):
        raise GraphProjectionError("invalid temporal publication engagement_id")
    if type(pub.verified_event_count) is not int or pub.verified_event_count < 1:
        raise GraphProjectionError("invalid temporal publication verified_event_count")
    if not _HEX64.fullmatch(pub.verified_head_hash or ""):
        raise GraphProjectionError("invalid temporal publication verified_head_hash")


def _validate_publication_lineage(pub: TemporalPublication) -> None:
    validate_temporal_lineage(
        pub.lineage.revisions, lineage_head_hash=pub.lineage.lineage_head_hash
    )
    head_group = pub.lineage.groups[-1]
    if head_group.source_sequence > pub.verified_event_count:
        raise GraphProjectionError("lineage head exceeds verified anchor")


def _validate_publication_state_root(pub: TemporalPublication) -> None:
    if pub.versions != SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS:
        raise GraphProjectionError("unsupported temporal publication versions")
    expected = compute_temporal_state_root(
        pub.tenant_id, pub.engagement_id, pub.lineage, versions=pub.versions
    )
    if pub.state_root != expected:
        raise GraphProjectionError("temporal publication state root is inconsistent")


def validate_temporal_publication(pub: object) -> TemporalPublication:
    if not isinstance(pub, TemporalPublication):
        raise GraphProjectionError("invalid temporal publication")
    _validate_publication_identity(pub)
    _validate_publication_lineage(pub)
    _validate_publication_state_root(pub)
    return pub
