"""Immutable verified-fact snapshots for the policy-admission boundary (M1.4b1a).

Defines the strict, frozen, versioned input contracts a caller supplies to policy admission:
a verified engagement-policy snapshot, a verified target-identity snapshot, a digest-pinned
capability-admission snapshot, and a bounded destination manifest, plus the canonical parameter
digest that binds a manifest to a proposal's parameters. These contracts carry provenance
references and digests, never a bare trust boolean, and reuse the conductor's canonical scalar
and target types rather than duplicating them. This slice defines inputs only: it adds no
evaluator, no result, and no executable outcome. The pure evaluator is PR-M1.4b1b.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from blackbread.conductor.contracts import (
    MAX_BUDGET_REQUESTS,
    MAX_DEADLINE_SECONDS,
    MAX_SCHEMA_VERSION,
    AgentRole,
    CanonicalText,
    CapabilityId,
    GraphVersionReference,
    HexDigest,
    IdentityTier,
    SchemaRef,
    TargetReference,
    TenantId,
    UtcTimestamp,
)
from blackbread.ledger.hashing import sha256_hex

ADMISSION_SCHEMA = "policy.admission"
ADMISSION_SCHEMA_VERSION = 1

MAX_SCOPE_ENTRIES = 256
MAX_CAPABILITY_IDS = 256
MAX_DESTINATIONS = 256

# The ADR-FINAL-002 §20.2 closed capability lifecycle vocabulary. Unknown values fail contract
# construction; the executable subset is selected by the evaluator (PR-M1.4b1b), not here.
CapabilityLifecycle = Literal[
    "PLANNED",
    "ON_HOLD",
    "RESEARCH_DRAFT",
    "STATIC_REVIEWED",
    "FIXTURE_VERIFIED",
    "NEGATIVE_CONTROL_VERIFIED",
    "LAB_PROVEN",
    "SAFETY_REVIEWED",
    "CLIENT_ELIGIBLE",
    "EXACT_TARGET_APPROVED",
    "FIELD_OBSERVED",
    "FIELD_PROVEN",
    "REPEATABLE",
    "SUSPENDED",
    "RETIRED",
]
RiskClass = Literal[
    "PASSIVE",
    "ACTIVE_READ_ONLY",
    "SENSITIVE_OFFLINE",
    "OFFLINE",
    "AUTHENTICATION",
    "ACTIVE_SENSITIVE_READ",
    "EXPLOIT",
    "POST_ACCESS",
]
ApprovalClass = Literal[
    "AUTO_WITH_MANIFEST",
    "LEASE",
    "OPERATOR_DATA_APPROVAL",
    "OPERATOR_EXACT",
    "EXACT_TARGET_AND_CAPABILITY",
    "SEPARATE_OBJECTIVE",
]
NetworkPath = Literal["CONTROL_PLANE_PASSIVE", "TARGET_EGRESS", "NONE"]
DestinationKind = Literal["primary", "redirect", "callback", "proxy", "file_input", "body_embedded"]

_PARAMETER_DIGEST_DOMAIN = "blackbread.policy.admission.parameter_digest.v1"


class AdmissionContractError(ValueError):
    """Typed validation failure for policy-admission input contracts."""


def parameter_digest(canonical_parameters: str) -> str:
    """Deterministic digest binding a destination manifest to a proposal's canonical parameters."""
    return sha256_hex(f"{_PARAMETER_DIGEST_DOMAIN}\x00{canonical_parameters}")


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EngagementPolicySnapshot(_Frozen):
    """Verified engagement-policy facts: provenance digests, validity, scope, capabilities."""

    tenant_id: TenantId
    engagement_id: UUID
    policy_schema: SchemaRef
    policy_version: Annotated[int, Field(ge=1, le=MAX_SCHEMA_VERSION)]
    policy_digest: HexDigest
    attestation_ref: CanonicalText
    attestation_digest: HexDigest
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp
    scope_allow: Annotated[
        tuple[TargetReference, ...], Field(min_length=1, max_length=MAX_SCOPE_ENTRIES)
    ]
    scope_exclusions: Annotated[tuple[TargetReference, ...], Field(max_length=MAX_SCOPE_ENTRIES)]
    allowed_capability_ids: Annotated[
        tuple[CapabilityId, ...], Field(min_length=1, max_length=MAX_CAPABILITY_IDS)
    ]
    graph_version: GraphVersionReference

    @model_validator(mode="after")
    def _check_snapshot(self) -> EngagementPolicySnapshot:
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be strictly after valid_from")
        if len(set(self.allowed_capability_ids)) != len(self.allowed_capability_ids):
            raise ValueError("allowed_capability_ids must be unique")
        return self


class TargetIdentitySnapshot(_Frozen):
    """Verified target-identity facts bound to one proposal digest and one exact target."""

    tenant_id: TenantId
    engagement_id: UUID
    proposal_digest: HexDigest
    target: TargetReference
    achieved_tier: IdentityTier
    verified_at: UtcTimestamp
    expires_at: UtcTimestamp
    graph_version: GraphVersionReference
    verifier_ref: CanonicalText
    evidence_digest: HexDigest

    @model_validator(mode="after")
    def _check_validity(self) -> TargetIdentitySnapshot:
        if self.expires_at <= self.verified_at:
            raise ValueError("expires_at must be strictly after verified_at")
        return self


class CapabilityAdmissionSnapshot(_Frozen):
    """Digest-pinned registry facts for one capability plus its bound destination extractor."""

    registry_schema_version: Annotated[int, Field(ge=1, le=MAX_SCHEMA_VERSION)]
    registry_digest: HexDigest
    capability_id: CapabilityId
    owner_agent: AgentRole
    lifecycle: CapabilityLifecycle
    input_schema: SchemaRef
    risk_class: RiskClass
    required_identity_tier: IdentityTier
    approval_class: ApprovalClass
    network_path: NetworkPath
    supply_chain_digest: HexDigest
    extractor_identity: CanonicalText
    extractor_digest: HexDigest
    max_target_requests: Annotated[int, Field(ge=0, le=MAX_BUDGET_REQUESTS)]
    max_deadline_seconds: Annotated[int, Field(ge=1, le=MAX_DEADLINE_SECONDS)]


class ScopedDestination(_Frozen):
    """One canonical destination with its kind and canonical scope identity."""

    destination_kind: DestinationKind
    scope: TargetReference


class DestinationManifest(_Frozen):
    """Bounded exhaustive destination set produced by a digest-admitted extractor."""

    proposal_digest: HexDigest
    parameter_digest: HexDigest
    input_schema: SchemaRef
    capability_id: CapabilityId
    extractor_identity: CanonicalText
    extractor_digest: HexDigest
    destinations: Annotated[tuple[ScopedDestination, ...], Field(max_length=MAX_DESTINATIONS)]

    @model_validator(mode="after")
    def _check_unique(self) -> DestinationManifest:
        keyed = {
            (item.destination_kind, item.scope.target_kind, item.scope.canonical_value)
            for item in self.destinations
        }
        if len(keyed) != len(self.destinations):
            raise ValueError("destinations must be canonical and unique")
        return self
