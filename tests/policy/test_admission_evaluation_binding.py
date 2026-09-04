"""Admission binding, freshness, lifecycle, profile, and precedence proofs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from blackbread.conductor.contracts import BudgetRequest, TargetReference
from blackbread.policy.admission import AdmissionEvaluationError, evaluate_admission
from tests.conductor._builders import graph_version, make_proposal
from tests.policy._builders import capability_snapshot, identity_snapshot, manifest, policy_snapshot

EVALUATED_AT = datetime(2026, 9, 3, 12, 5, tzinfo=UTC)


def _evaluate(**overrides: Any):
    proposal = overrides.get("proposal")
    policy = overrides.get("policy")
    identity = overrides.get("identity")
    capability = overrides.get("capability")
    destination_manifest = overrides.get("destination_manifest")
    evaluated_at = overrides.get("evaluated_at", EVALUATED_AT)
    proposal = make_proposal() if proposal is None else proposal
    policy = policy_snapshot() if policy is None else policy
    identity = identity_snapshot(proposal) if identity is None else identity
    capability = capability_snapshot() if capability is None else capability
    destination_manifest = (
        manifest(proposal) if destination_manifest is None else destination_manifest
    )
    return evaluate_admission(
        proposal,
        policy=policy,
        identity=identity,
        capability=capability,
        manifest=destination_manifest,
        evaluated_at=evaluated_at,
    )


def test_all_valid_bindings_admit_only_to_runtime_gates() -> None:
    result = _evaluate()
    assert result.outcome == "ADMITTED_FOR_RUNTIME_GATES"
    assert result.reason_code is None
    assert result.proposal_digest == make_proposal().proposal_digest


@pytest.mark.parametrize(
    ("proposal", "evaluated_at", "reason"),
    [
        (
            make_proposal(
                created_at=datetime(2026, 9, 3, 12, 6, tzinfo=UTC),
                expires_at=datetime(2026, 9, 3, 12, 16, tzinfo=UTC),
            ),
            EVALUATED_AT,
            "PROPOSAL_NOT_YET_VALID",
        ),
        (make_proposal(), datetime(2026, 9, 3, 12, 15, tzinfo=UTC), "PROPOSAL_EXPIRED"),
    ],
)
def test_proposal_half_open_validity(proposal: Any, evaluated_at: datetime, reason: str) -> None:
    assert _evaluate(proposal=proposal, evaluated_at=evaluated_at).reason_code == reason


@pytest.mark.parametrize(
    ("policy", "reason"),
    [
        (
            policy_snapshot(
                valid_from=datetime(2026, 9, 3, 12, 6, tzinfo=UTC),
                valid_until=datetime(2026, 9, 3, 13, 0, tzinfo=UTC),
            ),
            "POLICY_NOT_YET_VALID",
        ),
        (
            policy_snapshot(valid_until=EVALUATED_AT),
            "POLICY_EXPIRED",
        ),
    ],
)
def test_policy_half_open_validity(policy: Any, reason: str) -> None:
    assert _evaluate(policy=policy).reason_code == reason


@pytest.mark.parametrize(
    ("identity", "reason"),
    [
        (
            identity_snapshot(
                make_proposal(),
                verified_at=datetime(2026, 9, 3, 12, 6, tzinfo=UTC),
                expires_at=datetime(2026, 9, 3, 12, 30, tzinfo=UTC),
            ),
            "TARGET_IDENTITY_NOT_YET_VALID",
        ),
        (
            identity_snapshot(make_proposal(), expires_at=EVALUATED_AT),
            "TARGET_IDENTITY_EXPIRED",
        ),
    ],
)
def test_identity_half_open_validity(identity: Any, reason: str) -> None:
    assert _evaluate(identity=identity).reason_code == reason


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"policy": policy_snapshot(tenant_id="tenant-b")}, "TENANT_MISMATCH"),
        (
            {"identity": identity_snapshot(make_proposal(), tenant_id="tenant-b")},
            "TENANT_MISMATCH",
        ),
        (
            {"policy": policy_snapshot(engagement_id=uuid.uuid4())},
            "ENGAGEMENT_MISMATCH",
        ),
        (
            {"identity": identity_snapshot(make_proposal(), proposal_digest="9" * 64)},
            "PROPOSAL_BINDING_MISMATCH",
        ),
        (
            {"destination_manifest": manifest(make_proposal(), proposal_digest="9" * 64)},
            "PROPOSAL_BINDING_MISMATCH",
        ),
        (
            {"policy": policy_snapshot(graph_version=graph_version(ledger_event_count=8))},
            "GRAPH_BINDING_MISMATCH",
        ),
        (
            {
                "identity": identity_snapshot(
                    make_proposal(), graph_version=graph_version(ledger_head_hash="9" * 64)
                )
            },
            "GRAPH_BINDING_MISMATCH",
        ),
        (
            {"policy": policy_snapshot(allowed_capability_ids=("scout.other.v1",))},
            "CAPABILITY_NOT_ALLOWED",
        ),
        (
            {"capability": capability_snapshot(capability_id="scout.other.v1")},
            "CAPABILITY_BINDING_MISMATCH",
        ),
        (
            {"destination_manifest": manifest(make_proposal(), capability_id="scout.other.v1")},
            "CAPABILITY_BINDING_MISMATCH",
        ),
        (
            {"capability": capability_snapshot(owner_agent="Strike")},
            "CAPABILITY_OWNER_MISMATCH",
        ),
        (
            {"capability": capability_snapshot(input_schema="OtherInput.v1")},
            "CAPABILITY_SCHEMA_MISMATCH",
        ),
        (
            {"destination_manifest": manifest(make_proposal(), input_schema="OtherInput.v1")},
            "CAPABILITY_SCHEMA_MISMATCH",
        ),
        (
            {
                "destination_manifest": manifest(
                    make_proposal(), extractor_identity="blackbread.extractors.other.v1"
                )
            },
            "EXTRACTOR_BINDING_MISMATCH",
        ),
        (
            {"destination_manifest": manifest(make_proposal(), extractor_digest="9" * 64)},
            "EXTRACTOR_BINDING_MISMATCH",
        ),
        (
            {"destination_manifest": manifest(make_proposal(), parameter_digest="9" * 64)},
            "PARAMETER_BINDING_MISMATCH",
        ),
        (
            {
                "identity": identity_snapshot(
                    make_proposal(),
                    target=TargetReference(
                        target_kind="root_domain", canonical_value="other.example"
                    ),
                )
            },
            "TARGET_IDENTITY_MISMATCH",
        ),
    ],
)
def test_binding_mismatches_deny(overrides: dict[str, Any], reason: str) -> None:
    assert _evaluate(**overrides).reason_code == reason


@pytest.mark.parametrize(
    "lifecycle",
    [
        "PLANNED",
        "ON_HOLD",
        "RESEARCH_DRAFT",
        "STATIC_REVIEWED",
        "FIXTURE_VERIFIED",
        "NEGATIVE_CONTROL_VERIFIED",
        "LAB_PROVEN",
        "SAFETY_REVIEWED",
        "SUSPENDED",
        "RETIRED",
    ],
)
def test_every_ineligible_lifecycle_denies(lifecycle: str) -> None:
    result = _evaluate(capability=capability_snapshot(lifecycle=lifecycle))
    assert result.reason_code == "CAPABILITY_LIFECYCLE_DENIED"


@pytest.mark.parametrize(
    "lifecycle",
    [
        "CLIENT_ELIGIBLE",
        "EXACT_TARGET_APPROVED",
        "FIELD_OBSERVED",
        "FIELD_PROVEN",
        "REPEATABLE",
    ],
)
def test_every_eligible_lifecycle_reaches_later_gates(lifecycle: str) -> None:
    assert _evaluate(capability=capability_snapshot(lifecycle=lifecycle)).reason_code is None


@pytest.mark.parametrize(
    "capability",
    [
        capability_snapshot(required_identity_tier="T1"),
        capability_snapshot(approval_class="LEASE"),
        capability_snapshot(network_path="NONE"),
        capability_snapshot(risk_class="OFFLINE"),
    ],
)
def test_contradictory_or_unsupported_profile_denies(capability: Any) -> None:
    assert _evaluate(capability=capability).reason_code == "CAPABILITY_PROFILE_MISMATCH"


def test_identity_tier_must_satisfy_proposal_and_capability_independently() -> None:
    proposal = make_proposal(target_identity_tier="T1")
    assert _evaluate(proposal=proposal).reason_code == "IDENTITY_TIER_INSUFFICIENT"
    capability = capability_snapshot(
        risk_class="ACTIVE_READ_ONLY",
        required_identity_tier="T1",
        approval_class="LEASE",
        network_path="TARGET_EGRESS",
    )
    assert _evaluate(capability=capability).reason_code == "IDENTITY_TIER_INSUFFICIENT"


def test_structural_budget_ceilings_are_half_open_only_on_excess() -> None:
    capability = capability_snapshot(max_target_requests=0, max_deadline_seconds=30)
    assert _evaluate(capability=capability).reason_code is None
    requests = make_proposal(requested_budget=BudgetRequest(target_requests=1, deadline_seconds=30))
    assert _evaluate(proposal=requests).reason_code == "TARGET_EGRESS_DESTINATION_REQUIRED"
    deadline = make_proposal(requested_budget=BudgetRequest(target_requests=0, deadline_seconds=31))
    assert _evaluate(proposal=deadline).reason_code == "STRUCTURAL_BUDGET_EXCEEDED"


@pytest.mark.parametrize(
    "evaluated_at",
    [datetime(2026, 9, 3, 12, 5), datetime(2026, 9, 3, 13, 5, tzinfo=timezone(timedelta(hours=1)))],
)
def test_invalid_evaluation_time_raises_typed_error(evaluated_at: datetime) -> None:
    with pytest.raises(AdmissionEvaluationError, match="evaluation arguments failed validation"):
        _evaluate(evaluated_at=evaluated_at)


def test_invalid_argument_type_raises_typed_error_without_value_leakage() -> None:
    with pytest.raises(AdmissionEvaluationError) as captured:
        _evaluate(policy="secret-target.example")
    assert "secret-target.example" not in str(captured.value)


def test_documented_precedence_selects_first_matching_reason() -> None:
    proposal = make_proposal()
    policy = policy_snapshot(tenant_id="tenant-b")
    identity = identity_snapshot(
        proposal,
        target=TargetReference(target_kind="root_domain", canonical_value="other.example"),
    )
    result = _evaluate(proposal=proposal, policy=policy, identity=identity)
    assert result.reason_code == "TENANT_MISMATCH"
