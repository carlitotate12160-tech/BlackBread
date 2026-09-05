"""Target and destination scope, exclusion, network-path, and ceiling proofs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from blackbread.conductor.contracts import BudgetRequest, TargetReference
from blackbread.policy.admission import evaluate_admission
from blackbread.policy.admission_contracts import ScopedDestination
from tests.conductor._builders import make_proposal
from tests.policy._builders import capability_snapshot, identity_snapshot, manifest, policy_snapshot

EVALUATED_AT = datetime(2026, 9, 3, 12, 5, tzinfo=UTC)


def _target(kind: str, value: str) -> TargetReference:
    return TargetReference(target_kind=kind, canonical_value=value)  # type: ignore[arg-type]


def _destination(kind: str, target: TargetReference) -> ScopedDestination:
    return ScopedDestination(destination_kind=kind, scope=target)  # type: ignore[arg-type]


def _evaluate_egress(
    target: TargetReference,
    *,
    allow: tuple[TargetReference, ...],
    **options: Any,
):
    exclusions = options.get("exclusions", ())
    destinations = options.get("destinations")
    target_requests = options.get("target_requests", 1)
    deadline_seconds = options.get("deadline_seconds", 30)
    max_target_requests = options.get("max_target_requests", 1)
    max_deadline_seconds = options.get("max_deadline_seconds", 30)
    proposal = make_proposal(
        target=target,
        requested_budget=BudgetRequest(
            target_requests=target_requests,
            deadline_seconds=deadline_seconds,
        ),
        target_identity_tier="T1",
    )
    primary = _destination("primary", target)
    built_manifest = manifest(
        proposal,
        destinations=(primary,) if destinations is None else destinations,
    )
    return evaluate_admission(
        proposal,
        policy=policy_snapshot(
            scope_allow=allow,
            scope_exclusions=exclusions,
            graph_version=proposal.graph_version,
        ),
        identity=identity_snapshot(proposal, achieved_tier="T1"),
        capability=capability_snapshot(
            risk_class="ACTIVE_READ_ONLY",
            required_identity_tier="T1",
            approval_class="LEASE",
            network_path="TARGET_EGRESS",
            max_target_requests=max_target_requests,
            max_deadline_seconds=max_deadline_seconds,
        ),
        manifest=built_manifest,
        evaluated_at=EVALUATED_AT,
    )


@pytest.mark.parametrize(
    ("target", "allow"),
    [
        (_target("exact_host", "app.example.com"), _target("exact_host", "app.example.com")),
        (_target("exact_host", "app.example.com"), _target("root_domain", "example.com")),
        (_target("exact_host", "example.com"), _target("root_domain", "example.com")),
        (_target("root_domain", "example.com"), _target("root_domain", "example.com")),
        (_target("exact_address", "192.0.2.10"), _target("exact_address", "192.0.2.10")),
        (_target("cloud_tenant", "tenant/example"), _target("cloud_tenant", "tenant/example")),
    ],
)
def test_exact_and_root_descendant_scope_allows(
    target: TargetReference, allow: TargetReference
) -> None:
    assert _evaluate_egress(target, allow=(allow,)).reason_code is None


@pytest.mark.parametrize(
    ("target", "allow"),
    [
        (_target("exact_host", "badexample.com"), _target("root_domain", "example.com")),
        (_target("root_domain", "app.example.com"), _target("root_domain", "example.com")),
        (_target("exact_host", "b.example.com"), _target("exact_host", "a.example.com")),
        (_target("exact_address", "192.0.2.11"), _target("exact_address", "192.0.2.10")),
        (_target("cloud_tenant", "tenant/b"), _target("cloud_tenant", "tenant/a")),
    ],
)
def test_scope_containment_is_deliberately_narrow(
    target: TargetReference, allow: TargetReference
) -> None:
    assert _evaluate_egress(target, allow=(allow,)).reason_code == "TARGET_OUT_OF_SCOPE"


def test_target_exclusion_precedes_allow() -> None:
    target = _target("exact_host", "blocked.example.com")
    result = _evaluate_egress(
        target,
        allow=(_target("root_domain", "example.com"),),
        exclusions=(_target("exact_host", "blocked.example.com"),),
    )
    assert result.reason_code == "TARGET_EXCLUDED"


def test_broad_target_is_excluded_when_it_contains_a_narrower_excluded_host() -> None:
    # A root-domain proposal encompasses an explicitly excluded host, so it must
    # be denied: exclusions are overlap boundaries, not equal-or-narrower matches.
    result = _evaluate_egress(
        _target("root_domain", "example.com"),
        allow=(_target("root_domain", "example.com"),),
        exclusions=(_target("exact_host", "blocked.example.com"),),
    )
    assert result.reason_code == "TARGET_EXCLUDED"


def test_broad_destination_is_excluded_when_it_contains_a_narrower_excluded_host() -> None:
    target = _target("exact_host", "app.example.com")
    result = _evaluate_egress(
        target,
        allow=(_target("root_domain", "example.com"),),
        exclusions=(_target("exact_host", "blocked.example.com"),),
        destinations=(
            _destination("primary", target),
            _destination("callback", _target("root_domain", "example.com")),
        ),
    )
    assert result.reason_code == "DESTINATION_EXCLUDED"


def test_sibling_hosts_do_not_falsely_overlap_exclusions() -> None:
    # A sibling of the excluded host stays admissible, and a broad target whose
    # exclusion lies in an unrelated domain does not spuriously overlap.
    sibling = _evaluate_egress(
        _target("exact_host", "allowed.example.com"),
        allow=(_target("root_domain", "example.com"),),
        exclusions=(_target("exact_host", "blocked.example.com"),),
    )
    assert sibling.reason_code is None
    unrelated = _evaluate_egress(
        _target("root_domain", "example.com"),
        allow=(_target("root_domain", "example.com"),),
        exclusions=(_target("exact_host", "blocked.other.com"),),
    )
    assert unrelated.reason_code is None


def test_exact_host_allow_does_not_authorize_a_broader_root_domain_proposal() -> None:
    # Allow-list containment stays directional: overlap semantics apply to
    # exclusions only, never to the allow-list.
    result = _evaluate_egress(
        _target("root_domain", "example.com"),
        allow=(_target("exact_host", "app.example.com"),),
    )
    assert result.reason_code == "TARGET_OUT_OF_SCOPE"


def test_one_bad_destination_denies_the_complete_manifest() -> None:
    target = _target("exact_host", "app.example.com")
    result = _evaluate_egress(
        target,
        allow=(_target("root_domain", "example.com"),),
        destinations=(
            _destination("primary", target),
            _destination("redirect", _target("exact_host", "outside.example.net")),
        ),
    )
    assert result.reason_code == "DESTINATION_OUT_OF_SCOPE"


def test_one_excluded_destination_wins_over_destination_allow() -> None:
    target = _target("exact_host", "app.example.com")
    blocked = _target("exact_host", "blocked.example.com")
    result = _evaluate_egress(
        target,
        allow=(_target("root_domain", "example.com"),),
        exclusions=(blocked,),
        destinations=(_destination("primary", target), _destination("callback", blocked)),
    )
    assert result.reason_code == "DESTINATION_EXCLUDED"


def test_target_egress_requires_primary_exactly_equal_to_proposal_target() -> None:
    target = _target("exact_host", "app.example.com")
    allow = (_target("root_domain", "example.com"),)
    assert _evaluate_egress(target, allow=allow, destinations=()).reason_code == (
        "TARGET_EGRESS_DESTINATION_REQUIRED"
    )
    substituted = (_destination("primary", _target("exact_host", "other.example.com")),)
    assert _evaluate_egress(target, allow=allow, destinations=substituted).reason_code == (
        "TARGET_EGRESS_DESTINATION_REQUIRED"
    )


@pytest.mark.parametrize(
    ("network_path", "target_requests", "destinations"),
    [
        ("CONTROL_PLANE_PASSIVE", 1, ()),
        (
            "CONTROL_PLANE_PASSIVE",
            0,
            (_destination("primary", _target("root_domain", "example.com")),),
        ),
        ("NONE", 1, ()),
        ("NONE", 0, (_destination("file_input", _target("root_domain", "example.com")),)),
    ],
)
def test_non_target_egress_requires_zero_requests_and_empty_manifest(
    network_path: str,
    target_requests: int,
    destinations: tuple[ScopedDestination, ...],
) -> None:
    proposal = make_proposal(
        requested_budget=BudgetRequest(target_requests=target_requests, deadline_seconds=30)
    )
    profile: dict[str, Any] = {}
    if network_path == "NONE":
        profile = {
            "risk_class": "SENSITIVE_OFFLINE",
            "approval_class": "OPERATOR_DATA_APPROVAL",
            "network_path": "NONE",
        }
    result = evaluate_admission(
        proposal,
        policy=policy_snapshot(),
        identity=identity_snapshot(proposal),
        capability=capability_snapshot(**profile),
        manifest=manifest(proposal, destinations=destinations),
        evaluated_at=EVALUATED_AT,
    )
    assert result.reason_code == "TARGET_EGRESS_DESTINATION_REQUIRED"


def test_request_and_deadline_ceiling_equality_accepts_and_excess_denies() -> None:
    target = _target("exact_host", "app.example.com")
    allow = (_target("root_domain", "example.com"),)
    assert _evaluate_egress(target, allow=allow).reason_code is None
    requests = _evaluate_egress(
        target,
        allow=allow,
        target_requests=2,
        max_target_requests=1,
    )
    assert requests.reason_code == "STRUCTURAL_BUDGET_EXCEEDED"
    deadline = _evaluate_egress(
        target,
        allow=allow,
        deadline_seconds=31,
        max_deadline_seconds=30,
    )
    assert deadline.reason_code == "STRUCTURAL_BUDGET_EXCEEDED"
