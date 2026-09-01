import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import pairwise

from blackbread.graph.domain import GraphProjectionError, ScopeRoot, scope_root_id
from blackbread.graph.revision import ScopeRevision
from blackbread.ledger.errors import LedgerValidationError
from blackbread.ledger.hashing import canonical_timestamp

TEMPORAL_PROJECTOR_VERSION = 2
_HEX = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AttestationGroup:
    source_event_hash: str
    source_sequence: int
    valid_from: datetime
    valid_until: datetime
    predecessor_attestation_event_hash: str | None
    revisions: tuple[ScopeRevision, ...]


@dataclass(frozen=True, slots=True)
class TemporalLineage:
    groups: tuple[AttestationGroup, ...]
    lineage_head_hash: str

    @property
    def revisions(self) -> tuple[ScopeRevision, ...]:
        return tuple(revision for group in self.groups for revision in group.revisions)


@dataclass(frozen=True, slots=True)
class TemporalSelection:
    as_of: datetime
    effective_attestation_event_hash: str | None
    effective_nodes: tuple[ScopeRoot, ...]

    @property
    def has_effective_authority(self) -> bool:
        return self.effective_attestation_event_hash is not None


def _canonical_instant(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise GraphProjectionError(f"{label} must be a timezone-aware datetime")
    try:
        canonical_timestamp(value)
        return value.astimezone(UTC)
    except (LedgerValidationError, OverflowError, TypeError, ValueError) as exc:
        message = f"{label} must be a canonically normalizable timezone-aware time"
        raise GraphProjectionError(message) from exc


def _is_hex_digest(value: object) -> bool:
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _validate_revision(revision: ScopeRevision) -> None:
    predecessor = revision.predecessor_attestation_event_hash
    if any(
        not _is_hex_digest(value) for value in (revision.source_event_hash, revision.manifest_hash)
    ):
        raise GraphProjectionError("revision provenance hash is invalid")
    if predecessor is not None and not _is_hex_digest(predecessor):
        raise GraphProjectionError("revision predecessor hash is invalid")
    invalid_identity = not all(
        isinstance(value, str)
        for value in (revision.node_id, revision.scope_kind, revision.canonical_value)
    )
    if invalid_identity:
        raise GraphProjectionError("revision ScopeRoot identity is invalid")
    if revision.node_id != scope_root_id(revision.scope_kind, revision.canonical_value):
        raise GraphProjectionError("revision ScopeRoot identity is not canonical")
    valid_from = _canonical_instant(revision.valid_from, "revision timestamp")
    valid_until = _canonical_instant(revision.valid_until, "revision timestamp")
    if valid_until <= valid_from:
        raise GraphProjectionError("revision validity interval is invalid")
    expected_version = 1 if predecessor is None else 2
    invalid_source = (
        type(revision.source_sequence) is not int
        or revision.source_sequence < 1
        or revision.source_schema_name != "engagement.attested"
        or type(revision.source_schema_version) is not int
    )
    if invalid_source or revision.source_schema_version != expected_version:
        raise GraphProjectionError("revision attestation source is unsupported")
    if not _is_hex_digest(revision.revision_id):
        raise GraphProjectionError("revision identity hash is invalid")
    if revision.revision_id != replace(revision).revision_id:
        raise GraphProjectionError("revision identity does not match immutable fields")


def _group(event_hash: str, revisions: list[ScopeRevision]) -> AttestationGroup:
    first = revisions[0]
    metadata = {
        (
            item.source_sequence,
            item.source_schema_name,
            item.source_schema_version,
            item.manifest_hash,
            canonical_timestamp(item.valid_from),
            canonical_timestamp(item.valid_until),
            item.predecessor_attestation_event_hash,
        )
        for item in revisions
    }
    if len(metadata) != 1:
        raise GraphProjectionError("inconsistent attestation group metadata")
    if len({item.node_id for item in revisions}) != len(revisions):
        raise GraphProjectionError("duplicate membership in attestation group")
    ordered = tuple(sorted(revisions, key=lambda item: (item.node_id, item.revision_id)))
    return AttestationGroup(
        event_hash,
        first.source_sequence,
        _canonical_instant(first.valid_from, "revision timestamp"),
        _canonical_instant(first.valid_until, "revision timestamp"),
        first.predecessor_attestation_event_hash,
        ordered,
    )


def _validate_chain(groups: tuple[AttestationGroup, ...], lineage_head_hash: str) -> None:
    known = {group.source_event_hash for group in groups}
    missing = any(group.predecessor_attestation_event_hash not in known for group in groups[1:])
    if missing or groups[0].predecessor_attestation_event_hash is not None:
        raise GraphProjectionError("attestation lineage has a missing predecessor group")
    for predecessor, successor in pairwise(groups):
        if successor.predecessor_attestation_event_hash != predecessor.source_event_hash:
            raise GraphProjectionError("attestation lineage is not linear")
        if successor.valid_from < predecessor.valid_from:
            raise GraphProjectionError("successor valid_from regressed")
    if lineage_head_hash != groups[-1].source_event_hash:
        raise GraphProjectionError("lineage head is not the admitted structural head")


def validate_temporal_lineage(
    revisions: Iterable[ScopeRevision], *, lineage_head_hash: str
) -> TemporalLineage:
    materialized = tuple(revisions)
    if not materialized:
        raise GraphProjectionError("no attestation revisions")
    if not _is_hex_digest(lineage_head_hash):
        raise GraphProjectionError("lineage head hash is invalid")
    for revision in materialized:
        if not isinstance(revision, ScopeRevision):
            raise GraphProjectionError("temporal lineage contains an invalid revision")
        _validate_revision(revision)
    if len({item.revision_id for item in materialized}) != len(materialized):
        raise GraphProjectionError("duplicate revision identity")
    members: dict[str, list[ScopeRevision]] = {}
    for revision in materialized:
        members.setdefault(revision.source_event_hash, []).append(revision)
    groups = tuple(
        sorted(
            (_group(event_hash, group) for event_hash, group in members.items()),
            key=lambda item: (item.source_sequence, item.source_event_hash),
        )
    )
    if len({group.source_sequence for group in groups}) != len(groups):
        raise GraphProjectionError("attestation groups have duplicate source sequences")
    _validate_chain(groups, lineage_head_hash)
    return TemporalLineage(groups, lineage_head_hash)


def _nodes(group: AttestationGroup) -> tuple[ScopeRoot, ...]:
    return tuple(
        ScopeRoot(
            revision.node_id,
            revision.scope_kind,
            revision.canonical_value,
            revision.manifest_hash,
            revision.valid_from,
            revision.valid_until,
            revision.source_sequence,
            revision.source_event_hash,
            source_schema_version=revision.source_schema_version,
        )
        for revision in group.revisions
    )


def _select_from_lineage(lineage: TemporalLineage, *, as_of: datetime) -> TemporalSelection:
    instant = _canonical_instant(as_of, "as_of")
    activated = tuple(group for group in lineage.groups if group.valid_from <= instant)
    if not activated or instant >= activated[-1].valid_until:
        return TemporalSelection(instant, None, ())
    selected = activated[-1]
    return TemporalSelection(instant, selected.source_event_hash, _nodes(selected))


def select_temporal_scope(
    revisions: Iterable[ScopeRevision], *, as_of: datetime, lineage_head_hash: str
) -> TemporalSelection:
    lineage = validate_temporal_lineage(revisions, lineage_head_hash=lineage_head_hash)
    return _select_from_lineage(lineage, as_of=as_of)
