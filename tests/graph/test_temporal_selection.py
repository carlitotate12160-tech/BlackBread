from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from blackbread.graph.domain import GraphProjectionError, scope_root_id
from blackbread.graph.revision import ScopeRevision
from blackbread.graph.temporal import (
    TEMPORAL_PROJECTOR_VERSION,
    select_temporal_scope,
    validate_temporal_lineage,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)


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


def _chain(
    *,
    first_until: datetime = _START + timedelta(days=10),
    second_from: datetime = _START + timedelta(days=5),
    second_until: datetime = _START + timedelta(days=15),
) -> tuple[ScopeRevision, ScopeRevision]:
    first_hash = "1" * 64
    return (
        _revision(first_hash, 1, "first.example", (_START, first_until)),
        _revision(
            "2" * 64,
            2,
            "second.example",
            (second_from, second_until),
            (first_hash, 2, "a" * 64),
        ),
    )


def _select(revisions: tuple[ScopeRevision, ...], as_of: datetime):
    return select_temporal_scope(
        revisions, as_of=as_of, lineage_head_hash=revisions[-1].source_event_hash
    )


def test_half_open_selection_includes_valid_from_and_excludes_valid_until() -> None:
    revision = _revision("1" * 64, 1, "example.com")

    included = _select((revision,), revision.valid_from)
    excluded = _select((revision,), revision.valid_until)

    assert included.has_effective_authority is True
    assert included.effective_attestation_event_hash == revision.source_event_hash
    assert {node.canonical_value for node in included.effective_nodes} == {"example.com"}
    assert excluded.has_effective_authority is False
    assert excluded.effective_attestation_event_hash is None
    assert excluded.effective_nodes == ()


def test_predecessor_remains_effective_before_future_successor() -> None:
    revisions = _chain(second_from=_START + timedelta(days=8))

    selected = _select(revisions, _START + timedelta(days=6))

    assert selected.effective_attestation_event_hash == "1" * 64
    assert {node.canonical_value for node in selected.effective_nodes} == {"first.example"}


def test_gap_exists_only_when_no_attestation_covers_as_of() -> None:
    revisions = _chain(
        first_until=_START + timedelta(days=4),
        second_from=_START + timedelta(days=8),
    )

    selected = _select(revisions, _START + timedelta(days=6))

    assert selected.has_effective_authority is False
    assert selected.effective_attestation_event_hash is None


def test_superseded_revision_never_reactivates_after_successor_valid_from() -> None:
    revisions = _chain(
        first_until=_START + timedelta(days=30),
        second_from=_START + timedelta(days=5),
        second_until=_START + timedelta(days=8),
    )

    selected = _select(revisions, _START + timedelta(days=10))

    assert selected.has_effective_authority is False
    assert selected.effective_nodes == ()


def test_expired_activated_head_returns_empty_effective_authority() -> None:
    revisions = _chain(second_until=_START + timedelta(days=7))

    selected = _select(revisions, _START + timedelta(days=7))

    assert selected.has_effective_authority is False
    assert selected.effective_attestation_event_hash is None


def test_overlapping_intervals_transition_at_successor_valid_from() -> None:
    revisions = _chain(second_from=_START + timedelta(days=5))

    before = _select(revisions, _START + timedelta(days=4))
    after = _select(revisions, _START + timedelta(days=5))

    assert before.effective_attestation_event_hash == "1" * 64
    assert after.effective_attestation_event_hash == "2" * 64


def test_equal_valid_from_selects_successor() -> None:
    revisions = _chain(second_from=_START)

    selected = _select(revisions, _START)

    assert selected.effective_attestation_event_hash == "2" * 64


def test_non_monotonic_successor_valid_from_fails_closed() -> None:
    revisions = _chain(second_from=_START - timedelta(seconds=1))

    with pytest.raises(GraphProjectionError, match="valid_from regressed"):
        _select(revisions, _START)


def test_naive_as_of_fails_closed() -> None:
    revision = _revision("1" * 64, 1, "example.com")

    with pytest.raises(GraphProjectionError, match="timezone-aware"):
        _select((revision,), datetime(2026, 1, 1))


def test_equivalent_timezone_offsets_select_identically() -> None:
    revisions = _chain()
    utc = _START + timedelta(days=6)
    offset = utc.astimezone(timezone(timedelta(hours=7)))

    assert _select(revisions, utc) == _select(revisions, offset)


def test_temporal_selection_is_deterministic_and_order_independent() -> None:
    revisions = _chain()
    as_of = _START + timedelta(days=6)

    first = _select(revisions, as_of)
    repeated = _select(revisions, as_of)
    reordered = select_temporal_scope(
        tuple(reversed(revisions)),
        as_of=as_of,
        lineage_head_hash="2" * 64,
    )

    assert first == repeated == reordered


def test_temporal_selection_returns_complete_attestation_membership() -> None:
    event_hash = "1" * 64
    revisions = (
        _revision(event_hash, 1, "one.example"),
        _revision(event_hash, 1, "two.example"),
    )

    selected = _select(revisions, _START)

    assert {node.canonical_value for node in selected.effective_nodes} == {
        "one.example",
        "two.example",
    }


def test_inconsistent_attestation_group_metadata_fails_closed() -> None:
    event_hash = "1" * 64
    revisions = (
        _revision(event_hash, 1, "one.example"),
        _revision(event_hash, 1, "two.example", provenance=(None, 1, "b" * 64)),
    )

    with pytest.raises(GraphProjectionError, match="inconsistent attestation group"):
        validate_temporal_lineage(revisions, lineage_head_hash=event_hash)


def test_missing_predecessor_group_fails_closed() -> None:
    revision = _revision(
        "2" * 64,
        2,
        "example.com",
        provenance=("1" * 64, 2, "a" * 64),
    )

    with pytest.raises(GraphProjectionError, match="missing predecessor"):
        validate_temporal_lineage((revision,), lineage_head_hash=revision.source_event_hash)


def test_duplicate_revision_data_fails_closed() -> None:
    revision = _revision("1" * 64, 1, "example.com")

    with pytest.raises(GraphProjectionError, match="duplicate revision"):
        validate_temporal_lineage(
            (revision, revision), lineage_head_hash=revision.source_event_hash
        )


def test_duplicate_attestation_membership_fails_closed() -> None:
    revision = _revision("1" * 64, 1, "example.com")
    duplicate = replace(revision)
    object.__setattr__(duplicate, "revision_id", "f" * 64)

    with pytest.raises(GraphProjectionError, match=r"revision identity|duplicate membership"):
        validate_temporal_lineage(
            (revision, duplicate), lineage_head_hash=revision.source_event_hash
        )


def test_lineage_head_must_be_an_admitted_group() -> None:
    revision = _revision("1" * 64, 1, "example.com")

    with pytest.raises(GraphProjectionError, match="lineage head"):
        validate_temporal_lineage((revision,), lineage_head_hash="f" * 64)


def test_empty_effective_authority_is_distinct_from_invalid_projection() -> None:
    revision = _revision("1" * 64, 1, "example.com")

    empty = _select((revision,), revision.valid_until)

    assert empty.has_effective_authority is False
    with pytest.raises(GraphProjectionError, match="no attestation revisions"):
        validate_temporal_lineage((), lineage_head_hash=revision.source_event_hash)


def test_temporal_domain_version_and_results_are_immutable() -> None:
    revision = _revision("1" * 64, 1, "example.com")
    lineage = validate_temporal_lineage((revision,), lineage_head_hash=revision.source_event_hash)
    selection = _select((revision,), revision.valid_from)

    assert TEMPORAL_PROJECTOR_VERSION == 2
    with pytest.raises(FrozenInstanceError):
        lineage.lineage_head_hash = "f" * 64
    with pytest.raises(FrozenInstanceError):
        selection.effective_attestation_event_hash = None


def test_duplicate_attestation_source_sequence_fails_closed() -> None:
    revisions = (
        _revision("1" * 64, 1, "one.example"),
        _revision("2" * 64, 1, "two.example"),
    )

    with pytest.raises(GraphProjectionError, match="duplicate source sequences"):
        validate_temporal_lineage(revisions, lineage_head_hash="2" * 64)


@pytest.mark.parametrize("field", ["source_event_hash", "manifest_hash"])
def test_malformed_revision_hash_fails_closed(field: str) -> None:
    revision = _revision("1" * 64, 1, "example.com")
    object.__setattr__(revision, field, "bad")

    with pytest.raises(GraphProjectionError, match="hash"):
        validate_temporal_lineage((revision,), lineage_head_hash="1" * 64)


def test_canonical_scope_identity_mismatch_fails_closed() -> None:
    revision = _revision("1" * 64, 1, "example.com")
    object.__setattr__(revision, "node_id", "f" * 64)

    with pytest.raises(GraphProjectionError, match="ScopeRoot identity"):
        validate_temporal_lineage((revision,), lineage_head_hash=revision.source_event_hash)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("manifest_hash", 7),
        ("source_event_hash", 7),
        ("predecessor_attestation_event_hash", 7),
        ("source_sequence", "1"),
        ("source_sequence", True),
        ("source_schema_version", True),
        ("valid_from", "bad"),
        ("node_id", 7),
    ],
)
def test_malformed_revision_field_types_fail_closed(field: str, value: object) -> None:
    revision = _revision("1" * 64, 1, "example.com")
    object.__setattr__(revision, field, value)

    with pytest.raises(GraphProjectionError):
        validate_temporal_lineage((revision,), lineage_head_hash="1" * 64)
