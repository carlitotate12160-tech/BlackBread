"""Pure deterministic evaluation of immutable runtime-gate facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from math import ceil

from blackbread.conductor.contracts import ActionProposal
from blackbread.policy.admission_contracts import AdmissionResult, CapabilityAdmissionSnapshot
from blackbread.policy.runtime_contracts import RuntimeGateSnapshot
from blackbread.policy.runtime_result import OUTCOME_BY_REASON, RuntimeGateReason, RuntimeGateResult

_AUTO_APPROVALS = frozenset({"AUTO_WITH_MANIFEST", "LEASE"})
_IDENTITY_FIELDS = ("tenant_id", "engagement_id", "proposal_id", "proposal_digest")


class RuntimeGateEvaluationError(ValueError):
    """Typed fail-closed failure for invalid evaluator arguments."""


@dataclass(frozen=True)
class _Context:
    proposal: ActionProposal
    admission: AdmissionResult
    capability: CapabilityAdmissionSnapshot
    runtime: RuntimeGateSnapshot
    evaluated_at: datetime
    requested_cost: int


def _different(left: object, right: object, fields: tuple[str, ...]) -> bool:
    return any(getattr(left, field) != getattr(right, field) for field in fields)


def _binding_checks(context: _Context) -> tuple[bool, bool, bool]:
    proposal = context.proposal
    admission = context.admission
    capability = context.capability
    runtime = context.runtime
    admission_mismatch = _different(admission, proposal, _IDENTITY_FIELDS) or (
        admission.capability_id != proposal.capability_id
    )
    runtime_mismatch = (
        _different(runtime, proposal, _IDENTITY_FIELDS)
        or runtime.agent_instance_id != proposal.agent_instance_id
        or runtime.capability_id != proposal.capability_id
        or runtime.admission_result_digest != admission.result_digest
    )
    capability_mismatch = (
        _different(
            capability,
            admission,
            ("registry_schema_version", "registry_digest", "capability_id", "supply_chain_digest"),
        )
        or capability.owner_agent != proposal.agent_role
    )
    return admission_mismatch, runtime_mismatch, capability_mismatch


def _runtime_context_incoherent(context: _Context) -> bool:
    runtime = context.runtime
    timestamps = [
        runtime.engagement.transitioned_at if runtime.engagement is not None else None,
    ]
    if context.capability.network_path == "TARGET_EGRESS":
        timestamps.append(runtime.opsec.observed_at if runtime.opsec is not None else None)
        holder = runtime.lock.holder if runtime.lock is not None else None
        timestamps.append(holder.acquired_at if holder is not None else None)
    grant = runtime.approval_grant
    if context.capability.approval_class not in _AUTO_APPROVALS and grant is not None:
        timestamps.append(grant.revocation_timestamp)
    return runtime.captured_at < context.admission.evaluated_at or any(
        stamp is not None and stamp > runtime.captured_at for stamp in timestamps
    )


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
    admission_binding, runtime_binding, capability_binding = _binding_checks(context)
    budget_window, budget_deadline, budget_capacity = _budget_checks(context)
    approval = _approval_reason(context)
    return (
        ("ADMISSION_BINDING_MISMATCH", admission_binding),
        ("RUNTIME_BINDING_MISMATCH", runtime_binding),
        ("CAPABILITY_BINDING_MISMATCH", capability_binding),
        ("ADMISSION_NOT_ADMITTED", context.admission.outcome != "ADMITTED_FOR_RUNTIME_GATES"),
        ("PROPOSAL_NOT_YET_VALID", context.evaluated_at < context.proposal.created_at),
        ("PROPOSAL_EXPIRED", context.evaluated_at >= context.proposal.expires_at),
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


def evaluate_runtime_gates(
    proposal: ActionProposal,
    *,
    admission: AdmissionResult,
    capability: CapabilityAdmissionSnapshot,
    runtime: RuntimeGateSnapshot,
    evaluated_at: datetime,
) -> RuntimeGateResult:
    """Evaluate immutable runtime facts in fixed fail-closed precedence."""
    if not isinstance(evaluated_at, datetime):
        raise RuntimeGateEvaluationError("evaluation arguments failed validation")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != timedelta(0):
        raise RuntimeGateEvaluationError("evaluation arguments failed validation")
    requested_cost = ceil(Decimal(str(proposal.estimates.cost)) * Decimal(1_000_000))
    context = _Context(proposal, admission, capability, runtime, evaluated_at, requested_cost)
    reason = next((code for code, denied in _checks(context) if denied), None)
    return _result(context, reason)
