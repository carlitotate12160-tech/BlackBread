"""The composed evaluator accepts the capability once; cross-stage substitution is unrepresentable.

The PR #65 defect was that ``evaluate_runtime_gates`` took a caller-supplied ``AdmissionResult``
separately from the runtime ``capability``, so a strong admission could be paired with a weaker
runtime capability, and an admission-denied capability could reach a passed result. b2b-R removes
that seam: the public evaluator takes exactly one capability and computes admission itself. These
tests prove there is no admission/binding input position and that admission is really recomputed.
"""

from __future__ import annotations

import inspect

from blackbread.conductor.contracts import BudgetRequest, TargetReference
from blackbread.policy.runtime_gate import evaluate_runtime_gates
from tests.conductor._builders import make_proposal
from tests.policy._builders import capability_snapshot
from tests.policy._runtime_builders import runtime_case


def _evaluate(**case_overrides: object) -> object:
    case = runtime_case(**case_overrides)  # type: ignore[arg-type]
    return evaluate_runtime_gates(case.pop("proposal"), **case)


def _auth_proposal():
    return make_proposal(
        target=TargetReference(target_kind="exact_host", canonical_value="app.example.com"),
        requested_budget=BudgetRequest(target_requests=1, deadline_seconds=30),
        target_identity_tier="T2",
    )


def _auth_capability():
    return capability_snapshot(
        risk_class="AUTHENTICATION",
        required_identity_tier="T2",
        approval_class="OPERATOR_EXACT",
        network_path="TARGET_EGRESS",
        max_target_requests=1,
    )


def test_public_evaluator_has_no_admission_or_binding_parameter() -> None:
    params = set(inspect.signature(evaluate_runtime_gates).parameters)
    assert params == {
        "proposal",
        "policy",
        "identity",
        "capability",
        "manifest",
        "runtime",
        "evaluated_at",
    }
    # No caller-supplied admission result or admission-to-runtime binding input exists.
    for forbidden in ("admission", "admission_result", "binding", "admission_runtime_binding"):
        assert forbidden not in params


def test_runtime_evaluator_recomputes_admission_and_accepts_capability_once() -> None:
    # A genuine AUTHENTICATION capability (OPERATOR_EXACT) drives BOTH admission and runtime. Without
    # approval grant, the runtime enforces the strong capability's approval requirement. Under the
    # the old seam a weaker PASSIVE capability could be substituted at runtime to skip approval;
    # here there is only one capability position, so APPROVAL_MISSING is forced, not PASSED.
    result = _evaluate(
        proposal=_auth_proposal(), capability=_auth_capability(), approval_grant=None
    )
    assert result.outcome == "APPROVAL_REQUIRED"
    assert result.reason_code == "APPROVAL_MISSING"


def test_admission_denial_prevents_runtime_pass_lifecycle() -> None:
    # A RETIRED capability is denied only by admission (runtime gates never check lifecycle). A
    # passed result would prove admission was not recomputed inside the evaluator.
    result = _evaluate(capability=capability_snapshot(lifecycle="RETIRED"))
    assert result.outcome == "DENY"
    assert result.reason_code == "ADMISSION_DENIED"


def test_admission_denial_prevents_runtime_pass_incoherent_profile() -> None:
    # A PASSIVE risk class with an OPERATOR_EXACT approval class is an incoherent registry profile
    # that admission rejects; no runtime fact can turn it into PASSED_FOR_FINAL_DECISION.
    result = _evaluate(capability=capability_snapshot(approval_class="OPERATOR_EXACT"))
    assert result.outcome == "DENY"
    assert result.reason_code == "ADMISSION_DENIED"


def test_admission_denied_capability_cannot_pass_even_with_valid_runtime() -> None:
    # The runtime snapshot for a denied admission is otherwise valid; admission denial still wins.
    result = _evaluate(capability=capability_snapshot(lifecycle="SUSPENDED"))
    assert result.outcome != "PASSED_FOR_FINAL_DECISION"
    assert result.reason_code == "ADMISSION_DENIED"
