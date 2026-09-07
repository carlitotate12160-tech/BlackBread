"""Tests for the composed final policy evaluator (M1.4b2c)."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from blackbread.conductor.contracts import ActionProposal, TargetReference
from blackbread.policy.evaluation import PolicyEvaluationError, evaluate_policy
from blackbread.policy.runtime_gate import evaluate_runtime_gates
from tests.conductor._builders import make_proposal
from tests.policy._builders import capability_snapshot
from tests.policy._runtime_builders import _held, _lock, _opsec, _run, runtime_case

DECISION_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
DECIDED_AT = datetime(2026, 9, 3, 12, 5, tzinfo=UTC)


def _eval_kwargs(**overrides: Any) -> dict[str, Any]:
    runtime_overrides = overrides.pop("runtime_overrides", {})
    evaluated_at = overrides.pop("evaluated_at", DECIDED_AT)
    # Pass all remaining overrides (proposal, capability, etc) plus runtime overrides
    kwargs = runtime_case(evaluated_at=evaluated_at, **overrides, **runtime_overrides)
    kwargs["decision_id"] = DECISION_ID
    kwargs["decided_at"] = kwargs.pop("evaluated_at")
    return kwargs


def test_composition_and_substitution_prevention() -> None:
    """Verify composed passing case preserves identity and matches separate runtime digest."""
    kwargs = _eval_kwargs()
    decision = evaluate_policy(**kwargs)

    assert decision.outcome == "ALLOW"
    assert decision.reason_code is None

    # Verify proposal identity preservation
    proposal: ActionProposal = kwargs["proposal"]
    assert decision.tenant_id == proposal.tenant_id
    assert decision.engagement_id == proposal.engagement_id
    assert decision.proposal_id == proposal.proposal_id
    assert decision.proposal_digest == proposal.proposal_digest
    assert decision.graph_version == proposal.graph_version

    # Verify continuity against independent runtime evaluation
    runtime_kwargs = dict(kwargs)
    runtime_kwargs.pop("decision_id")
    runtime_kwargs["evaluated_at"] = runtime_kwargs.pop("decided_at")
    expected_result = evaluate_runtime_gates(**runtime_kwargs)
    assert decision.runtime_gate_result_digest == expected_result.result_digest


def test_admission_denied_regression() -> None:
    """Verify capability denied by real admission yields ADMISSION_DENIED."""
    # Build a capability with a tier requirement higher than the proposal's T0
    cap = capability_snapshot(required_identity_tier="T1")
    kwargs = _eval_kwargs(capability=cap)

    decision = evaluate_policy(**kwargs)
    assert decision.outcome == "DENY"
    assert decision.reason_code == "ADMISSION_DENIED"


def test_operator_required_without_approval_fails() -> None:
    """Verify operator-required case without approval cannot yield ALLOW."""
    # AUTO_WITH_MANIFEST is exempt, let's use OPERATOR_EXACT which requires a grant
    cap = capability_snapshot(
        risk_class="AUTHENTICATION",
        required_identity_tier="T2",
        approval_class="OPERATOR_EXACT",
        network_path="TARGET_EGRESS",
    )
    proposal = make_proposal(
        target_identity_tier="T2",
        target=TargetReference(target_kind="exact_host", canonical_value="app.example.com"),
    )
    kwargs = _eval_kwargs(
        capability=cap, proposal=proposal, runtime_overrides={"approval_grant": None}
    )

    decision = evaluate_policy(**kwargs)
    assert decision.outcome == "APPROVAL_REQUIRED"
    assert decision.reason_code == "APPROVAL_MISSING"


def test_lease_semantics_without_operator_grant() -> None:
    """Verify LEASE approval class may yield ALLOW without an operator grant."""
    # LEASE is exempt from operator grants at the runtime gate stage
    # Must use a coherent risk profile to pass admission evaluation
    cap = capability_snapshot(
        risk_class="ACTIVE_READ_ONLY",
        required_identity_tier="T1",
        approval_class="LEASE",
        network_path="TARGET_EGRESS",
    )
    proposal = make_proposal(
        target_identity_tier="T1",
        target=TargetReference(target_kind="exact_host", canonical_value="app.example.com"),
    )
    kwargs = _eval_kwargs(
        capability=cap, proposal=proposal, runtime_overrides={"approval_grant": None}
    )

    decision = evaluate_policy(**kwargs)
    assert decision.outcome == "ALLOW"
    assert decision.reason_code is None

    # Verify decision retains no execution token or activation fields
    fields = decision.model_fields.keys()
    for forbidden in ("lease_id", "work_order_id", "executable_token", "activation"):
        assert forbidden not in fields


@pytest.mark.parametrize(
    "runtime_overrides, expected_outcome, expected_reason",
    [
        # Budget exhausted
        (
            {"budget": None},  # Missing budget state
            "STALE_CONTEXT",
            "BUDGET_STATE_MISSING",
        ),
        # Wait for resource (Lock held)
        (
            {
                "lock": _lock(
                    holder=_held(
                        uuid.UUID("99999999-9999-9999-9999-999999999999"),
                        DECIDED_AT + timedelta(minutes=5),
                    )
                )
            },
            "WAIT_FOR_RESOURCE",
            "RESOURCE_LOCK_HELD",
        ),
        # Engagement stopped
        (
            {"engagement": _run(state="STOPPED")},
            "ENGAGEMENT_STOPPED",
            "ENGAGEMENT_STOPPED",
        ),
        # OPSEC hold
        (
            {"opsec": _opsec(state="HOT")},
            "OPSEC_HOLD",
            "OPSEC_HOT",
        ),
    ],
)
def test_representative_real_outcomes(
    runtime_overrides: dict[str, Any], expected_outcome: str, expected_reason: str
) -> None:
    """Exercise DENY, APPROVAL_REQUIRED, WAIT_FOR_RESOURCE, STALE_CONTEXT, STOPPED, OPSEC_HOLD."""
    cap = capability_snapshot(
        risk_class="ACTIVE_READ_ONLY",
        required_identity_tier="T1",
        approval_class="LEASE",
        network_path="TARGET_EGRESS",
    )
    proposal = make_proposal(
        target_identity_tier="T1",
        target=TargetReference(target_kind="exact_host", canonical_value="app.example.com"),
    )
    kwargs = _eval_kwargs(capability=cap, proposal=proposal, runtime_overrides=runtime_overrides)

    decision = evaluate_policy(**kwargs)
    assert decision.outcome == expected_outcome
    assert decision.reason_code == expected_reason


def test_timestamp_boundary_freshness() -> None:
    """Verify decided_at exactly fresh_until triggers RUNTIME_SNAPSHOT_EXPIRED."""
    # Default snapshot has fresh_until = captured_at + 30m. Let's force it.
    fresh_until = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    captured_at = fresh_until - timedelta(minutes=5)

    # Evaluate exactly at fresh_until (expired). We must pass this as evaluated_at
    # so the admission digest baked into the runtime snapshot matches.
    kwargs = _eval_kwargs(
        evaluated_at=fresh_until,
        runtime_overrides={"fresh_until": fresh_until, "captured_at": captured_at},
    )

    decision = evaluate_policy(**kwargs)
    assert decision.outcome == "STALE_CONTEXT"
    assert decision.reason_code == "RUNTIME_SNAPSHOT_EXPIRED"


def test_cross_tenant_engagement_substitution() -> None:
    """Verify coherent cross-tenant and cross-engagement substitutions fail closed."""
    # Cross-tenant substitution
    kwargs = _eval_kwargs(
        runtime_overrides={
            "tenant_id": "tenant-b",
            "budget": None,
            "lock": None,
            "engagement": None,
            "opsec": None,
            "approval_grant": None,
        }
    )
    decision = evaluate_policy(**kwargs)
    assert decision.outcome == "DENY"
    assert decision.reason_code == "RUNTIME_BINDING_MISMATCH"

    # Cross-engagement substitution
    kwargs = _eval_kwargs(
        runtime_overrides={
            "engagement_id": uuid.uuid4(),
            "budget": None,
            "lock": None,
            "engagement": None,
            "opsec": None,
            "approval_grant": None,
        }
    )
    decision = evaluate_policy(**kwargs)
    assert decision.outcome == "DENY"
    assert decision.reason_code == "RUNTIME_BINDING_MISMATCH"


@pytest.mark.parametrize(
    "arg_name, invalid_value",
    [
        ("decision_id", None),
        ("decision_id", "44444444-4444-4444-4444-444444444444"),
        ("decision_id", 44444444),
        ("decided_at", None),
        ("decided_at", "2026-09-03T12:05:00Z"),
        ("decided_at", 1725365100),
        ("decided_at", datetime(2026, 9, 3, 12, 5)),  # Naive
        (
            "decided_at",
            datetime(2026, 9, 3, 12, 5, tzinfo=timezone(timedelta(hours=1))),
        ),  # Nonzero offset
        ("proposal", object()),
        ("policy", object()),
        ("identity", object()),
        ("capability", object()),
        ("manifest", object()),
        ("runtime", object()),
    ],
)
def test_public_argument_failures(arg_name: str, invalid_value: Any) -> None:
    """Verify typed fail-closed failures for malformed arguments."""
    kwargs = _eval_kwargs()
    kwargs[arg_name] = invalid_value

    with pytest.raises(PolicyEvaluationError, match="evaluation arguments failed validation"):
        evaluate_policy(**kwargs)


def test_forged_runtime_gate_result_signature() -> None:
    """Verify a forged passing RuntimeGateResult has no accepted input position."""
    sig = inspect.signature(evaluate_policy)
    for param in sig.parameters.values():
        assert "RuntimeGateResult" not in str(param.annotation)
        assert "AdmissionResult" not in str(param.annotation)
        assert "PolicyDecision" not in str(param.annotation)
