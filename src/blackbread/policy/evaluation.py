"""Composed final policy evaluator: computes runtime gates and returns PolicyDecisionV2.

No public parameter accepts AdmissionResult, RuntimeGateResult, PolicyDecision, or an
admission/runtime binding.  ALLOW is a policy outcome, not an execution lease or token.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from blackbread.conductor.contracts import ActionProposal
from blackbread.policy.admission_contracts import (
    CapabilityAdmissionSnapshot,
    DestinationManifest,
    EngagementPolicySnapshot,
    TargetIdentitySnapshot,
)
from blackbread.policy.decision_v2 import FinalDecisionOutcome, PolicyDecisionV2
from blackbread.policy.runtime_contracts import RuntimeGateSnapshot
from blackbread.policy.runtime_gate import evaluate_runtime_gates
from blackbread.policy.runtime_result import RuntimeGateReason, RuntimeGateResult


class PolicyEvaluationError(ValueError):
    """Typed fail-closed failure for invalid evaluator arguments."""


def _validate_arguments(  # noqa: PLR0913, PLR0917
    proposal: object,
    decision_id: object,
    policy: object,
    identity: object,
    capability: object,
    manifest: object,
    runtime: object,
    decided_at: object,
) -> None:
    """Validate public argument types before dereferencing or evaluating."""
    if not all(
        (
            isinstance(proposal, ActionProposal),
            isinstance(decision_id, UUID),
            isinstance(policy, EngagementPolicySnapshot),
            isinstance(identity, TargetIdentitySnapshot),
            isinstance(capability, CapabilityAdmissionSnapshot),
            isinstance(manifest, DestinationManifest),
            isinstance(runtime, RuntimeGateSnapshot),
        )
    ):
        raise PolicyEvaluationError("evaluation arguments failed validation")
    if not isinstance(decided_at, datetime):
        raise PolicyEvaluationError("evaluation arguments failed validation")
    if decided_at.tzinfo is None or decided_at.utcoffset() != timedelta(0):
        raise PolicyEvaluationError("evaluation arguments failed validation")


def _map_runtime_outcome(
    runtime_result: RuntimeGateResult,
) -> tuple[FinalDecisionOutcome, RuntimeGateReason | None]:
    """Map the runtime-gate outcome to the final decision vocabulary.

    ``PASSED_FOR_FINAL_DECISION`` becomes ``ALLOW`` with ``reason_code=None``; every other
    outcome passes through unchanged.  This is a pure projection over the closed
    ``RuntimeGateReason`` vocabulary and grants no authority.
    """
    if runtime_result.outcome == "PASSED_FOR_FINAL_DECISION":
        return "ALLOW", None
    return runtime_result.outcome, runtime_result.reason_code


def _build_decision(  # noqa: PLR0913
    proposal: ActionProposal,
    *,
    decision_id: UUID,
    runtime_result: RuntimeGateResult,
    outcome: FinalDecisionOutcome,
    reason_code: RuntimeGateReason | None,
    decided_at: datetime,
) -> PolicyDecisionV2:
    """Assemble the immutable PolicyDecisionV2 from the proposal and runtime result."""
    return PolicyDecisionV2.build(
        {
            "schema_name": "policy.decision",
            "schema_version": 2,
            "decision_id": decision_id,
            "tenant_id": proposal.tenant_id,
            "engagement_id": proposal.engagement_id,
            "proposal_id": proposal.proposal_id,
            "proposal_digest": proposal.proposal_digest,
            "decision_authority": "policy.kernel.v2",
            "outcome": outcome,
            "reason_code": reason_code,
            "decided_at": decided_at,
            "graph_version": proposal.graph_version,
            "runtime_gate_result_digest": runtime_result.result_digest,
        }
    )


def evaluate_policy(  # noqa: PLR0913
    proposal: ActionProposal,
    *,
    decision_id: UUID,
    policy: EngagementPolicySnapshot,
    identity: TargetIdentitySnapshot,
    capability: CapabilityAdmissionSnapshot,
    manifest: DestinationManifest,
    runtime: RuntimeGateSnapshot,
    decided_at: datetime,
) -> PolicyDecisionV2:
    """Compute the final policy decision; passes decided_at as evaluated_at internally."""
    _validate_arguments(
        proposal,
        decision_id,
        policy,
        identity,
        capability,
        manifest,
        runtime,
        decided_at,
    )

    runtime_result = evaluate_runtime_gates(
        proposal,
        policy=policy,
        identity=identity,
        capability=capability,
        manifest=manifest,
        runtime=runtime,
        evaluated_at=decided_at,
    )

    outcome, reason_code = _map_runtime_outcome(runtime_result)
    return _build_decision(
        proposal,
        decision_id=decision_id,
        runtime_result=runtime_result,
        outcome=outcome,
        reason_code=reason_code,
        decided_at=decided_at,
    )
