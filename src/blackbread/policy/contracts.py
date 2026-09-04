"""Policy decision contracts for deny-only evaluation results.

Defines immutable, versioned, deny-only PolicyDecision v1. ALLOW, APPROVAL_REQUIRED,
lease, work order, and executable token are unrepresentable in this schema version.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from blackbread.conductor.contracts import (
    GraphVersionReference,
    HexDigest,
    SchemaVersionOne,
    TenantId,
    UtcTimestamp,
)

POLICY_DECISION_SCHEMA: Literal["policy.decision"] = "policy.decision"
POLICY_DECISION_SCHEMA_VERSION = 1
DENY_ONLY_DECISION_AUTHORITY: Literal["conductor.deny_only_intake_guard.v1"] = (
    "conductor.deny_only_intake_guard.v1"
)
DENY_REASONS = ("PROPOSAL_EXPIRED", "TRUST_SPINE_NOT_READY")

DenyReason = Literal["PROPOSAL_EXPIRED", "TRUST_SPINE_NOT_READY"]


class PolicyContractError(ValueError):
    """Typed validation failure for policy decision contracts."""


class PolicyDecision(BaseModel):
    """Immutable, versioned, deny-only policy decision with strict validation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_name: Literal["policy.decision"]
    schema_version: SchemaVersionOne
    decision_id: UUID
    tenant_id: TenantId
    engagement_id: UUID
    proposal_id: UUID
    proposal_digest: HexDigest
    decision_authority: Literal["conductor.deny_only_intake_guard.v1"]
    outcome: Literal["DENY"]
    reason_code: DenyReason
    decided_at: UtcTimestamp
    graph_version: GraphVersionReference
