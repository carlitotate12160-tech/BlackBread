"""M1 event shapes; these validate records but do not grant execution authority."""

from datetime import datetime
from functools import lru_cache
from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from blackbread.ledger.schema import EventPayload, EventRegistry
from blackbread.scope.canonical import ScopeKind, canonical_target_value
from blackbread.scope.canonical import canonical_address as _canonical_address
from blackbread.scope.canonical import canonical_domain as _canonical_domain
from blackbread.scope.canonical import canonical_text as _canonical_text

_HEX_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_MAX_SCOPE_ENTRIES = 500
SCOPE_CANONICALIZATION_VERSION = 1


def _sorted_unique(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{field} must be sorted and unique")
    return values


class ScopeExclusion(BaseModel):
    """A canonical exclusion with an explicit target interpretation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    target_type: ScopeKind
    value: str

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        canonical_target_value(self.target_type, self.value)
        return self


class EngagementScope(BaseModel):
    """Canonical snapshot of all positive scope and boundary dimensions."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    root_domains: tuple[str, ...] = ()
    exact_hosts: tuple[str, ...] = ()
    exact_addresses: tuple[str, ...] = ()
    cloud_tenants: tuple[str, ...] = ()
    exclusions: tuple[ScopeExclusion, ...] = ()
    third_party_boundaries: tuple[str, ...] = ()

    @field_validator("root_domains", "exact_hosts")
    @classmethod
    def validate_domains(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) > _MAX_SCOPE_ENTRIES:
            raise ValueError("domains has too many entries")
        canonical = tuple(_canonical_domain(value) for value in values)
        return _sorted_unique(canonical, "domains")

    @field_validator("exact_addresses")
    @classmethod
    def validate_addresses(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) > _MAX_SCOPE_ENTRIES:
            raise ValueError("exact_addresses has too many entries")
        canonical: list[str] = []
        for value in values:
            canonical.append(_canonical_address(value))
        return _sorted_unique(tuple(canonical), "exact_addresses")

    @field_validator("cloud_tenants", "third_party_boundaries")
    @classmethod
    def validate_opaque_scope_values(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(values) > _MAX_SCOPE_ENTRIES:
            raise ValueError("scope values has too many entries")
        canonical = tuple(_canonical_text(value, "scope value", 500) for value in values)
        return _sorted_unique(canonical, "scope values")

    @field_validator("exclusions")
    @classmethod
    def validate_exclusions(
        cls,
        values: tuple[ScopeExclusion, ...],
    ) -> tuple[ScopeExclusion, ...]:
        if len(values) > _MAX_SCOPE_ENTRIES:
            raise ValueError("exclusions has too many entries")
        keys = tuple((value.target_type, value.value) for value in values)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("exclusions must be sorted and unique")
        return values

    @model_validator(mode="after")
    def require_positive_scope(self) -> Self:
        if not (
            self.root_domains or self.exact_hosts or self.exact_addresses or self.cloud_tenants
        ):
            raise ValueError("attested scope must contain at least one positive scope entry")
        return self


class EngagementMode(BaseModel):
    """Complete immutable mode dimensions from the accepted engagement contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    knowledge: Literal["blind"]
    execution: Literal["covert"]
    tier: Literal["recon_only", "recon_validate", "full_kill_chain"]
    pacing: Literal["short", "long_low_and_slow"]


class EngagementAttested(EventPayload):
    SCHEMA_NAME: ClassVar[str] = "engagement.attested"
    SCHEMA_VERSION: ClassVar[int] = 1

    manifest_hash: str = Field(pattern=_HEX_DIGEST_PATTERN)
    manifest_signature_ref: str
    attested_by: str
    mode: EngagementMode
    scope: EngagementScope
    valid_from: datetime
    expires_at: datetime

    @field_validator("manifest_signature_ref", "attested_by")
    @classmethod
    def validate_identity_fields(cls, value: str) -> str:
        return _canonical_text(value, "attestation identity", 500)

    @field_validator("valid_from", "expires_at")
    @classmethod
    def validate_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("attestation validity timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_validity_window(self) -> Self:
        if self.expires_at <= self.valid_from:
            raise ValueError("attestation expiry must be after its start")
        return self


class EngagementAttestedV2(EngagementAttested):
    SCHEMA_VERSION: ClassVar[int] = 2

    supersedes_event_hash: str = Field(pattern=_HEX_DIGEST_PATTERN)


class EngagementStopped(EventPayload):
    SCHEMA_NAME: ClassVar[str] = "engagement.stopped"
    SCHEMA_VERSION: ClassVar[int] = 1

    reason: Literal[
        "operator_stop",
        "white_cell_stop",
        "service_instability",
        "target_identity_uncertain",
        "third_party_boundary",
        "real_incident_collision",
        "unexpected_sensitive_data",
        "operator_heartbeat_lost",
        "authorization_revoked",
        "scope_violation",
        "budget_exhausted",
        "opsec_burned",
        "lease_expired",
        "other",
    ]
    stopped_by: str
    disposition: Literal["freeze_forensic_hold", "graceful_stop"]
    detail: str | None = None

    @field_validator("stopped_by")
    @classmethod
    def validate_stopped_by(cls, value: str) -> str:
        return _canonical_text(value, "stopped_by", 200)

    @field_validator("detail")
    @classmethod
    def validate_detail(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_text(value, "stop detail", 500)

    @model_validator(mode="after")
    def require_other_detail(self) -> Self:
        if self.reason == "other" and self.detail is None:
            raise ValueError("other stop reasons require canonical detail")
        return self


@lru_cache(maxsize=1)
def default_registry() -> EventRegistry:
    registry = EventRegistry()
    registry.register(EngagementAttested)
    registry.register(EngagementAttestedV2)
    registry.register(EngagementStopped)
    return registry.freeze()
