"""PolicyDecision v2 schema with strict validation and canonical decision digest.

Defines the immutable, versioned, digest-bound ``PolicyDecisionV2`` that replaces the intermediate
``PASSED_FOR_FINAL_DECISION`` runtime-gate outcome with a closed final-decision vocabulary. The
decision is a policy result value; it grants no execution authority, lease, work order, or target
effect.  Its digest proves content consistency, not producer identity.

Public construction via ``build()`` or ``model_validate`` is allowed for serialization support and
does not authenticate the producer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from blackbread.conductor.contracts import (
    GraphVersionReference,
    HexDigest,
    TenantId,
    UtcTimestamp,
)
from blackbread.ledger.hashing import canonical_json, canonical_timestamp, sha256_hex
from blackbread.policy.runtime_result import OUTCOME_BY_REASON, RuntimeGateReason

POLICY_DECISION_V2_SCHEMA: Literal["policy.decision"] = "policy.decision"
POLICY_DECISION_V2_SCHEMA_VERSION = 2
POLICY_DECISION_V2_AUTHORITY: Literal["policy.kernel.v2"] = "policy.kernel.v2"
_DECISION_DIGEST_DOMAIN = "blackbread.policy.decision_digest.v2"

FinalDecisionOutcome = Literal[
    "ALLOW",
    "DENY",
    "APPROVAL_REQUIRED",
    "WAIT_FOR_RESOURCE",
    "STALE_CONTEXT",
    "ENGAGEMENT_STOPPED",
    "OPSEC_HOLD",
]

# Map each RuntimeGateReason to its final decision outcome.  PASSED_FOR_FINAL_DECISION becomes
# ALLOW (with reason_code=None) at the evaluator layer; every other reason maps through
# OUTCOME_BY_REASON unchanged.  This mapping is consumed by the evaluator and by coherence
# validation; it is NOT the evaluator itself.
FINAL_OUTCOME_BY_REASON: dict[RuntimeGateReason, FinalDecisionOutcome] = {}
for _reason, _gate_outcome in OUTCOME_BY_REASON.items():
    if _gate_outcome not in get_args(FinalDecisionOutcome):
        raise RuntimeError(
            f"unmapped runtime-gate outcome {_gate_outcome!r} for reason {_reason!r}"
        )
    FINAL_OUTCOME_BY_REASON[_reason] = _gate_outcome  # type: ignore[assignment]

SchemaVersionTwo = Annotated[int, Field(strict=True, ge=2, le=2)]


class _PolicyDecisionV2Fields(BaseModel):
    """Validates all decision fields except the decision_digest."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_name: Literal["policy.decision"]
    schema_version: SchemaVersionTwo
    decision_id: UUID
    tenant_id: TenantId
    engagement_id: UUID
    proposal_id: UUID
    proposal_digest: HexDigest
    decision_authority: Literal["policy.kernel.v2"]
    outcome: FinalDecisionOutcome
    reason_code: RuntimeGateReason | None
    decided_at: UtcTimestamp
    graph_version: GraphVersionReference
    runtime_gate_result_digest: HexDigest


class PolicyDecisionV2(_PolicyDecisionV2Fields):
    """Immutable, versioned, digest-bound policy decision v2 with strict validation.

    ALLOW represents a policy evaluation outcome only.  No component may execute merely because it
    receives a serialized PolicyDecisionV2.
    """

    decision_digest: HexDigest

    @model_validator(mode="after")
    def _check_coherence_and_digest(self) -> PolicyDecisionV2:
        # Outcome/reason coherence.
        if self.reason_code is None:
            if self.outcome != "ALLOW":
                raise ValueError("reason_code is None but outcome is not ALLOW")
        else:
            expected = FINAL_OUTCOME_BY_REASON.get(self.reason_code)
            if expected is None or self.outcome != expected:
                raise ValueError("outcome and reason_code are incompatible")

        # Decision-digest binding.
        expected_digest = _decision_digest(self.model_dump(exclude={"decision_digest"}))
        if self.decision_digest != expected_digest:
            raise ValueError("decision_digest does not bind the decision contents")
        return self

    @classmethod
    def build(cls, fields: dict[str, Any]) -> PolicyDecisionV2:
        """Validate fields and compute the decision digest.

        Factory validation occurs before hashing.  Public construction is allowed for
        serialization support and does not authenticate the producer.
        """
        validated = _PolicyDecisionV2Fields.model_validate(fields).model_dump()
        digest = _decision_digest(validated)
        return cls.model_validate({**validated, "decision_digest": digest})


def _canonical_scalar(value: object) -> object:
    """Canonicalize a scalar for the decision-digest preimage."""
    if isinstance(value, datetime):
        return canonical_timestamp(value)
    return str(value) if isinstance(value, UUID) else value


def _decision_preimage(values: dict[str, Any]) -> dict[str, Any]:
    """Build the canonical preimage dict from validated decision fields."""
    preimage: dict[str, Any] = {}
    for key, value in values.items():
        if key == "graph_version":
            # Expand graph_version to its component fields.
            for gk, gv in value.items():
                preimage[f"graph_version.{gk}"] = _canonical_scalar(gv)
        else:
            preimage[key] = _canonical_scalar(value)
    return preimage


def _decision_digest(values: dict[str, Any]) -> str:
    """Compute the canonical SHA-256 decision digest."""
    preimage = _decision_preimage(values)
    return sha256_hex(f"{_DECISION_DIGEST_DOMAIN}\x00{canonical_json(preimage)}")
