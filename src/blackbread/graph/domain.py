import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Literal, NamedTuple, cast
from uuid import UUID

from blackbread.ledger.catalog import (
    EngagementAttested,
    EngagementScope,
    EngagementStopped,
    default_registry,
)
from blackbread.ledger.errors import LedgerValidationError
from blackbread.ledger.event import AgentEvent
from blackbread.ledger.hashing import canonical_json, canonical_timestamp, sha256_hex

PROJECTOR_VERSION = 1
STATE_ROOT_VERSION = 1
ScopeKind = Literal["root_domain", "exact_host", "exact_address", "cloud_tenant"]
_SCOPE_FIELDS: dict[ScopeKind, str] = {
    "root_domain": "root_domains",
    "exact_host": "exact_hosts",
    "exact_address": "exact_addresses",
    "cloud_tenant": "cloud_tenants",
}
_HEX = re.compile(r"^[0-9a-f]{64}$")


class GraphProjectionError(RuntimeError):
    pass


class ProjectionNotFoundError(GraphProjectionError):
    pass


def canonical_scope_value(kind: str, value: str) -> tuple[ScopeKind, str]:
    canonical_kind = cast(ScopeKind, kind)
    field = _SCOPE_FIELDS.get(canonical_kind)
    if field is None:
        raise GraphProjectionError("unsupported ScopeRoot kind")
    try:
        scope = EngagementScope.model_validate({field: (value,)}, strict=True)
    except ValueError as exc:
        raise GraphProjectionError("invalid canonical ScopeRoot value") from exc
    return canonical_kind, cast(tuple[str, ...], getattr(scope, field))[0]


def scope_root_id(kind: str, value: str) -> str:
    kind, value = canonical_scope_value(kind, value)
    identity = {"family": "ScopeRoot", "kind": kind, "value": value, "version": 1}
    return sha256_hex("blackbread.graph.scope-root.identity\x00" + canonical_json(identity))


@dataclass(frozen=True, slots=True)
class ScopeRoot:
    node_id: str
    scope_kind: ScopeKind
    canonical_value: str
    manifest_hash: str
    valid_from: datetime
    valid_until: datetime
    source_sequence: int
    source_event_hash: str
    node_family: Literal["ScopeRoot"] = "ScopeRoot"
    authority: Literal["attested_scope"] = "attested_scope"
    source_schema_name: Literal["engagement.attested"] = "engagement.attested"
    source_schema_version: Literal[1] = 1


@dataclass(frozen=True, slots=True)
class ScopeProjection:
    tenant_id: str
    engagement_id: UUID
    verified_event_count: int
    verified_head_hash: str
    state_root: str
    nodes: tuple[ScopeRoot, ...]
    ledger_hash_algorithm: ClassVar[str] = "sha256"
    ledger_hash_version: ClassVar[int] = 1
    projector_version: ClassVar[int] = PROJECTOR_VERSION
    state_root_version: ClassVar[int] = STATE_ROOT_VERSION


class ProjectionRead(NamedTuple):
    projection: ScopeProjection
    is_current: bool


def _node_state(node: ScopeRoot) -> list[object]:
    if node.node_id != scope_root_id(node.scope_kind, node.canonical_value):
        raise GraphProjectionError("ScopeRoot identity is not canonical")
    invalid_source = node.source_sequence < 1 or _HEX.fullmatch(node.source_event_hash) is None
    invalid_authority = (
        node.valid_until <= node.valid_from or _HEX.fullmatch(node.manifest_hash) is None
    )
    if invalid_source or invalid_authority:
        raise GraphProjectionError("ScopeRoot provenance is invalid")
    validity = [canonical_timestamp(node.valid_from), canonical_timestamp(node.valid_until)]
    return [
        [node.node_id, node.scope_kind, node.canonical_value],
        [node.manifest_hash, *validity],
        [node.source_sequence, node.source_event_hash],
        [node.node_family, node.authority, node.source_schema_name, node.source_schema_version],
    ]


def compute_state_root(
    tenant_id: str,
    engagement_id: UUID,
    nodes: Iterable[ScopeRoot],
    *,
    projector_version: int = PROJECTOR_VERSION,
    version: int = STATE_ROOT_VERSION,
) -> str:
    if projector_version != PROJECTOR_VERSION:
        raise GraphProjectionError("unsupported projector version")
    if version != STATE_ROOT_VERSION:
        raise GraphProjectionError("unsupported state-root version")
    ordered = sorted((_node_state(node) for node in nodes), key=lambda node: str(node[0]))
    if len({str(node[0]) for node in ordered}) != len(ordered):
        raise GraphProjectionError("duplicate ScopeRoot identity")
    header = [version, projector_version, tenant_id, str(engagement_id)]
    state = ["blackbread.graph.scope-projection.state-root", header, ordered]
    return sha256_hex(canonical_json(state))


class ScopeProjector:
    def __init__(self, *, version: int = PROJECTOR_VERSION) -> None:
        if version != PROJECTOR_VERSION:
            raise GraphProjectionError("unsupported projector version")
        self._binding: tuple[str, object] | None = None
        self._nodes: tuple[ScopeRoot, ...] = ()

    @property
    def nodes(self) -> tuple[ScopeRoot, ...]:
        return self._nodes

    def consume(self, event: AgentEvent) -> None:
        binding = event.tenant_id, event.engagement_id
        if self._binding is not None and binding != self._binding:
            raise GraphProjectionError("ledger event binding changed during replay")
        try:
            registry = default_registry()
            payload = registry.parse(event.schema_name, event.schema_version, event.payload)
        except LedgerValidationError as exc:
            raise GraphProjectionError("unsupported schema or malformed payload") from exc
        if isinstance(payload, EngagementStopped):
            if not self._nodes:
                raise GraphProjectionError("stop precedes attestation")
            self._binding = binding
            return
        if not isinstance(payload, EngagementAttested):
            raise GraphProjectionError("unsupported graph event schema")
        if self._nodes:
            raise GraphProjectionError("multiple attestations lack supersession semantics")
        manifest = payload.manifest_hash
        window = payload.valid_from, payload.expires_at
        source = event.sequence, event.event_hash
        roots = (
            ScopeRoot(scope_root_id(kind, value), kind, value, manifest, *window, *source)
            for kind, field in _SCOPE_FIELDS.items()
            for value in getattr(payload.scope, field)
        )
        self._nodes = tuple(sorted(roots, key=lambda node: node.node_id))
        self._binding = binding
