"""Binding, precedence, approval, budget, lock, temporal, and purity proofs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from blackbread.conductor.contracts import (
    BudgetRequest,
    ResourceEstimates,
    TargetReference,
)
from blackbread.policy.admission_contracts import AdmissionResult
from blackbread.policy.runtime_contracts import RuntimeGateSnapshot
from blackbread.policy.runtime_gate import RuntimeGateEvaluationError, evaluate_runtime_gates
from tests.conductor._builders import make_proposal
from tests.policy._builders import (
    capability_snapshot,
    egress_destination,
    manifest,
)
from tests.policy._runtime_builders import (
    _account,
    _budget,
    _grant,
    _held,
    _lock,
    _opsec,
    _run,
    _ts,
    admitted_context,
    runtime_snapshot,
)

EVALUATED_AT = datetime(2026, 9, 3, 12, 5, tzinfo=UTC)
OTHER_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")


def _admission_copy(admission: AdmissionResult, **overrides: object) -> AdmissionResult:
    fields = admission.model_dump(exclude={"result_digest"})
    fields.update(overrides)
    return AdmissionResult.build(fields)


def _runtime_copy(runtime: RuntimeGateSnapshot, **overrides: object) -> RuntimeGateSnapshot:
    fields = runtime.model_dump(exclude={"snapshot_digest"})
    fields.update(overrides)
    return RuntimeGateSnapshot.build(fields)


def _evaluate(
    proposal: Any = None,
    admission: Any = None,
    capability: Any = None,
    runtime: Any = None,
    evaluated_at: datetime = EVALUATED_AT,
):
    if proposal is None:
        proposal, default_capability, default_admission = admitted_context()
        capability = default_capability if capability is None else capability
        admission = default_admission if admission is None else admission
    if runtime is None:
        runtime = runtime_snapshot(proposal, admission)
    return evaluate_runtime_gates(
        proposal,
        admission=admission,
        capability=capability,
        runtime=runtime,
        evaluated_at=evaluated_at,
    )


def _reason(*args: Any, **kwargs: Any) -> Any:
    return _evaluate(*args, **kwargs).reason_code


def _profile_context(approval_class: str):
    profiles = {
        "AUTO_WITH_MANIFEST": ("PASSIVE", "T0", "CONTROL_PLANE_PASSIVE", 0),
        "LEASE": ("ACTIVE_READ_ONLY", "T1", "TARGET_EGRESS", 1),
        "OPERATOR_DATA_APPROVAL": ("SENSITIVE_OFFLINE", "T0", "NONE", 0),
        "OPERATOR_EXACT": ("AUTHENTICATION", "T2", "TARGET_EGRESS", 1),
        "EXACT_TARGET_AND_CAPABILITY": ("EXPLOIT", "T3", "TARGET_EGRESS", 1),
        "SEPARATE_OBJECTIVE": ("POST_ACCESS", "T3", "TARGET_EGRESS", 1),
    }
    risk, tier, path, requests = profiles[approval_class]
    target = TargetReference(target_kind="exact_host", canonical_value="app.example.com")
    proposal = make_proposal(
        target=target,
        requested_budget=BudgetRequest(target_requests=requests, deadline_seconds=30),
        target_identity_tier=tier,
    )
    capability = capability_snapshot(
        risk_class=risk,
        required_identity_tier=tier,
        approval_class=approval_class,
        network_path=path,
        max_target_requests=requests,
    )
    destinations = (egress_destination(),) if path == "TARGET_EGRESS" else ()
    proposal, capability, admission = admitted_context(
        proposal, capability, manifest(proposal, destinations=destinations)
    )
    return proposal, capability, admission


def _grant_for(proposal: Any, admission: Any, capability: Any, **overrides: object):
    objective = capability.approval_class == "SEPARATE_OBJECTIVE"
    fields = _grant(
        proposal_id=proposal.proposal_id,
        proposal_digest=proposal.proposal_digest,
        admission_result_digest=admission.result_digest,
        capability_id=proposal.capability_id,
        target=proposal.target.model_dump(),
        approval_class=capability.approval_class,
        objective_ref="objective-001" if objective else None,
        objective_binding_digest="0" * 64 if objective else None,
    )
    fields.update(overrides)
    return fields


def _target_runtime(approval_class: str = "LEASE", **overrides: object):
    proposal, capability, admission = _profile_context(approval_class)
    runtime = runtime_snapshot(proposal, admission, **overrides)
    return proposal, capability, admission, runtime


def _budget_for(
    proposal: Any,
    *,
    hard_stop: datetime | None = None,
    **overrides: int,
) -> dict[str, Any]:
    values = {
        "request_limit": overrides.get("request_limit", 10),
        "cost_microunit_limit": overrides.get("cost_limit", 10_000_000),
        "consumed_requests": overrides.get("consumed_requests", 0),
        "reserved_requests": overrides.get("reserved_requests", 0),
        "consumed_microunits": overrides.get("consumed_cost", 0),
        "reserved_microunits": overrides.get("reserved_cost", 0),
        "hard_stop_until": _ts(14, 0) if hard_stop is None else hard_stop,
    }
    return _budget(
        agent_instance_id=proposal.agent_instance_id,
        engagement_account=_account(**values),
        agent_account=_account(agent=proposal.agent_instance_id, **values),
    )


def test_runtime_gate_rejects_cross_boundary_substitution() -> None:
    proposal, capability, admission = admitted_context()
    sparse = runtime_snapshot(
        proposal, admission, budget=None, engagement=None, lock=None, opsec=None
    )
    admission_cases = (
        {"tenant_id": "tenant-b"},
        {"engagement_id": OTHER_ID},
        {"proposal_id": OTHER_ID},
        {"proposal_digest": "9" * 64},
    )
    for mutation in admission_cases:
        changed = _admission_copy(admission, **mutation)
        assert _reason(proposal, changed, capability, sparse) == "ADMISSION_BINDING_MISMATCH"

    runtime_cases = (
        {"tenant_id": "tenant-b"},
        {"engagement_id": OTHER_ID},
        {"proposal_id": OTHER_ID},
        {"proposal_digest": "8" * 64},
        {"agent_instance_id": OTHER_ID},
        {"admission_result_digest": "7" * 64},
        {"capability_id": "scout.other.v1"},
    )
    for mutation in runtime_cases:
        changed = _runtime_copy(sparse, **mutation)
        assert _reason(proposal, admission, capability, changed) == "RUNTIME_BINDING_MISMATCH"

    capability_cases = (
        capability_snapshot(capability_id="scout.other.v1"),
        capability_snapshot(registry_schema_version=2),
        capability_snapshot(registry_digest="6" * 64),
        capability_snapshot(supply_chain_digest="5" * 64),
        capability_snapshot(owner_agent="Strike"),
    )
    for changed in capability_cases:
        assert _reason(proposal, admission, changed, sparse) == "CAPABILITY_BINDING_MISMATCH"


def test_runtime_gate_precedence_is_fixed() -> None:
    proposal, capability, admission = admitted_context()
    sparse = runtime_snapshot(
        proposal,
        admission,
        captured_at=_ts(12, 0),
        budget=None,
        engagement=None,
        lock=None,
        opsec=None,
    )
    changed_runtime = _runtime_copy(sparse, proposal_id=OTHER_ID)
    assert _reason(proposal, admission, capability, changed_runtime) == "RUNTIME_BINDING_MISMATCH"
    changed_capability = capability_snapshot(owner_agent="Strike")
    assert _reason(proposal, admission, changed_capability, sparse) == "CAPABILITY_BINDING_MISMATCH"

    denied_capability = capability_snapshot(lifecycle="PLANNED")
    _, _, denied_admission = admitted_context(capability=denied_capability)
    denied_runtime = runtime_snapshot(
        proposal, denied_admission, budget=None, engagement=None, lock=None, opsec=None
    )
    assert _reason(proposal, denied_admission, denied_capability, denied_runtime) == (
        "ADMISSION_NOT_ADMITTED"
    )

    future = make_proposal(created_at=_ts(12, 6), expires_at=_ts(12, 16))
    future, future_capability, future_admission = admitted_context(future, evaluated_at=_ts(12, 6))
    future_runtime = runtime_snapshot(future, future_admission, engagement=None)
    assert _reason(future, future_admission, future_capability, future_runtime) == (
        "PROPOSAL_NOT_YET_VALID"
    )
    assert (
        _reason(proposal, admission, capability, sparse, proposal.expires_at) == "PROPOSAL_EXPIRED"
    )
    assert _reason(proposal, admission, capability, sparse) == "ENGAGEMENT_STATE_MISSING"

    incoherent = runtime_snapshot(proposal, admission, engagement=_run(transitioned_at=_ts(12, 3)))
    assert _reason(proposal, admission, capability, incoherent) == "RUNTIME_CONTEXT_INCOHERENT"
    stopped = runtime_snapshot(proposal, admission, engagement=_run("STOPPED"), budget=None)
    assert _reason(proposal, admission, capability, stopped) == "ENGAGEMENT_STOPPED"

    target, target_capability, target_admission, _ = _target_runtime()
    no_opsec = runtime_snapshot(target, target_admission, opsec=None, budget=None)
    assert _reason(target, target_admission, target_capability, no_opsec) == "OPSEC_STATE_MISSING"
    burned = runtime_snapshot(
        target, target_admission, opsec=_opsec("BURNED"), fresh_until=_ts(12, 4)
    )
    assert _reason(target, target_admission, target_capability, burned) == "OPSEC_BURNED"
    no_budget = runtime_snapshot(target, target_admission, budget=None, lock=None)
    assert _reason(target, target_admission, target_capability, no_budget) == "BUDGET_STATE_MISSING"


def test_runtime_gate_enforces_exact_approval() -> None:
    for approval_class in ("AUTO_WITH_MANIFEST", "LEASE"):
        proposal, capability, admission = _profile_context(approval_class)
        runtime = runtime_snapshot(proposal, admission, approval_grant=None)
        assert _reason(proposal, admission, capability, runtime) is None
        irrelevant = _grant_for(
            proposal,
            admission,
            capability,
            approval_class="OPERATOR_EXACT",
            target={"target_kind": "exact_host", "canonical_value": "other.example.com"},
            revocation_ref="revoke-001",
            revocation_timestamp=_ts(12, 4),
            revocation_digest="a" * 64,
        )
        optional = runtime_snapshot(proposal, admission, approval_grant=irrelevant)
        assert _reason(proposal, admission, capability, optional) is None

    required = (
        "OPERATOR_DATA_APPROVAL",
        "OPERATOR_EXACT",
        "EXACT_TARGET_AND_CAPABILITY",
        "SEPARATE_OBJECTIVE",
    )
    for approval_class in required:
        proposal, capability, admission = _profile_context(approval_class)
        missing = runtime_snapshot(proposal, admission, approval_grant=None)
        assert _reason(proposal, admission, capability, missing) == "APPROVAL_MISSING"
        grant = _grant_for(proposal, admission, capability)
        approved = runtime_snapshot(proposal, admission, approval_grant=grant)
        assert _reason(proposal, admission, capability, approved) is None

    proposal, capability, admission = _profile_context("OPERATOR_EXACT")
    cases = (
        ({"approval_class": "LEASE"}, "APPROVAL_CLASS_MISMATCH"),
        (
            {"target": {"target_kind": "exact_host", "canonical_value": "other.example.com"}},
            "APPROVAL_TARGET_MISMATCH",
        ),
        ({"valid_from": _ts(12, 6), "valid_until": _ts(13, 0)}, "APPROVAL_NOT_YET_VALID"),
        ({"valid_until": EVALUATED_AT}, "APPROVAL_EXPIRED"),
        (
            {
                "revocation_ref": "revoke",
                "revocation_timestamp": EVALUATED_AT,
                "revocation_digest": "a" * 64,
            },
            "APPROVAL_REVOKED",
        ),
    )
    for mutation, reason in cases:
        grant = _grant_for(proposal, admission, capability, **mutation)
        capture = EVALUATED_AT if reason == "APPROVAL_REVOKED" else _ts(12, 2)
        runtime = runtime_snapshot(proposal, admission, approval_grant=grant, captured_at=capture)
        assert _reason(proposal, admission, capability, runtime) == reason
    grant = _grant_for(proposal, admission, capability, valid_from=EVALUATED_AT)
    runtime = runtime_snapshot(proposal, admission, approval_grant=grant, captured_at=EVALUATED_AT)
    assert _reason(proposal, admission, capability, runtime) is None


def test_runtime_gate_enforces_hierarchical_budget_without_mutation() -> None:
    estimates = ResourceEstimates(risk=0.1, cost=1.0000001, information_gain=0.4, opsec_noise=0.2)
    proposal = make_proposal(estimates=estimates)
    proposal, capability, admission = admitted_context(proposal)
    exact = _budget_for(
        proposal,
        request_limit=3,
        cost_limit=1_000_006,
        consumed_requests=2,
        reserved_requests=1,
        consumed_cost=3,
        reserved_cost=2,
        hard_stop=EVALUATED_AT + timedelta(seconds=30),
    )
    runtime = runtime_snapshot(proposal, admission, budget=exact)
    before = runtime.model_dump_json()
    result = _evaluate(proposal, admission, capability, runtime)
    assert result.reason_code is None
    assert result.requested_cost_microunits == 1_000_001
    assert runtime.model_dump_json() == before

    deadline = _budget_for(proposal, hard_stop=EVALUATED_AT + timedelta(seconds=29))
    runtime = runtime_snapshot(proposal, admission, budget=deadline)
    assert _reason(proposal, admission, capability, runtime) == "BUDGET_DEADLINE_EXCEEDED"

    requested, requested_capability, requested_admission, _ = _target_runtime()
    request_excess = _budget_for(
        requested, request_limit=2, consumed_requests=1, reserved_requests=1
    )
    request_excess["engagement_account"] = _account(cost_microunit_limit=10_000_000)
    runtime = runtime_snapshot(requested, requested_admission, budget=request_excess)
    assert _reason(requested, requested_admission, requested_capability, runtime) == (
        "BUDGET_CAPACITY_EXCEEDED"
    )

    cost_excess = _budget_for(proposal, cost_limit=1_000_005, consumed_cost=3, reserved_cost=2)
    cost_excess["agent_account"] = _account(
        agent=proposal.agent_instance_id, cost_microunit_limit=10_000_000
    )
    runtime = runtime_snapshot(proposal, admission, budget=cost_excess)
    assert _reason(proposal, admission, capability, runtime) == "BUDGET_CAPACITY_EXCEEDED"


def test_runtime_gate_enforces_target_egress_lock() -> None:
    proposal, capability, admission, _ = _target_runtime()
    allowed_holders = (
        None,
        _held(proposal.proposal_id, _ts(12, 6)),
        _held(OTHER_ID, EVALUATED_AT),
    )
    for holder in allowed_holders:
        runtime = runtime_snapshot(proposal, admission, lock=_lock(holder=holder))
        assert _reason(proposal, admission, capability, runtime) is None

    held = runtime_snapshot(
        proposal,
        admission,
        lock=_lock(holder=_held(OTHER_ID, _ts(12, 6))),
    )
    result = _evaluate(proposal, admission, capability, held)
    assert result.outcome == "WAIT_FOR_RESOURCE"
    assert result.reason_code == "RESOURCE_LOCK_HELD"

    passive, passive_capability, passive_admission = admitted_context()
    irrelevant = runtime_snapshot(passive, passive_admission, lock=None)
    assert _reason(passive, passive_admission, passive_capability, irrelevant) is None


def test_runtime_gate_enforces_stop_opsec_and_temporal_boundaries() -> None:
    proposal, capability, admission, _ = _target_runtime()
    stopped = runtime_snapshot(
        proposal,
        admission,
        engagement=_run("STOPPED"),
        opsec=_opsec("BURNED"),
    )
    assert _reason(proposal, admission, capability, stopped) == "ENGAGEMENT_STOPPED"

    for state, reason in (("BURNED", "OPSEC_BURNED"), ("HOT", "OPSEC_HOT")):
        runtime = runtime_snapshot(proposal, admission, opsec=_opsec(state))
        assert _reason(proposal, admission, capability, runtime) == reason
    for state in ("COOL", "WARM"):
        runtime = runtime_snapshot(proposal, admission, opsec=_opsec(state))
        assert _reason(proposal, admission, capability, runtime) is None
    lower_bound = runtime_snapshot(proposal, admission, captured_at=EVALUATED_AT)
    assert _reason(proposal, admission, capability, lower_bound) is None

    not_yet = runtime_snapshot(proposal, admission, captured_at=_ts(12, 6), fresh_until=_ts(12, 7))
    assert _reason(proposal, admission, capability, not_yet) == ("RUNTIME_SNAPSHOT_NOT_YET_VALID")
    expired = runtime_snapshot(proposal, admission, fresh_until=EVALUATED_AT)
    assert _reason(proposal, admission, capability, expired) == "RUNTIME_SNAPSHOT_EXPIRED"
    stale_opsec = runtime_snapshot(proposal, admission, opsec=_opsec(fresh_until=EVALUATED_AT))
    assert _reason(proposal, admission, capability, stale_opsec) == "OPSEC_STATE_EXPIRED"

    budget = _budget_for(proposal, hard_stop=EVALUATED_AT)
    expired_budget = runtime_snapshot(proposal, admission, budget=budget)
    assert _reason(proposal, admission, capability, expired_budget) == "BUDGET_WINDOW_EXPIRED"
    missing_lock = runtime_snapshot(proposal, admission, lock=None)
    assert _reason(proposal, admission, capability, missing_lock) == "LOCK_STATE_MISSING"


def test_runtime_gate_rejects_causally_future_nested_facts() -> None:
    def check(proposal: Any, capability: Any, admission: Any, runtime: Any) -> None:
        assert _reason(proposal, admission, capability, runtime) == "RUNTIME_CONTEXT_INCOHERENT"

    proposal, capability, admission = admitted_context()
    before_admission = runtime_snapshot(proposal, admission, captured_at=_ts(12, 0))
    check(proposal, capability, admission, before_admission)
    future_engagement = runtime_snapshot(
        proposal, admission, engagement=_run(transitioned_at=_ts(12, 3))
    )
    check(proposal, capability, admission, future_engagement)

    target, target_capability, target_admission, _ = _target_runtime()
    future_opsec = runtime_snapshot(target, target_admission, opsec=_opsec(observed_at=_ts(12, 3)))
    check(target, target_capability, target_admission, future_opsec)
    holder = _held(OTHER_ID, _ts(12, 6), acquired_at=_ts(12, 3))
    future_lock = runtime_snapshot(target, target_admission, lock=_lock(holder=holder))
    check(target, target_capability, target_admission, future_lock)

    required, required_capability, required_admission = _profile_context("OPERATOR_EXACT")
    grant = _grant_for(
        required,
        required_admission,
        required_capability,
        revocation_ref="revoke",
        revocation_timestamp=_ts(12, 3),
        revocation_digest="a" * 64,
    )
    check(
        required,
        required_capability,
        required_admission,
        runtime_snapshot(required, required_admission, approval_grant=grant),
    )


def test_runtime_gate_is_pure_deterministic_and_does_not_mutate_inputs() -> None:
    proposal, capability, admission, runtime = _target_runtime()
    inputs = (proposal, admission, capability, runtime)
    before = tuple(item.model_dump_json() for item in inputs)
    first = _evaluate(proposal, admission, capability, runtime)
    second = _evaluate(proposal, admission, capability, runtime)
    after = tuple(item.model_dump_json() for item in inputs)
    assert first.model_dump_json() == second.model_dump_json()
    assert first.result_digest == second.result_digest
    assert before == after
    with pytest.raises(RuntimeGateEvaluationError, match="evaluation arguments failed validation"):
        _evaluate(evaluated_at=datetime(2026, 9, 3, 12, 5))
