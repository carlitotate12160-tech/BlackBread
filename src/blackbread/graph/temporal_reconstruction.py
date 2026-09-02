from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import NamedTuple
from uuid import UUID

from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine

from blackbread.graph.domain import GraphProjectionError
from blackbread.graph.revision import ScopeRevision
from blackbread.graph.state_root import (
    SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
    TemporalStateRootVersions,
    compute_temporal_state_root,
)
from blackbread.graph.temporal import (
    TEMPORAL_PROJECTOR_VERSION,
    TemporalLineage,
    select_temporal_scope,
    validate_temporal_lineage,
)
from blackbread.graph.temporal_persistence import (
    TemporalSnapshot,
    load_temporal_snapshot,
)
from blackbread.graph.temporal_projection import (
    TemporalProjection,
    validate_temporal_projection,
)
from blackbread.ledger.catalog import SCOPE_CANONICALIZATION_VERSION


def _revision_from_row(row: RowMapping) -> ScopeRevision:
    return ScopeRevision(
        node_id=row["node_id"],
        scope_kind=row["scope_kind"],
        canonical_value=row["canonical_value"],
        manifest_hash=row["manifest_hash"],
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        source_sequence=row["source_sequence"],
        source_event_hash=row["source_event_hash"],
        source_schema_name=row["source_schema_name"],
        source_schema_version=row["source_schema_version"],
        predecessor_attestation_event_hash=row["predecessor_attestation_event_hash"],
    )


def _verify_snapshot_versions(snap: RowMapping) -> None:
    checks = (
        ("ledger_hash_algorithm", "sha256"),
        ("ledger_hash_version", 1),
        (
            "temporal_projector_version",
            TEMPORAL_PROJECTOR_VERSION,
        ),
        (
            "state_root_version",
            SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS.state_root_version,
        ),
        (
            "scope_canonicalization_version",
            SCOPE_CANONICALIZATION_VERSION,
        ),
    )
    for field, expected in checks:
        if snap[field] != expected:
            raise GraphProjectionError(
                f"snapshot {field} mismatch: expected {expected}, got {snap[field]}"
            )


def _verify_head_membership(
    lineage: TemporalLineage,
    heads: list[RowMapping] | tuple[RowMapping, ...],
) -> None:
    final = lineage.groups[-1]
    expected = {(rev.node_id, rev.revision_id, final.source_event_hash) for rev in final.revisions}
    actual = {(h["node_id"], h["revision_id"], h["source_event_hash"]) for h in heads}
    if actual != expected:
        raise GraphProjectionError("reconstructed head membership does not match stored heads")


def _verify_stable_roots(
    lineage: TemporalLineage,
    roots: Sequence[RowMapping],
) -> None:
    expected = {
        (r.node_id, r.scope_kind, r.canonical_value) for g in lineage.groups for r in g.revisions
    }
    actual = {(r["node_id"], r["scope_kind"], r["canonical_value"]) for r in roots}
    if actual != expected:
        raise GraphProjectionError("reconstructed stable roots do not match lineage")


class ColdReconstruction(NamedTuple):
    lineage: TemporalLineage
    state_root: str
    versions: TemporalStateRootVersions
    verified_event_count: int
    verified_head_hash: str
    lineage_head_hash: str
    lineage_head_sequence: int


def _reconstruct(cold: TemporalSnapshot, expected_tenant_id: str) -> ColdReconstruction:
    snap = cold.snapshot
    if snap["tenant_id"] != expected_tenant_id:
        raise GraphProjectionError("snapshot tenant_id does not match requested tenant_id")
    _verify_snapshot_versions(snap)

    revisions = tuple(_revision_from_row(row) for row in cold.revisions)
    if not revisions:
        raise GraphProjectionError("no revisions in cold snapshot")

    lineage_head_hash: str = snap["lineage_head_hash"]
    lineage = validate_temporal_lineage(revisions, lineage_head_hash=lineage_head_hash)

    versions = SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS
    recomputed = compute_temporal_state_root(
        snap["tenant_id"],
        snap["engagement_id"],
        lineage,
        versions=versions,
    )
    stored_root: str = snap["state_root"]
    if recomputed != stored_root:
        raise GraphProjectionError("recomputed state-root v2 does not match stored snapshot")

    _verify_stable_roots(lineage, cold.roots)
    _verify_head_membership(lineage, list(cold.heads))

    expected_sequence = lineage.groups[-1].source_sequence
    if expected_sequence != snap["lineage_head_sequence"]:
        raise GraphProjectionError(
            f"lineage head sequence mismatch: expected {expected_sequence}, "
            f"got {snap['lineage_head_sequence']} in snapshot"
        )

    return ColdReconstruction(
        lineage=lineage,
        state_root=recomputed,
        versions=versions,
        verified_event_count=snap["verified_event_count"],
        verified_head_hash=snap["verified_head_hash"],
        lineage_head_hash=lineage_head_hash,
        lineage_head_sequence=expected_sequence,
    )


async def load_temporal_projection(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    engagement_id: UUID,
) -> ColdReconstruction | None:
    cold = await load_temporal_snapshot(engine, tenant_id=tenant_id, engagement_id=engagement_id)
    if cold is None:
        return None
    return _reconstruct(cold, expected_tenant_id=tenant_id)


async def load_temporal_projection_as_of(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    engagement_id: UUID,
    as_of: datetime,
) -> TemporalProjection | None:
    cold = await load_temporal_projection(engine, tenant_id=tenant_id, engagement_id=engagement_id)
    if cold is None:
        return None

    selection = select_temporal_scope(
        cold.lineage.revisions,
        as_of=as_of,
        lineage_head_hash=cold.lineage.lineage_head_hash,
    )

    projection = TemporalProjection(
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        lineage=cold.lineage,
        state_root=cold.state_root,
        versions=cold.versions,
        as_of=selection.as_of,
        effective_attestation_event_hash=selection.effective_attestation_event_hash,
        effective_nodes=selection.effective_nodes,
    )
    return validate_temporal_projection(projection)
