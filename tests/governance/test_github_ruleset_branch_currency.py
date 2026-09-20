"""Focused proofs for strict branch-currency evidence (GOV-LIVE-GATES-001D2)."""

from typing import Any

import pytest

from blackbread.governance.github_merge_normalization import (
    EvidenceNormalizationError,
    normalize_ruleset,
)
from blackbread.governance.merge_readiness import (
    CheckRunEvidence,
    CodeScanningEvidence,
    DeliveryContract,
    MergeEvidence,
    PullRequestIdentity,
    RequiredStatusCheck,
    RulesetEvidence,
    evaluate_merge_readiness,
)

HEAD_SHA, BASE_SHA, MERGE_SHA = "1" * 40, "b" * 40, "2" * 40


def _status_rule(**params: Any) -> dict[str, Any]:
    base = {
        "required_status_checks": [{"context": "ci-ok", "integration_id": 15368}],
        "strict_required_status_checks_policy": True,
    }
    return {"type": "required_status_checks", "parameters": {**base, **params}}


def _ruleset_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": 21644438,
        "enforcement": "active",
        "bypass_actors": [],
        "target": "branch",
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [_status_rule()],
    }
    return {**body, **overrides}


def _contract() -> DeliveryContract:
    return DeliveryContract(
        schema_version=3,
        ruleset_id=21644438,
        required_approving_reviews=0,
        require_review_thread_resolution=True,
        allow_changes_requested=False,
        require_branch_up_to_date=True,
        required_status_checks=(RequiredStatusCheck("ci-ok", 15368),),
        required_code_scanning=(),
    )


def _evidence(ruleset: RulesetEvidence) -> MergeEvidence:
    identity = PullRequestIdentity(91, HEAD_SHA, BASE_SHA, "main", MERGE_SHA)
    return MergeEvidence(
        pull_request_before=identity,
        pull_request_after=identity,
        is_draft=False,
        merge_state="CLEAN",
        check_runs=(CheckRunEvidence("ci-ok", 15368, HEAD_SHA, "success"),),
        ruleset=ruleset,
        code_scanning=CodeScanningEvidence(analyses=(), alerts=(), queried_ref="refs/pull/91/head"),
        review_states=(),
        review_threads=(True,),
        incomplete_sections=frozenset(),
    )


def _codes(body: dict[str, Any]) -> list[str]:
    ruleset = normalize_ruleset(body)
    decision = evaluate_merge_readiness(_contract(), _evidence(ruleset), HEAD_SHA)
    return [blocker.code for blocker in decision.blockers]


def test_strict_currency_true_normalizes_and_ready() -> None:
    ruleset = normalize_ruleset(_ruleset_body())
    assert ruleset.strict_branch_currency is True
    decision = evaluate_merge_readiness(_contract(), _evidence(ruleset), HEAD_SHA)
    assert decision.ready


def test_strict_currency_false_is_observed_and_blocks_with_drift() -> None:
    body = _ruleset_body(rules=[_status_rule(strict_required_status_checks_policy=False)])
    assert normalize_ruleset(body).strict_branch_currency is False
    assert "RULESET_STATUS_CHECK_DRIFT" in _codes(body)


def test_strict_currency_missing_is_unobserved_and_blocks() -> None:
    rule = _status_rule()
    del rule["parameters"]["strict_required_status_checks_policy"]
    body = _ruleset_body(rules=[rule])
    assert normalize_ruleset(body).strict_branch_currency is None
    assert "RULESET_STATUS_CHECK_DRIFT" in _codes(body)


def test_absent_status_check_rule_leaves_currency_unobserved_and_blocks() -> None:
    body = _ruleset_body(rules=[{"type": "deletion"}])
    assert normalize_ruleset(body).strict_branch_currency is None
    assert "RULESET_STATUS_CHECK_DRIFT" in _codes(body)


@pytest.mark.parametrize("bad", ["true", 1, 0, [], {}])
def test_strict_currency_malformed_fails_closed(bad: Any) -> None:
    body = _ruleset_body(rules=[_status_rule(strict_required_status_checks_policy=bad)])
    with pytest.raises(EvidenceNormalizationError):
        normalize_ruleset(body)
