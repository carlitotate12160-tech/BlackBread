from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from blackbread.graph.domain import GraphProjectionError, scope_root_id
from blackbread.graph.revision import ScopeRevision
from blackbread.graph.state_root import (
    SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
    _compute_temporal_state_root,
    _state_root_v2_preimage,
    compute_temporal_state_root,
)
from blackbread.graph.temporal import select_temporal_scope, validate_temporal_lineage

_START = datetime(2026, 1, 1, tzinfo=UTC)
_TENANT = "tenant-a"
_ENGAGEMENT = UUID(int=100)


def _revision(
    event: str,
    sequence: int,
    value: str,
    validity: tuple[datetime, datetime] = (_START, _START + timedelta(days=10)),
    provenance: tuple[str | None, int, str] = (None, 1, "a" * 64),
) -> ScopeRevision:
    predecessor, schema_version, manifest = provenance
    return ScopeRevision(
        node_id=scope_root_id("root_domain", value),
        scope_kind="root_domain",
        canonical_value=value,
        manifest_hash=manifest,
        valid_from=validity[0],
        valid_until=validity[1],
        source_sequence=sequence,
        source_event_hash=event,
        source_schema_name="engagement.attested",
        source_schema_version=schema_version,
        predecessor_attestation_event_hash=predecessor,
    )


def _history(
    first_members: tuple[str, ...] = ("first.example",),
    first_hash: str = "1" * 64,
    first_validity: tuple[datetime, datetime] = (_START, _START + timedelta(days=10)),
    manifests: tuple[str, str] = ("a" * 64, "b" * 64),
) -> tuple[ScopeRevision, ...]:
    first = tuple(
        _revision(first_hash, 1, value, first_validity, (None, 1, manifests[0]))
        for value in first_members
    )
    head = _revision(
        "2" * 64,
        2,
        "head.example",
        (_START + timedelta(days=5), _START + timedelta(days=15)),
        (first_hash, 2, manifests[1]),
    )
    return (*first, head)


def _lineage(revisions: tuple[ScopeRevision, ...], head: str = "2" * 64):
    return validate_temporal_lineage(revisions, lineage_head_hash=head)


def _root(revisions: tuple[ScopeRevision, ...], head: str = "2" * 64) -> str:
    return compute_temporal_state_root(_TENANT, _ENGAGEMENT, _lineage(revisions, head))


def test_state_root_v2_binds_full_supersession_history_not_only_head() -> None:
    first = _history(("historical-one.example",))
    second = _history(("historical-two.example",))
    as_of = _START + timedelta(days=6)

    first_effective = select_temporal_scope(first, as_of=as_of, lineage_head_hash="2" * 64)
    second_effective = select_temporal_scope(second, as_of=as_of, lineage_head_hash="2" * 64)

    assert first_effective.effective_nodes == second_effective.effective_nodes
    assert _root(first) != _root(second)


def test_state_root_v2_changes_for_predecessor_validity_provenance_and_removed_history() -> None:
    baseline = _history(("first.example", "removed.example"))
    alternatives = (
        _history(("first.example", "removed.example"), first_hash="3" * 64),
        _history(
            ("first.example", "removed.example"),
            first_validity=(_START, _START + timedelta(days=9)),
        ),
        _history(("first.example", "removed.example"), manifests=("c" * 64, "b" * 64)),
        _history(("first.example",)),
    )

    assert all(_root(baseline) != _root(alternative) for alternative in alternatives)


def test_state_root_v2_is_input_and_mapping_order_independent() -> None:
    history = _history(("first.example", "other.example"))
    reordered = tuple(
        ScopeRevision(
            **{
                field.name: getattr(revision, field.name)
                for field in reversed(fields(revision))
                if field.init
            }
        )
        for revision in reversed(history)
    )

    assert _root(history) == _root(reordered)


def test_state_root_v2_differs_when_canonicalization_version_differs() -> None:
    lineage = _lineage(_history())

    first = _compute_temporal_state_root(
        _TENANT,
        _ENGAGEMENT,
        lineage,
        replace(SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS, scope_canonicalization_version=1),
    )
    second = _compute_temporal_state_root(
        _TENANT,
        _ENGAGEMENT,
        lineage,
        replace(SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS, scope_canonicalization_version=2),
    )

    assert first != second


def test_state_root_v2_is_stable_across_as_of_queries_for_same_history() -> None:
    history = _history()
    before = select_temporal_scope(
        history, as_of=_START + timedelta(days=2), lineage_head_hash="2" * 64
    )
    after = select_temporal_scope(
        history, as_of=_START + timedelta(days=7), lineage_head_hash="2" * 64
    )
    lineage = _lineage(history)

    assert before.effective_nodes != after.effective_nodes
    assert compute_temporal_state_root(_TENANT, _ENGAGEMENT, lineage) == (
        compute_temporal_state_root(_TENANT, _ENGAGEMENT, lineage)
    )


def test_state_root_v2_preimage_shape_is_locked() -> None:
    preimage = _state_root_v2_preimage(
        _TENANT,
        _ENGAGEMENT,
        _lineage(_history()),
        SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
    )

    assert preimage[0] == "blackbread.graph.temporal-scope-projection.state-root"
    assert preimage[1] == [
        ["state_root_version", 2],
        ["projector_version", 2],
        ["scope_canonicalization_version", 1],
        ["tenant_id", _TENANT],
        ["engagement_id", str(_ENGAGEMENT)],
    ]
    assert [section[0] for section in preimage[2:]] == [
        "scope_roots",
        "revisions",
        "lineage_head_hash",
    ]


@pytest.mark.parametrize("version", [1, 3, True])
def test_state_root_v2_rejects_unsupported_state_root_version(version: object) -> None:
    versions = replace(SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS, state_root_version=version)
    with pytest.raises(GraphProjectionError, match="state-root version"):
        compute_temporal_state_root(_TENANT, _ENGAGEMENT, _lineage(_history()), versions=versions)


@pytest.mark.parametrize("version", [1, 3, True])
def test_state_root_v2_rejects_unsupported_projector_version(version: object) -> None:
    versions = replace(SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS, projector_version=version)
    with pytest.raises(GraphProjectionError, match="projector version"):
        compute_temporal_state_root(_TENANT, _ENGAGEMENT, _lineage(_history()), versions=versions)


def test_state_root_v2_rejects_unsupported_canonicalization_version() -> None:
    versions = replace(SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS, scope_canonicalization_version=2)
    with pytest.raises(GraphProjectionError, match="canonicalization version"):
        compute_temporal_state_root(_TENANT, _ENGAGEMENT, _lineage(_history()), versions=versions)


@pytest.mark.parametrize(
    ("tenant", "engagement"),
    [(7, _ENGAGEMENT), (_TENANT, "bad"), ("tenant\x00bad", _ENGAGEMENT)],
)
def test_state_root_v2_rejects_invalid_projection_binding(
    tenant: object, engagement: object
) -> None:
    with pytest.raises(GraphProjectionError, match="projection binding"):
        compute_temporal_state_root(tenant, engagement, _lineage(_history()))


def test_state_root_v2_rejects_forged_lineage() -> None:
    lineage = _lineage(_history())
    object.__setattr__(lineage, "lineage_head_hash", "f" * 64)

    with pytest.raises(GraphProjectionError, match="lineage head"):
        compute_temporal_state_root(_TENANT, _ENGAGEMENT, lineage)


def test_state_root_v2_changes_for_different_lineage_head() -> None:
    second = _history()
    third = _revision(
        "3" * 64,
        3,
        "third.example",
        (_START + timedelta(days=8), _START + timedelta(days=18)),
        ("2" * 64, 2, "c" * 64),
    )

    assert _root(second) != _root((*second, third), "3" * 64)


def test_state_root_v2_rejects_duplicate_revision_identity() -> None:
    lineage = _lineage(_history())
    group = lineage.groups[0]
    object.__setattr__(group, "revisions", (*group.revisions, group.revisions[0]))

    with pytest.raises(GraphProjectionError, match="duplicate revision"):
        compute_temporal_state_root(_TENANT, _ENGAGEMENT, lineage)


def test_state_root_v2_rejects_noncanonical_revision_identity() -> None:
    lineage = _lineage(_history())
    object.__setattr__(lineage.groups[0].revisions[0], "node_id", "f" * 64)

    with pytest.raises(GraphProjectionError, match="ScopeRoot identity"):
        compute_temporal_state_root(_TENANT, _ENGAGEMENT, lineage)


def test_state_root_v2_known_answer_vector_is_frozen() -> None:
    assert _root(_history(("first.example", "other.example"))) == (
        "0f5990b20fcdf3897d73ec85bb2fa4d6b953190d690b59ed748a1ad0d883b6c9"
    )
