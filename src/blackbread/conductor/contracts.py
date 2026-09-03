"""Conductor action proposal contracts with strict validation and deterministic digests.

Defines immutable, versioned ActionProposal with proposal-owned value objects
(GraphVersionReference, TargetReference, ParameterEnvelope, ResourceEstimates,
BudgetRequest) and a deterministic proposal digest over a versioned canonical preimage.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    model_validator,
)

from blackbread.ledger.errors import LedgerValidationError
from blackbread.ledger.hashing import canonical_json, canonical_timestamp, sha256_hex

ACTION_PROPOSAL_SCHEMA = "conductor.action_proposal"
ACTION_PROPOSAL_SCHEMA_VERSION = 1
PROPOSAL_DIGEST_VERSION = 1
AGENT_ROLES = ("Scout", "Strike", "Exploit", "Post-Exploit", "Report")
IDENTITY_TIERS = ("T0", "T1", "T2", "T3")
TARGET_KINDS = ("root_domain", "exact_host", "exact_address", "cloud_tenant")

MAX_TENANT_ID_LENGTH = 100
MAX_KEY_LENGTH = 200
MAX_TEXT_LENGTH = 500
MAX_PRECONDITION_REFS = 64
MAX_PARAMETER_BYTES = 65_536
MAX_PROPOSAL_BYTES = 131_072
MAX_SCHEMA_VERSION = 2_147_483_647
MAX_LEDGER_EVENT_COUNT = 9_223_372_036_854_775_807
MAX_COST = 1_000_000.0
MAX_BUDGET_REQUESTS = 1_000_000
MAX_DEADLINE_SECONDS = 604_800

_CAPABILITY_PATTERN = r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\.v[1-9][0-9]*$"
_SCHEMA_REF_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*\.v[1-9][0-9]*$"
_HEX64_PATTERN = r"^[0-9a-f]{64}$"
_DIGEST_DOMAIN = "blackbread.conductor.action_proposal.digest"


class ConductorContractError(ValueError):
    """Typed validation failure for conductor proposal contracts."""


def _canonical_text(value: str) -> str:
    """Validate and return canonical text: non-blank, trimmed, no NUL characters."""
    if not value or value != value.strip():
        raise ValueError("value must be non-blank with no surrounding whitespace")
    if "\x00" in value:
        raise ValueError("value must not contain a NUL character")
    return value


def require_utc(value: datetime) -> datetime:
    """Validate and return a timezone-aware UTC datetime."""
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value


def _deep_freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


TenantId = Annotated[str, AfterValidator(_canonical_text), Field(max_length=MAX_TENANT_ID_LENGTH)]
KeyText = Annotated[str, AfterValidator(_canonical_text), Field(max_length=MAX_KEY_LENGTH)]
CanonicalText = Annotated[str, AfterValidator(_canonical_text), Field(max_length=MAX_TEXT_LENGTH)]
HexDigest = Annotated[str, Field(pattern=_HEX64_PATTERN)]
CapabilityId = Annotated[str, Field(pattern=_CAPABILITY_PATTERN, max_length=MAX_KEY_LENGTH)]
SchemaRef = Annotated[str, Field(pattern=_SCHEMA_REF_PATTERN, max_length=MAX_KEY_LENGTH)]
UtcTimestamp = Annotated[datetime, AfterValidator(require_utc)]
SchemaVersionOne = Annotated[int, Field(ge=1, le=1)]
AgentRole = Literal["Scout", "Strike", "Exploit", "Post-Exploit", "Report"]
IdentityTier = Literal["T0", "T1", "T2", "T3"]
TargetKind = Literal["root_domain", "exact_host", "exact_address", "cloud_tenant"]
Ratio = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class GraphVersionReference(_StrictModel):
    """Immutable reference to a specific graph state root and ledger anchor."""

    state_root_version: Annotated[int, Field(ge=1, le=MAX_SCHEMA_VERSION)]
    projector_version: Annotated[int, Field(ge=1, le=MAX_SCHEMA_VERSION)]
    state_root: HexDigest
    ledger_event_count: Annotated[int, Field(ge=1, le=MAX_LEDGER_EVENT_COUNT)]
    ledger_head_hash: HexDigest


class TargetReference(_StrictModel):
    """Immutable reference to a target scope (domain, host, address, or cloud tenant)."""

    target_kind: TargetKind
    canonical_value: CanonicalText


class ResourceEstimates(_StrictModel):
    """Immutable risk, cost, information-gain, and OPSEC-noise estimates for a proposal."""

    risk: Ratio
    cost: Annotated[float, Field(ge=0.0, le=MAX_COST, allow_inf_nan=False)]
    information_gain: Ratio
    opsec_noise: Ratio


class BudgetRequest(_StrictModel):
    """Immutable budget request specifying target request count and deadline."""

    target_requests: Annotated[int, Field(ge=0, le=MAX_BUDGET_REQUESTS)]
    deadline_seconds: Annotated[int, Field(ge=1, le=MAX_DEADLINE_SECONDS)]


class ParameterEnvelope(_StrictModel):
    """Immutable parameter envelope with a schema reference and canonical JSON parameters."""

    input_schema_ref: SchemaRef
    parameters: Mapping[str, object]
    _canonical_parameters: str = PrivateAttr()

    def model_post_init(self, context: object) -> None:
        """Validate and canonicalize parameters after initialization."""
        del context
        try:
            encoded = canonical_json(dict(self.parameters), max_bytes=MAX_PARAMETER_BYTES)
        except LedgerValidationError as exc:
            raise ConductorContractError("proposal parameters are not canonical JSON") from exc
        object.__setattr__(self, "_canonical_parameters", encoded)
        object.__setattr__(self, "parameters", _deep_freeze(json.loads(encoded)))

    @property
    def canonical_parameters(self) -> str:
        """Return the canonical JSON representation of the parameters."""
        return self._canonical_parameters


class ActionProposal(_StrictModel):
    """Immutable, versioned action proposal with deterministic digest and strict validation."""

    schema_name: Literal["conductor.action_proposal"]
    schema_version: SchemaVersionOne
    proposal_id: UUID
    tenant_id: TenantId
    engagement_id: UUID
    agent_instance_id: UUID
    agent_role: AgentRole
    capability_id: CapabilityId
    target: TargetReference
    parameter_envelope: ParameterEnvelope
    intended_proof: CanonicalText
    precondition_refs: Annotated[tuple[CanonicalText, ...], Field(max_length=MAX_PRECONDITION_REFS)]
    oracle_ref: CanonicalText
    estimates: ResourceEstimates
    requested_budget: BudgetRequest
    target_identity_tier: IdentityTier
    graph_version: GraphVersionReference
    idempotency_key: KeyText
    created_at: UtcTimestamp
    expires_at: UtcTimestamp
    _digest: str = PrivateAttr()

    @model_validator(mode="after")
    def _check_validity_window(self) -> ActionProposal:
        """Validate that expires_at is strictly after created_at."""
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be strictly after created_at")
        return self

    def model_post_init(self, context: object) -> None:
        """Compute the proposal digest after initialization."""
        del context
        object.__setattr__(self, "_digest", _compute_proposal_digest(self))

    @property
    def proposal_digest(self) -> str:
        """Return the deterministic SHA-256 digest of the proposal."""
        return self._digest

    @classmethod
    def from_untrusted(cls, raw: Mapping[str, object]) -> ActionProposal:
        """Parse and validate an action proposal from untrusted raw input."""
        if not isinstance(raw, Mapping):
            raise ConductorContractError("raw proposal must be a mapping")
        try:
            encoded = canonical_json(dict(raw), max_bytes=MAX_PROPOSAL_BYTES)
            return cls.model_validate_json(encoded, strict=True)
        except (ValidationError, LedgerValidationError, ConductorContractError) as exc:
            raise ConductorContractError("raw proposal failed validation") from exc


def _proposal_preimage(proposal: ActionProposal) -> list[object]:
    """Construct the canonical preimage for proposal digest computation."""
    estimates = proposal.estimates
    budget = proposal.requested_budget
    graph = proposal.graph_version
    return [
        ["digest_version", PROPOSAL_DIGEST_VERSION],
        ["schema_name", proposal.schema_name],
        ["schema_version", proposal.schema_version],
        ["proposal_id", str(proposal.proposal_id)],
        ["tenant_id", proposal.tenant_id],
        ["engagement_id", str(proposal.engagement_id)],
        ["agent_instance_id", str(proposal.agent_instance_id)],
        ["agent_role", proposal.agent_role],
        ["capability_id", proposal.capability_id],
        ["target", [proposal.target.target_kind, proposal.target.canonical_value]],
        ["input_schema_ref", proposal.parameter_envelope.input_schema_ref],
        ["parameters", proposal.parameter_envelope.canonical_parameters],
        ["intended_proof", proposal.intended_proof],
        ["precondition_refs", list(proposal.precondition_refs)],
        ["oracle_ref", proposal.oracle_ref],
        ["risk", estimates.risk],
        ["cost", estimates.cost],
        ["information_gain", estimates.information_gain],
        ["opsec_noise", estimates.opsec_noise],
        ["target_requests", budget.target_requests],
        ["deadline_seconds", budget.deadline_seconds],
        ["target_identity_tier", proposal.target_identity_tier],
        ["state_root_version", graph.state_root_version],
        ["projector_version", graph.projector_version],
        ["state_root", graph.state_root],
        ["ledger_event_count", graph.ledger_event_count],
        ["ledger_head_hash", graph.ledger_head_hash],
        ["idempotency_key", proposal.idempotency_key],
        ["created_at", canonical_timestamp(proposal.created_at)],
        ["expires_at", canonical_timestamp(proposal.expires_at)],
    ]


def _compute_proposal_digest(proposal: ActionProposal) -> str:
    """Compute the deterministic SHA-256 digest for an action proposal."""
    preimage = _proposal_preimage(proposal)
    return sha256_hex(f"{_DIGEST_DOMAIN}\x00{canonical_json(preimage)}")
