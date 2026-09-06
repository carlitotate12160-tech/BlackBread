"""Runtime-gate conditions, fixed fail-closed precedence, determinism, and typed argument errors.

Every case drives the composed evaluator with one capability. The runtime snapshot is bound to the
admission the evaluator recomputes, so a well-formed case reaches the runtime checks and each fault
selects exactly one expected reason.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from blackbread.conductor.contracts import BudgetRequest, TargetReference
from blackbread.policy.runtime_gate import RuntimeGateEvaluationError, evaluate_runtime_gates
from tests.conductor._builders import make_proposal
from tests.policy._builders import capability_snapshot, egress_destination, manifest
from tests.policy._runtime_builders import (
    _account,
    _budget,
    _held,
    _lock,
    _opsec,
    _run,
    _ts,
    compute_admission,
    grant_for,
    runtime_case,
    runtime_snapshot,
)

AGENT = uuid.UUID("33333333-3333-3333-3333-333333333333")
OTHER = uuid.UUID("99999999-9999-9999-9999-999999999999")


def _evaluate(**overrides: Any) -> Any:
    case = runtime_case(**overrides)
    return evaluate_runtime_gates(case.pop("proposal"), **case)


def _reason(**overrides: Any) -> Any:
    return _evaluate(**overrides).reason_code


def _auth_proposal() -> Any:
    return make_proposal(
        target=TargetReference(target_kind="exact_host", canonical_value="app.example.com"),
        requested_budget=BudgetRequest(target_requests=1, deadline_seconds=30),
        target_identity_tier="T2",
    )


def _auth_capability() -> Any:
    return capability_snapshot(
        risk_class="AUTHENTICATION",
        required_identity_tier="T2",
        approval_class="OPERATOR_EXACT",
        network_path="TARGET_EGRESS",
        max_target_requests=1,
    )


def _egress(**runtime_overrides: Any) -> Any:
    return _reason(proposal=_auth_proposal(), capability=_auth_capability(), **runtime_overrides)


def _egress_with_grant(**grant_overrides: Any) -> Any:
    proposal = _auth_proposal()
    capability = _auth_capability()
    destination_manifest = manifest(proposal, destinations=(egress_destination(),))
    admission = compute_admission(proposal, capability, destination_manifest)
    grant = grant_for(proposal, admission, capability, **grant_overrides)
    case = runtime_case(
        proposal=proposal,
        capability=capability,
        destination_manifest=destination_manifest,
        runtime=runtime_snapshot(proposal, admission, approval_grant=grant),
    )
    return evaluate_runtime_gates(case.pop("proposal"), **case).reason_code


def _budget_over(**account: Any) -> dict[str, Any]:
    account.setdefault("cost_microunit_limit", 10_000_000)
    return _budget(
        engagement_account=_account(**account), agent_account=_account(agent=AGENT, **account)
    )


def test_passive_case_passes() -> None:
    result = _evaluate()
    assert result.outcome == "PASSED_FOR_FINAL_DECISION"
    assert result.reason_code is None


def test_egress_case_passes() -> None:
    proposal = _auth_proposal()
    result = evaluate_runtime_gates(
        **{
            k: v
            for k, v in runtime_case(proposal=proposal, capability=_auth_capability()).items()
            if k != "proposal"
        },
        proposal=proposal,
    )
    assert result.outcome == "PASSED_FOR_FINAL_DECISION"


@pytest.mark.parametrize(
    "override",
    [{"admission_result_digest": "0" * 64}, {"capability_id": "scout.other_thing.v1"}],
)
def test_runtime_binding_mismatch(override: dict[str, Any]) -> None:
    assert _reason(**override) == "RUNTIME_BINDING_MISMATCH"


def test_admission_denied() -> None:
    assert _reason(capability=capability_snapshot(lifecycle="RETIRED")) == "ADMISSION_DENIED"


def test_engagement_state_missing() -> None:
    assert _reason(engagement=None) == "ENGAGEMENT_STATE_MISSING"


def test_engagement_stopped() -> None:
    assert _reason(engagement=_run(state="STOPPED")) == "ENGAGEMENT_STOPPED"


def test_runtime_context_incoherent() -> None:
    # A nested fact observed after the snapshot was captured is incoherent.
    assert _reason(engagement=_run(transitioned_at=_ts(12, 9))) == "RUNTIME_CONTEXT_INCOHERENT"


def test_opsec_state_missing() -> None:
    assert _egress(opsec=None) == "OPSEC_STATE_MISSING"


def test_opsec_burned() -> None:
    assert _egress(opsec=_opsec(state="BURNED")) == "OPSEC_BURNED"


def test_opsec_hot() -> None:
    assert _egress(opsec=_opsec(state="HOT")) == "OPSEC_HOT"


def test_opsec_state_expired() -> None:
    assert _egress(opsec=_opsec(fresh_until=_ts(12, 4))) == "OPSEC_STATE_EXPIRED"


def test_runtime_snapshot_not_yet_valid() -> None:
    assert _reason(evaluated_at=_ts(12, 3)) == "RUNTIME_SNAPSHOT_NOT_YET_VALID"


def test_runtime_snapshot_expired() -> None:
    assert _reason(evaluated_at=_ts(12, 11)) == "RUNTIME_SNAPSHOT_EXPIRED"


def test_budget_state_missing() -> None:
    assert _reason(budget=None) == "BUDGET_STATE_MISSING"


def test_budget_window_expired() -> None:
    assert _reason(budget=_budget_over(hard_stop_until=_ts(12, 0))) == "BUDGET_WINDOW_EXPIRED"


def test_budget_deadline_exceeded() -> None:
    hard_stop = datetime(2026, 9, 3, 12, 5, 15, tzinfo=UTC)
    assert _reason(budget=_budget_over(hard_stop_until=hard_stop)) == "BUDGET_DEADLINE_EXCEEDED"


def test_budget_capacity_exceeded() -> None:
    assert (
        _reason(budget=_budget_over(cost_microunit_limit=1_000_000)) == "BUDGET_CAPACITY_EXCEEDED"
    )


def test_lock_state_missing() -> None:
    assert _egress(lock=None) == "LOCK_STATE_MISSING"


def test_resource_lock_held() -> None:
    held = _lock(holder=_held(OTHER, _ts(13, 0)))
    assert _egress(lock=held) == "RESOURCE_LOCK_HELD"


def test_approval_missing() -> None:
    assert _egress(approval_grant=None) == "APPROVAL_MISSING"


def test_approval_class_mismatch() -> None:
    assert (
        _egress_with_grant(approval_class="EXACT_TARGET_AND_CAPABILITY")
        == "APPROVAL_CLASS_MISMATCH"
    )


def test_approval_target_mismatch() -> None:
    other = {"target_kind": "exact_host", "canonical_value": "other.example.com"}
    assert _egress_with_grant(target=other) == "APPROVAL_TARGET_MISMATCH"


def test_approval_not_yet_valid() -> None:
    assert (
        _egress_with_grant(valid_from=_ts(12, 30), valid_until=_ts(13, 0))
        == "APPROVAL_NOT_YET_VALID"
    )


def test_approval_expired() -> None:
    assert _egress_with_grant(valid_from=_ts(11, 0), valid_until=_ts(12, 0)) == "APPROVAL_EXPIRED"


def test_approval_revoked() -> None:
    revoked = _egress_with_grant(
        revocation_ref="rev-001", revocation_timestamp=_ts(12, 0), revocation_digest="a" * 64
    )
    assert revoked == "APPROVAL_REVOKED"


def test_precedence_runtime_binding_before_admission_denial() -> None:
    # Both a binding mismatch and admission denial hold; the binding failure wins.
    assert (
        _reason(
            capability=capability_snapshot(lifecycle="RETIRED"), admission_result_digest="0" * 64
        )
        == "RUNTIME_BINDING_MISMATCH"
    )


def test_precedence_admission_denial_before_runtime_fact() -> None:
    # Admission denial precedes a missing runtime engagement fact.
    assert (
        _reason(capability=capability_snapshot(lifecycle="RETIRED"), engagement=None)
        == "ADMISSION_DENIED"
    )


def test_deterministic_for_identical_inputs() -> None:
    first, second = _evaluate(), _evaluate()
    assert first == second
    assert first.result_digest == second.result_digest


def test_naive_evaluation_time_raises() -> None:
    case = runtime_case()
    case["evaluated_at"] = datetime(2026, 9, 3, 12, 5)
    with pytest.raises(RuntimeGateEvaluationError):
        evaluate_runtime_gates(case.pop("proposal"), **case)


def test_wrong_argument_type_raises() -> None:
    case = runtime_case()
    case["capability"] = "not-a-capability"
    with pytest.raises(RuntimeGateEvaluationError):
        evaluate_runtime_gates(case.pop("proposal"), **case)
