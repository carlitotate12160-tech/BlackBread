"""Composed, pure runtime-gate evaluation over one capability input (M1.4b2b-R).

`evaluate_runtime_gates` computes admission internally to prevent substituting a weak capability
into a strong admission. The strict, digest-bound `RuntimeGateResult` issues no `PolicyDecision`,
lease, work order, or target effect. Admission conditions surface as ``ADMISSION_DENIED``.
The runtime facts (engagement, OPSEC, approvals, budgets, locks, freshness) and computed admission
share one evaluation instant, so the snapshot binding establishes stage continuity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from math import ceil

from blackbread.conductor.contracts import ActionProposal
from blackbread.policy.admission import evaluate_admission
from blackbread.policy.admission_contracts import (
    AdmissionResult,
    CapabilityAdmissionSnapshot,
    DestinationManifest,
    EngagementPolicySnapshot,
    TargetIdentitySnapshot,
)
from blackbread.policy.runtime_contracts import RuntimeGateSnapshot
from blackbread.policy.runtime_result import OUTCOME_BY_REASON, RuntimeGateReason, RuntimeGateResult

_AUTO_APPROVALS = frozenset({"AUTO_WITH_MANIFEST", "LEASE"})
_RUNTIME_IDENTITY_FIELDS = ("tenant_id", "engagement_id", "proposal_id", "proposal_digest")


class RuntimeGateEvaluationError(ValueError):
    """Typed fail-closed failure for invalid evaluator arguments."""


@dataclass(frozen=True)
class _Context:
    proposal: ActionProposal
    capability: CapabilityAdmissionSnapshot
    runtime: RuntimeGateSnapshot
    admission: AdmissionResult
    evaluated_at: datetime
    requested_cost: int


def _validate_arguments(typed: tuple[tuple[object, type], ...], evaluated_at: datetime) -> None:
    if any(not isinstance(value, kind) for value, kind in typed):
        raise RuntimeGateEvaluationError("evaluation arguments failed validation")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != timedelta(0):
        raise RuntimeGateEvaluationError("evaluation arguments failed validation")


def _runtime_binding_mismatch(context: _Context) -> bool:
    # The runtime snapshot is caller-supplied; bind it to this proposal, capability, and agent,
    # and the exact admission this call computed. Its admission_result_digest establishes that the
    # runtime facts were captured for the same admission, so no separate temporal check is needed.
    runtime = context.runtime
    proposal = context.proposal
    return (
        any(
            getattr(runtime, field) != getattr(proposal, field)
            for field in _RUNTIME_IDENTITY_FIELDS
        )
        or runtime.agent_instance_id != proposal.agent_instance_id
        or runtime.capability_id != proposal.capability_id
        or runtime.admission_result_digest != context.admission.result_digest
    )


def _runtime_context_incoherent(context: _Context) -> bool:
    runtime = context.runtime
    timestamps = [runtime.engagement.transitioned_at if runtime.engagement is not None else None]
    if context.capability.network_path == "TARGET_EGRESS":
        timestamps.append(runtime.opsec.observed_at if runtime.opsec is not None else None)
        holder = runtime.lock.holder if runtime.lock is not None else None
        timestamps.append(holder.acquired_at if holder is not None else None)
    grant = runtime.approval_grant
    if context.capability.approval_class not in _AUTO_APPROVALS and grant is not None:
        timestamps.append(grant.revocation_timestamp)
    return any(stamp is not None and stamp > runtime.captured_at for stamp in timestamps)


def _approval_reason(context: _Context) -> RuntimeGateReason | None:
    if context.capability.approval_class in _AUTO_APPROVALS:
        return None
    grant = context.runtime.approval_grant
    if grant is None:
        return "APPROVAL_MISSING"
    revoked_at = grant.revocation_timestamp
    checks: tuple[tuple[bool, RuntimeGateReason], ...] = (
        (grant.approval_class != context.capability.approval_class, "APPROVAL_CLASS_MISMATCH"),
        (grant.target != context.proposal.target, "APPROVAL_TARGET_MISMATCH"),
        (context.evaluated_at < grant.valid_from, "APPROVAL_NOT_YET_VALID"),
        (context.evaluated_at >= grant.valid_until, "APPROVAL_EXPIRED"),
        (revoked_at is not None and context.evaluated_at >= revoked_at, "APPROVAL_REVOKED"),
    )
    return next((reason for failed, reason in checks if failed), None)


def _budget_checks(context: _Context) -> tuple[bool, bool, bool]:
    budget = context.runtime.budget
    if budget is None:
        return False, False, False
    accounts = (budget.engagement_account, budget.agent_account)
    requested = context.proposal.requested_budget
    deadline = context.evaluated_at + timedelta(seconds=requested.deadline_seconds)
    window_expired = any(context.evaluated_at >= item.hard_stop_until for item in accounts)
    deadline_exceeded = any(deadline > item.hard_stop_until for item in accounts)
    capacity_exceeded = any(
        item.consumed_requests + item.reserved_requests + requested.target_requests
        > item.request_limit
        or item.consumed_microunits + item.reserved_microunits + context.requested_cost
        > item.cost_microunit_limit
        for item in accounts
    )
    return window_expired, deadline_exceeded, capacity_exceeded


def _lock_held(context: _Context) -> bool:
    lock = context.runtime.lock
    holder = lock.holder if lock is not None else None
    if context.capability.network_path != "TARGET_EGRESS" or holder is None:
        return False
    return (
        holder.holder_proposal_id != context.proposal.proposal_id
        and context.evaluated_at < holder.expires_at
    )


def _checks(context: _Context) -> tuple[tuple[RuntimeGateReason, bool], ...]:
    runtime = context.runtime
    engagement = runtime.engagement
    opsec = runtime.opsec
    target_egress = context.capability.network_path == "TARGET_EGRESS"
    budget_window, budget_deadline, budget_capacity = _budget_checks(context)
    approval = _approval_reason(context)
    return (
        ("RUNTIME_BINDING_MISMATCH", _runtime_binding_mismatch(context)),
        ("ADMISSION_DENIED", context.admission.outcome != "ADMITTED_FOR_RUNTIME_GATES"),
        ("ENGAGEMENT_STATE_MISSING", engagement is None),
        ("RUNTIME_CONTEXT_INCOHERENT", _runtime_context_incoherent(context)),
        ("ENGAGEMENT_STOPPED", engagement is not None and engagement.state == "STOPPED"),
        ("OPSEC_STATE_MISSING", target_egress and opsec is None),
        ("OPSEC_BURNED", target_egress and opsec is not None and opsec.state == "BURNED"),
        ("OPSEC_HOT", target_egress and opsec is not None and opsec.state == "HOT"),
        ("RUNTIME_SNAPSHOT_NOT_YET_VALID", context.evaluated_at < runtime.captured_at),
        ("RUNTIME_SNAPSHOT_EXPIRED", context.evaluated_at >= runtime.fresh_until),
        (
            "OPSEC_STATE_EXPIRED",
            target_egress and opsec is not None and context.evaluated_at >= opsec.fresh_until,
        ),
        ("BUDGET_STATE_MISSING", runtime.budget is None),
        ("BUDGET_WINDOW_EXPIRED", budget_window),
        ("LOCK_STATE_MISSING", target_egress and runtime.lock is None),
        ("APPROVAL_MISSING", approval == "APPROVAL_MISSING"),
        ("APPROVAL_CLASS_MISMATCH", approval == "APPROVAL_CLASS_MISMATCH"),
        ("APPROVAL_TARGET_MISMATCH", approval == "APPROVAL_TARGET_MISMATCH"),
        ("APPROVAL_NOT_YET_VALID", approval == "APPROVAL_NOT_YET_VALID"),
        ("APPROVAL_EXPIRED", approval == "APPROVAL_EXPIRED"),
        ("APPROVAL_REVOKED", approval == "APPROVAL_REVOKED"),
        ("BUDGET_DEADLINE_EXCEEDED", budget_deadline),
        ("BUDGET_CAPACITY_EXCEEDED", budget_capacity),
        ("RESOURCE_LOCK_HELD", _lock_held(context)),
    )


def _result(context: _Context, reason: RuntimeGateReason | None) -> RuntimeGateResult:
    proposal = context.proposal
    capability = context.capability
    outcome = "PASSED_FOR_FINAL_DECISION" if reason is None else OUTCOME_BY_REASON[reason]
    return RuntimeGateResult.build(
        {
            "schema_name": "policy.runtime.gate.result",
            "schema_version": 1,
            "tenant_id": proposal.tenant_id,
            "engagement_id": proposal.engagement_id,
            "proposal_id": proposal.proposal_id,
            "proposal_digest": proposal.proposal_digest,
            "agent_instance_id": proposal.agent_instance_id,
            "admission_result_digest": context.admission.result_digest,
            "runtime_snapshot_digest": context.runtime.snapshot_digest,
            "registry_schema_version": capability.registry_schema_version,
            "registry_digest": capability.registry_digest,
            "capability_id": capability.capability_id,
            "supply_chain_digest": capability.supply_chain_digest,
            "approval_class": capability.approval_class,
            "network_path": capability.network_path,
            "requested_target_requests": proposal.requested_budget.target_requests,
            "requested_cost_microunits": context.requested_cost,
            "requested_deadline_seconds": proposal.requested_budget.deadline_seconds,
            "evaluated_at": context.evaluated_at,
            "outcome": outcome,
            "reason_code": reason,
        }
    )


def evaluate_runtime_gates(  # noqa: PLR0913 - binds five admission inputs plus the runtime snapshot
    proposal: ActionProposal,
    *,
    policy: EngagementPolicySnapshot,
    identity: TargetIdentitySnapshot,
    capability: CapabilityAdmissionSnapshot,
    manifest: DestinationManifest,
    runtime: RuntimeGateSnapshot,
    evaluated_at: datetime,
) -> RuntimeGateResult:
    """Compute admission and runtime gates from one capability, in fixed fail-closed precedence."""
    _validate_arguments(
        (
            (proposal, ActionProposal),
            (policy, EngagementPolicySnapshot),
            (identity, TargetIdentitySnapshot),
            (capability, CapabilityAdmissionSnapshot),
            (manifest, DestinationManifest),
            (runtime, RuntimeGateSnapshot),
        ),
        evaluated_at,
    )
    admission = evaluate_admission(
        proposal,
        policy=policy,
        identity=identity,
        capability=capability,
        manifest=manifest,
        evaluated_at=evaluated_at,
    )
    requested_cost = ceil(Decimal(str(proposal.estimates.cost)) * Decimal(1_000_000))
    context = _Context(proposal, capability, runtime, admission, evaluated_at, requested_cost)
    reason = next((code for code, failed in _checks(context) if failed), None)
    return _result(context, reason)
