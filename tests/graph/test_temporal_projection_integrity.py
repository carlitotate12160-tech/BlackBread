from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from blackbread.graph.domain import GraphProjectionError, scope_root_id
from blackbread.graph.networkx_view import build_temporal_networkx_view
from blackbread.graph.revision import ScopeRevision
from blackbread.graph.state_root import (
    SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
    compute_temporal_state_root,
)
from blackbread.graph.temporal import select_temporal_scope, validate_temporal_lineage
from blackbread.graph.temporal_projection import TemporalProjection

_START = datetime(2026, 1, 1, tzinfo=UTC)
_TENANT = "tenant-a"
_ENGAGEMENT = UUID(int=100)


def _revision(
    event_hash: str,
    sequence: int,
    value: str,
    valid_from: datetime,
    provenance: tuple[str | None, int],
) -> ScopeRevision:
    predecessor, schema_version = provenance
    return ScopeRevision(
        node_id=scope_root_id("root_domain", value),
        scope_kind="root_domain",
        canonical_value=value,
        manifest_hash=f"{sequence:x}" * 64,
        valid_from=valid_from,
        valid_until=valid_from + timedelta(days=10),
        source_sequence=sequence,
        source_event_hash=event_hash,
        source_schema_name="engagement.attested",
        source_schema_version=schema_version,
        predecessor_attestation_event_hash=predecessor,
    )


def _projection() -> TemporalProjection:
    first_hash = "1" * 64
    second_hash = "2" * 64
    revisions = (
        _revision(
            first_hash,
            1,
            "historical.example",
            _START,
            (None, 1),
        ),
        _revision(
            second_hash,
            2,
            "effective.example",
            _START + timedelta(days=2),
            (first_hash, 2),
        ),
    )
    lineage = validate_temporal_lineage(revisions, lineage_head_hash=second_hash)
    selection = select_temporal_scope(
        lineage.revisions,
        as_of=_START + timedelta(days=3),
        lineage_head_hash=lineage.lineage_head_hash,
    )
    return TemporalProjection(
        tenant_id=_TENANT,
        engagement_id=_ENGAGEMENT,
        verified_event_count=2,
        verified_head_hash=second_hash,
        lineage=lineage,
        state_root=compute_temporal_state_root(_TENANT, _ENGAGEMENT, lineage),
        versions=SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
        as_of=selection.as_of,
        effective_attestation_event_hash=selection.effective_attestation_event_hash,
        effective_nodes=selection.effective_nodes,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state_root", "f" * 64),
        ("effective_attestation_event_hash", "f" * 64),
        ("effective_nodes", ()),
        ("verified_event_count", 1),
        ("verified_head_hash", "bad"),
    ],
)
def test_temporal_networkx_view_rejects_inconsistent_projection(field: str, value: object) -> None:
    forged = replace(_projection(), **{field: value})

    with pytest.raises(GraphProjectionError):
        build_temporal_networkx_view(forged)


def test_temporal_networkx_view_rejects_injected_historical_node() -> None:
    projection = _projection()
    historical = select_temporal_scope(
        projection.revisions,
        as_of=_START,
        lineage_head_hash=projection.lineage_head_hash,
    )
    forged = replace(projection, effective_nodes=historical.effective_nodes)

    with pytest.raises(GraphProjectionError, match="effective nodes"):
        build_temporal_networkx_view(forged)


def test_temporal_networkx_view_accepts_order_independent_effective_membership() -> None:
    projection = _projection()
    extra = replace(
        projection.effective_nodes[0],
        node_id=scope_root_id("root_domain", "second-effective.example"),
        canonical_value="second-effective.example",
    )
    group = projection.lineage.groups[-1]
    revision = _revision(
        group.source_event_hash,
        group.source_sequence,
        "second-effective.example",
        group.valid_from,
        (group.predecessor_attestation_event_hash, 2),
    )
    lineage = validate_temporal_lineage(
        (*projection.revisions, revision), lineage_head_hash=projection.lineage_head_hash
    )
    selection = select_temporal_scope(
        lineage.revisions,
        as_of=projection.as_of,
        lineage_head_hash=lineage.lineage_head_hash,
    )
    expanded = replace(
        projection,
        lineage=lineage,
        state_root=compute_temporal_state_root(_TENANT, _ENGAGEMENT, lineage),
        effective_nodes=tuple(reversed(selection.effective_nodes)),
    )

    graph = build_temporal_networkx_view(expanded)

    assert set(graph.nodes) == {extra.node_id, projection.effective_nodes[0].node_id}
