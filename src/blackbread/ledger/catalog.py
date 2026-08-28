"""M1 event shapes; these validate records but do not grant execution authority."""

import re
from datetime import datetime
from functools import lru_cache
from ipaddress import IPv6Address, ip_address
from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from blackbread.ledger.schema import EventPayload, EventRegistry

_DOMAIN_LABEL_PATTERN = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_HEX_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_MAX_SCOPE_ENTRIES = 500
_MIN_DOMAIN_LABELS = 2


def _canonical_text(value: str, field: str, maximum: int) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field} must be a canonical non-blank string")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    if "\x00" in value:
        raise ValueError(f"{field} contains a NUL character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} contains invalid Unicode") from exc
    return value


def _canonical_domain(value: str) -> str:
    _canonical_text(value, "domain", 253)
    labels = value.split(".")
    if len(labels) < _MIN_DOMAIN_LABELS or value != value.lower():
        raise ValueError("domain must be a lowercase fully-qualified name")
    if any(_DOMAIN_LABEL_PATTERN.fullmatch(label) is None for label in labels):
        raise ValueError("domain is not canonical")
    return value


def _sorted_unique(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{field} must be sorted and unique")
    return values


def _canonical_address(value: str) -> str:
    parsed = ip_address(value)
    if isinstance(parsed, IPv6Address) and parsed.scope_id is not None:
        raise ValueError("scoped IPv6 addresses are not valid engagement targets")
    if value != parsed.compressed:
        raise ValueError("IP address must use its canonical compressed spelling")
    return value


class ScopeExclusion(BaseModel):
    """A canonical exclusion with an explicit target interpretation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    target_type: Literal["root_domain", "exact_host", "exact_address", "cloud_tenant"]
    value: str

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if self.target_type in {"root_domain", "exact_host"}:
            _canonical_domain(self.value)
        elif self.target_type == "exact_address":
            _canonical_address(self.value)
        else:
            _canonical_text(self.value, "cloud tenant exclusion", 500)
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
    registry.register(EngagementStopped)
    return registry.freeze()
