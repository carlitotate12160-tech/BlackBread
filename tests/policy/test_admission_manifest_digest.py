"""The evaluated destination manifest is bound into result_digest via its manifest digest."""

from __future__ import annotations

from datetime import UTC, datetime

from blackbread.conductor.contracts import BudgetRequest, TargetReference
from blackbread.policy.admission import evaluate_admission
from blackbread.policy.admission_contracts import (
    AdmissionResult,
    ScopedDestination,
    destination_manifest_digest,
)
from tests.conductor._builders import make_proposal
from tests.policy._builders import capability_snapshot, identity_snapshot, manifest, policy_snapshot

ADMIT_AT = datetime(2026, 9, 3, 12, 5, tzinfo=UTC)
DENY_AT = datetime(2026, 9, 3, 12, 20, tzinfo=UTC)  # past the proposal's 12:15 expiry


def _dest(kind: str, target_kind: str, value: str) -> ScopedDestination:
    return ScopedDestination(
        destination_kind=kind,  # type: ignore[arg-type]
        scope=TargetReference(target_kind=target_kind, canonical_value=value),  # type: ignore[arg-type]
    )


def _denied_result(destinations: tuple[ScopedDestination, ...]) -> AdmissionResult:
    # Denied early (PROPOSAL_EXPIRED) so the reason is stable while destinations vary freely.
    proposal = make_proposal(
        target=TargetReference(target_kind="exact_host", canonical_value="app.example.com")
    )
    return evaluate_admission(
        proposal,
        policy=policy_snapshot(graph_version=proposal.graph_version),
        identity=identity_snapshot(proposal),
        capability=capability_snapshot(),
        manifest=manifest(proposal, destinations=destinations),
        evaluated_at=DENY_AT,
    )


def _admitted_result(
    destinations: tuple[ScopedDestination, ...],
) -> tuple[AdmissionResult, object]:
    target = TargetReference(target_kind="exact_host", canonical_value="app.example.com")
    proposal = make_proposal(
        target=target,
        requested_budget=BudgetRequest(target_requests=1, deadline_seconds=30),
        target_identity_tier="T1",
    )
    built = manifest(proposal, destinations=destinations)
    result = evaluate_admission(
        proposal,
        policy=policy_snapshot(
            scope_allow=(
                TargetReference(target_kind="root_domain", canonical_value="example.com"),
            ),
            graph_version=proposal.graph_version,
        ),
        identity=identity_snapshot(proposal, achieved_tier="T1"),
        capability=capability_snapshot(
            risk_class="ACTIVE_READ_ONLY",
            required_identity_tier="T1",
            approval_class="LEASE",
            network_path="TARGET_EGRESS",
            max_target_requests=1,
            max_deadline_seconds=30,
        ),
        manifest=built,
        evaluated_at=ADMIT_AT,
    )
    return result, built


def test_changing_destination_canonical_value_changes_both_digests() -> None:
    left = _denied_result((_dest("callback", "exact_host", "c1.example.com"),))
    right = _denied_result((_dest("callback", "exact_host", "c2.example.com"),))
    assert left.reason_code == right.reason_code == "PROPOSAL_EXPIRED"
    assert left.destination_manifest_digest != right.destination_manifest_digest
    assert left.result_digest != right.result_digest


def test_changing_destination_kind_changes_both_digests() -> None:
    left = _denied_result((_dest("callback", "exact_host", "c.example.com"),))
    right = _denied_result((_dest("redirect", "exact_host", "c.example.com"),))
    assert left.reason_code == right.reason_code == "PROPOSAL_EXPIRED"
    assert left.destination_manifest_digest != right.destination_manifest_digest
    assert left.result_digest != right.result_digest


def test_changing_destination_target_kind_changes_both_digests() -> None:
    # Same canonical_value under two target kinds isolates target_kind as the only change.
    left = _denied_result((_dest("callback", "exact_host", "example.com"),))
    right = _denied_result((_dest("callback", "root_domain", "example.com"),))
    assert left.reason_code == right.reason_code == "PROPOSAL_EXPIRED"
    assert left.destination_manifest_digest != right.destination_manifest_digest
    assert left.result_digest != right.result_digest


def test_reordering_an_identical_destination_set_does_not_change_the_manifest_digest() -> None:
    proposal = make_proposal()
    a = _dest("callback", "exact_host", "a.example.com")
    b = _dest("redirect", "exact_host", "b.example.com")
    forward = destination_manifest_digest(manifest(proposal, destinations=(a, b)))
    reversed_ = destination_manifest_digest(manifest(proposal, destinations=(b, a)))
    assert forward == reversed_


def test_admitted_result_binds_the_evaluated_manifest() -> None:
    primary = _dest("primary", "exact_host", "app.example.com")
    result, built = _admitted_result((primary,))
    assert result.reason_code is None
    assert result.destination_manifest_digest == destination_manifest_digest(built)


def test_denied_result_binds_the_evaluated_manifest() -> None:
    proposal = make_proposal(
        target=TargetReference(target_kind="exact_host", canonical_value="app.example.com")
    )
    built = manifest(proposal, destinations=(_dest("callback", "exact_host", "c.example.com"),))
    result = evaluate_admission(
        proposal,
        policy=policy_snapshot(graph_version=proposal.graph_version),
        identity=identity_snapshot(proposal),
        capability=capability_snapshot(),
        manifest=built,
        evaluated_at=DENY_AT,
    )
    assert result.reason_code == "PROPOSAL_EXPIRED"
    assert result.destination_manifest_digest == destination_manifest_digest(built)
