from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from blackbread.conductor.contracts import (
    ActionProposal,
    ConductorContractError,
    require_utc,
)
from blackbread.policy.contracts import (
    DENY_ONLY_DECISION_AUTHORITY,
    POLICY_DECISION_SCHEMA,
    POLICY_DECISION_SCHEMA_VERSION,
    DenyReason,
    PolicyDecision,
)


def _deny_reason(proposal: ActionProposal, decided_at: datetime) -> DenyReason:
    if decided_at >= proposal.expires_at:
        return "PROPOSAL_EXPIRED"
    return "TRUST_SPINE_NOT_READY"


def evaluate_proposal(
    proposal: ActionProposal,
    *,
    decision_id: UUID,
    decided_at: datetime,
) -> PolicyDecision:
    if not isinstance(decision_id, UUID):
        raise ConductorContractError("decision_id must be a UUID")
    try:
        decided = require_utc(decided_at)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ConductorContractError("decided_at must be timezone-aware UTC") from exc
    return PolicyDecision(
        schema_name=POLICY_DECISION_SCHEMA,
        schema_version=POLICY_DECISION_SCHEMA_VERSION,
        decision_id=decision_id,
        tenant_id=proposal.tenant_id,
        engagement_id=proposal.engagement_id,
        proposal_id=proposal.proposal_id,
        proposal_digest=proposal.proposal_digest,
        decision_authority=DENY_ONLY_DECISION_AUTHORITY,
        outcome="DENY",
        reason_code=_deny_reason(proposal, decided),
        decided_at=decided,
        graph_version=proposal.graph_version,
    )


def intake_proposal(
    raw: Mapping[str, object],
    *,
    decision_id: UUID,
    decided_at: datetime,
) -> PolicyDecision:
    proposal = ActionProposal.from_untrusted(raw)
    return evaluate_proposal(proposal, decision_id=decision_id, decided_at=decided_at)
