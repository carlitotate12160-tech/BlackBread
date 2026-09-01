from dataclasses import dataclass
from uuid import UUID

from blackbread.graph.domain import GraphProjectionError
from blackbread.graph.revision import ScopeRevision
from blackbread.graph.temporal import (
    TEMPORAL_PROJECTOR_VERSION,
    TemporalLineage,
    validate_temporal_lineage,
)
from blackbread.ledger.catalog import SCOPE_CANONICALIZATION_VERSION
from blackbread.ledger.errors import LedgerValidationError
from blackbread.ledger.hashing import canonical_json, canonical_timestamp, sha256_hex

TEMPORAL_STATE_ROOT_VERSION = 2
_DOMAIN = "blackbread.graph.temporal-scope-projection.state-root"


@dataclass(frozen=True, slots=True)
class TemporalStateRootVersions:
    state_root_version: int = TEMPORAL_STATE_ROOT_VERSION
    projector_version: int = TEMPORAL_PROJECTOR_VERSION
    scope_canonicalization_version: int = SCOPE_CANONICALIZATION_VERSION


SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS = TemporalStateRootVersions()


def _revision_state(revision: ScopeRevision) -> list[object]:
    return [
        revision.revision_id,
        revision.node_id,
        revision.scope_kind,
        revision.canonical_value,
        revision.manifest_hash,
        canonical_timestamp(revision.valid_from),
        canonical_timestamp(revision.valid_until),
        revision.source_sequence,
        revision.source_event_hash,
        revision.source_schema_name,
        revision.source_schema_version,
        revision.predecessor_attestation_event_hash,
    ]


def _stable_scope_roots(lineage: TemporalLineage) -> list[list[str]]:
    identities: dict[str, list[str]] = {}
    for revision in lineage.revisions:
        identity = [revision.node_id, revision.scope_kind, revision.canonical_value]
        if identities.setdefault(revision.node_id, identity) != identity:
            raise GraphProjectionError("stable ScopeRoot identity collision")
    return [identities[node_id] for node_id in sorted(identities)]


def _state_root_v2_preimage(
    tenant_id: str,
    engagement_id: UUID,
    lineage: TemporalLineage,
    versions: TemporalStateRootVersions,
) -> list[object]:
    revisions = sorted(
        lineage.revisions,
        key=lambda item: (
            item.source_sequence,
            item.source_event_hash,
            item.node_id,
            item.revision_id,
        ),
    )
    return [
        _DOMAIN,
        [
            ["state_root_version", versions.state_root_version],
            ["projector_version", versions.projector_version],
            ["scope_canonicalization_version", versions.scope_canonicalization_version],
            ["tenant_id", tenant_id],
            ["engagement_id", str(engagement_id)],
        ],
        ["scope_roots", _stable_scope_roots(lineage)],
        ["revisions", [_revision_state(revision) for revision in revisions]],
        ["lineage_head_hash", lineage.lineage_head_hash],
    ]


def _compute_temporal_state_root(
    tenant_id: str,
    engagement_id: UUID,
    lineage: TemporalLineage,
    versions: TemporalStateRootVersions,
) -> str:
    return sha256_hex(
        canonical_json(_state_root_v2_preimage(tenant_id, engagement_id, lineage, versions))
    )


def _validate_versions(versions: object) -> TemporalStateRootVersions:
    if not isinstance(versions, TemporalStateRootVersions):
        raise GraphProjectionError("invalid temporal state-root version header")
    if (
        type(versions.state_root_version) is not int
        or versions.state_root_version != TEMPORAL_STATE_ROOT_VERSION
    ):
        raise GraphProjectionError("unsupported temporal state-root version")
    if (
        type(versions.projector_version) is not int
        or versions.projector_version != TEMPORAL_PROJECTOR_VERSION
    ):
        raise GraphProjectionError("unsupported temporal projector version")
    if (
        type(versions.scope_canonicalization_version) is not int
        or versions.scope_canonicalization_version != SCOPE_CANONICALIZATION_VERSION
    ):
        raise GraphProjectionError("unsupported scope canonicalization version")
    return versions


def compute_temporal_state_root(
    tenant_id: str,
    engagement_id: UUID,
    lineage: TemporalLineage,
    *,
    versions: TemporalStateRootVersions = SUPPORTED_TEMPORAL_STATE_ROOT_VERSIONS,
) -> str:
    supported = _validate_versions(versions)
    invalid_tenant = (
        not isinstance(tenant_id, str)
        or not tenant_id
        or tenant_id != tenant_id.strip()
        or "\x00" in tenant_id
    )
    if invalid_tenant or not isinstance(engagement_id, UUID):
        raise GraphProjectionError("invalid projection binding")
    if not isinstance(lineage, TemporalLineage):
        raise GraphProjectionError("invalid temporal lineage")
    validated = validate_temporal_lineage(
        lineage.revisions, lineage_head_hash=lineage.lineage_head_hash
    )
    if validated != lineage:
        raise GraphProjectionError("temporal lineage is not canonical")
    try:
        return _compute_temporal_state_root(tenant_id, engagement_id, validated, supported)
    except LedgerValidationError as exc:
        raise GraphProjectionError("state-root preimage is not canonical") from exc
