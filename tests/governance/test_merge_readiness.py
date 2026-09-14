"""Proofs for the pure deterministic merge-readiness evaluator."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from blackbread.governance.merge_readiness import (
    CheckRunEvidence,
    CodeScanningAlert,
    CodeScanningAnalysis,
    CodeScanningEvidence,
    CodeScanningRequirement,
    DeliveryContract,
    MergeEvidence,
    PullRequestIdentity,
    RequiredStatusCheck,
    RulesetEvidence,
    evaluate_merge_readiness,
)

ROOT = Path(__file__).parents[2]
BASE_SHA = "b" * 40
HEAD_SHA = "1" * 40
MERGE_SHA = "2" * 40
OTHER_SHA = "3" * 40


def _contract() -> DeliveryContract:
    return DeliveryContract(
        schema_version=3,
        ruleset_id=21644438,
        required_approving_reviews=0,
        require_review_thread_resolution=True,
        allow_changes_requested=False,
        required_status_checks=(
            RequiredStatusCheck("ci-ok", 15368),
            RequiredStatusCheck("GitGuardian Security Checks", 46505),
        ),
        required_code_scanning=(CodeScanningRequirement("CodeQL", "high_or_higher", "errors"),),
    )


def _identity(**overrides: object) -> PullRequestIdentity:
    identity = PullRequestIdentity(
        number=91,
        head_sha=HEAD_SHA,
        base_sha=BASE_SHA,
        base_ref="main",
        potential_merge_sha=MERGE_SHA,
    )
    return replace(identity, **overrides)


def _passing_runs() -> tuple[CheckRunEvidence, ...]:
    return tuple(
        CheckRunEvidence(
            context=check.context,
            integration_id=check.integration_id,
            head_sha=HEAD_SHA,
            conclusion="success",
        )
        for check in _contract().required_status_checks
    )


def _ruleset(**overrides: object) -> RulesetEvidence:
    contract = _contract()
    ruleset = RulesetEvidence(
        ruleset_id=contract.ruleset_id,
        enforcement="active",
        bypass_actors=(),
        status_checks=contract.required_status_checks,
        code_scanning=contract.required_code_scanning,
        target="branch",
        included_refs=("refs/heads/main",),
        excluded_refs=(),
        unmodeled_rule_types=(
            "deletion",
            "non_fast_forward",
            "required_linear_history",
            "pull_request",
        ),
    )
    return replace(ruleset, **overrides)


def _scanning(**overrides: object) -> CodeScanningEvidence:
    evidence = CodeScanningEvidence(
        analyses=(CodeScanningAnalysis(tool="CodeQL", commit_sha=MERGE_SHA, error=""),),
        alerts=(),
        queried_ref="refs/pull/91/merge",
    )
    return replace(evidence, **overrides)


def _evidence(**overrides: object) -> MergeEvidence:
    identity = _identity()
    evidence = MergeEvidence(
        pull_request_before=identity,
        pull_request_after=identity,
        is_draft=False,
        merge_state="CLEAN",
        check_runs=_passing_runs(),
        ruleset=_ruleset(),
        code_scanning=_scanning(),
        review_states=(),
        review_threads=(True,),
        incomplete_sections=frozenset(),
    )
    return replace(evidence, **overrides)


def _codes(evidence: MergeEvidence, contract: DeliveryContract | None = None) -> list[str]:
    decision = evaluate_merge_readiness(contract or _contract(), evidence, HEAD_SHA)
    assert not decision.ready
    return [blocker.code for blocker in decision.blockers]


def test_contract_model_matches_live_delivery_contract() -> None:
    document = json.loads((ROOT / ".github/agent-delivery.json").read_text(encoding="utf-8"))
    delivery = document["agent_delivery"]
    contract = _contract()
    assert document["schema_version"] == 3
    assert contract.ruleset_id == delivery["ruleset_id"]
    assert contract.required_status_checks == tuple(
        RequiredStatusCheck(check["context"], check["integration_id"])
        for check in delivery["required_status_checks"]
    )
    assert contract.required_code_scanning == tuple(
        CodeScanningRequirement(
            requirement["tool"],
            requirement["security_alerts_threshold"],
            requirement["alerts_threshold"],
        )
        for requirement in delivery["required_code_scanning"]
    )
    assert contract.required_approving_reviews == delivery["required_approving_reviews"]
    assert contract.require_review_thread_resolution == delivery["require_review_thread_resolution"]
    assert contract.allow_changes_requested == delivery["allow_changes_requested"]


def test_complete_evidence_is_ready() -> None:
    decision = evaluate_merge_readiness(_contract(), _evidence(), HEAD_SHA)
    assert decision.ready
    assert decision.blockers == ()


def test_wrong_integration_with_correct_context_blocks() -> None:
    runs = tuple(replace(run, integration_id=99999) for run in _passing_runs())
    assert "REQUIRED_CHECK_INTEGRATION_MISMATCH" in _codes(_evidence(check_runs=runs))


def test_pinned_failure_blocks_despite_same_name_foreign_success() -> None:
    runs = (
        CheckRunEvidence("ci-ok", 15368, HEAD_SHA, "failure"),
        CheckRunEvidence("ci-ok", 99999, HEAD_SHA, "success"),
        CheckRunEvidence("GitGuardian Security Checks", 46505, HEAD_SHA, "success"),
    )
    assert "REQUIRED_CHECK_FAILING" in _codes(_evidence(check_runs=runs))


def test_required_check_missing_blocks() -> None:
    runs = (CheckRunEvidence("GitGuardian Security Checks", 46505, HEAD_SHA, "success"),)
    assert "REQUIRED_CHECK_MISSING" in _codes(_evidence(check_runs=runs))


def test_required_check_at_stale_head_blocks() -> None:
    runs = tuple(replace(run, head_sha=OTHER_SHA) for run in _passing_runs())
    assert "REQUIRED_CHECK_STALE" in _codes(_evidence(check_runs=runs))


def test_codeql_check_run_does_not_satisfy_code_scanning() -> None:
    runs = (*_passing_runs(), CheckRunEvidence("CodeQL", 15368, HEAD_SHA, "success"))
    codes = _codes(_evidence(check_runs=runs, code_scanning=_scanning(analyses=())))
    assert "CODE_SCANNING_ANALYSIS_MISSING" in codes
    assert not any(code.startswith("REQUIRED_CHECK") for code in codes)


def test_missing_code_scanning_analysis_blocks() -> None:
    codes = _codes(_evidence(code_scanning=_scanning(analyses=())))
    assert "CODE_SCANNING_ANALYSIS_MISSING" in codes


def test_analysis_at_pr_head_instead_of_merge_candidate_blocks() -> None:
    stale = (CodeScanningAnalysis(tool="CodeQL", commit_sha=HEAD_SHA, error=""),)
    codes = _codes(_evidence(code_scanning=_scanning(analyses=stale)))
    assert "CODE_SCANNING_ANALYSIS_STALE" in codes


def test_analysis_error_blocks_with_zero_alerts() -> None:
    failed = (CodeScanningAnalysis(tool="CodeQL", commit_sha=MERGE_SHA, error="sarif failed"),)
    codes = _codes(_evidence(code_scanning=_scanning(analyses=failed)))
    assert "CODE_SCANNING_ANALYSIS_ERROR" in codes


def test_analysis_with_unknown_error_state_blocks() -> None:
    unknown = (CodeScanningAnalysis(tool="CodeQL", commit_sha=MERGE_SHA, error=None),)
    assert "INCOMPLETE_EVIDENCE" in _codes(_evidence(code_scanning=_scanning(analyses=unknown)))


def test_missing_code_scanning_queried_ref_blocks() -> None:
    codes = _codes(_evidence(code_scanning=_scanning(queried_ref=None)))
    assert "MISSING_EVIDENCE" in codes


@pytest.mark.parametrize("ref", ["refs/pull/91/head", "refs/pull/92/merge"])
def test_wrong_code_scanning_queried_ref_blocks(ref: str) -> None:
    codes = _codes(_evidence(code_scanning=_scanning(queried_ref=ref)))
    assert "CODE_SCANNING_REF_MISMATCH" in codes


@pytest.mark.parametrize("severity", ["critical", "high"])
def test_security_alert_at_or_above_threshold_blocks(severity: str) -> None:
    alerts = (CodeScanningAlert("CodeQL", "open", severity, "error"),)
    assert "CODE_SCANNING_ALERT" in _codes(_evidence(code_scanning=_scanning(alerts=alerts)))


@pytest.mark.parametrize("severity", ["medium", "low"])
def test_security_alert_below_threshold_does_not_block(severity: str) -> None:
    alerts = (CodeScanningAlert("CodeQL", "open", severity, "warning"),)
    decision = evaluate_merge_readiness(
        _contract(), _evidence(code_scanning=_scanning(alerts=alerts)), HEAD_SHA
    )
    assert decision.ready


def test_tool_error_alert_blocks() -> None:
    alerts = (CodeScanningAlert("CodeQL", "open", None, "error"),)
    assert "CODE_SCANNING_ALERT" in _codes(_evidence(code_scanning=_scanning(alerts=alerts)))


@pytest.mark.parametrize("severity", ["warning", "note"])
def test_tool_alert_below_error_threshold_does_not_block(severity: str) -> None:
    alerts = (CodeScanningAlert("CodeQL", "open", None, severity),)
    decision = evaluate_merge_readiness(
        _contract(), _evidence(code_scanning=_scanning(alerts=alerts)), HEAD_SHA
    )
    assert decision.ready


def test_dismissed_alert_does_not_block() -> None:
    alerts = (CodeScanningAlert("CodeQL", "dismissed", "critical", "error"),)
    decision = evaluate_merge_readiness(
        _contract(), _evidence(code_scanning=_scanning(alerts=alerts)), HEAD_SHA
    )
    assert decision.ready


@pytest.mark.parametrize(
    "alert",
    [
        CodeScanningAlert("CodeQL", "open", "severe", "error"),
        CodeScanningAlert("CodeQL", "open", None, "catastrophic"),
        CodeScanningAlert("CodeQL", "open", None, None),
    ],
    ids=["unknown_security_severity", "unknown_rule_severity", "absent_severity"],
)
def test_unknown_alert_severity_fails_closed(alert: CodeScanningAlert) -> None:
    codes = _codes(_evidence(code_scanning=_scanning(alerts=(alert,))))
    assert "UNKNOWN_ALERT_SEVERITY" in codes


@pytest.mark.parametrize(
    ("security_threshold", "alerts_threshold", "expected_code"),
    [
        ("sometimes", "errors", "UNKNOWN_SECURITY_THRESHOLD"),
        ("high_or_higher", "loud", "UNKNOWN_ALERTS_THRESHOLD"),
    ],
)
def test_unknown_thresholds_fail_closed(
    security_threshold: str, alerts_threshold: str, expected_code: str
) -> None:
    contract = replace(
        _contract(),
        required_code_scanning=(
            CodeScanningRequirement("CodeQL", security_threshold, alerts_threshold),
        ),
    )
    assert expected_code in _codes(_evidence(), contract)


def test_expected_head_mismatch_blocks() -> None:
    decision = evaluate_merge_readiness(_contract(), _evidence(), OTHER_SHA)
    assert not decision.ready
    assert "HEAD_SHA_MISMATCH" in [blocker.code for blocker in decision.blockers]


def test_before_after_identity_drift_blocks() -> None:
    codes = _codes(_evidence(pull_request_before=_identity(head_sha=OTHER_SHA)))
    assert "PR_IDENTITY_DRIFT" in codes


def test_missing_pr_identity_blocks() -> None:
    codes = _codes(_evidence(pull_request_after=None))
    assert "MISSING_PR_EVIDENCE" in codes


def test_missing_merge_candidate_blocks() -> None:
    codes = _codes(_evidence(pull_request_after=_identity(potential_merge_sha="")))
    assert "MISSING_MERGE_CANDIDATE" in codes


def test_ruleset_id_mismatch_blocks() -> None:
    assert "RULESET_ID_MISMATCH" in _codes(_evidence(ruleset=_ruleset(ruleset_id=1)))


@pytest.mark.parametrize("enforcement", ["evaluate", "disabled"])
def test_inactive_ruleset_blocks(enforcement: str) -> None:
    codes = _codes(_evidence(ruleset=_ruleset(enforcement=enforcement)))
    assert "RULESET_INACTIVE" in codes


def test_ruleset_bypass_actor_blocks() -> None:
    codes = _codes(_evidence(ruleset=_ruleset(bypass_actors=("Integration:5",))))
    assert "RULESET_BYPASS_ACTOR" in codes


@pytest.mark.parametrize(
    "status_checks",
    [
        (RequiredStatusCheck("ci-ok", 15368),),
        (
            RequiredStatusCheck("ci-ok", 15368),
            RequiredStatusCheck("GitGuardian Security Checks", 46505),
            RequiredStatusCheck("extra", 1),
        ),
        None,
    ],
    ids=["missing_check", "extra_check", "rule_absent"],
)
def test_status_check_rule_drift_blocks(
    status_checks: tuple[RequiredStatusCheck, ...] | None,
) -> None:
    codes = _codes(_evidence(ruleset=_ruleset(status_checks=status_checks)))
    assert "RULESET_STATUS_CHECK_DRIFT" in codes


def test_code_scanning_rule_drift_blocks() -> None:
    drifted = (CodeScanningRequirement("CodeQL", "all", "errors"),)
    codes = _codes(_evidence(ruleset=_ruleset(code_scanning=drifted)))
    assert "RULESET_CODE_SCANNING_DRIFT" in codes


def test_unmodeled_ruleset_rules_do_not_block() -> None:
    ruleset = _ruleset(unmodeled_rule_types=("deletion", "pull_request", "copilot_code_review"))
    decision = evaluate_merge_readiness(_contract(), _evidence(ruleset=ruleset), HEAD_SHA)
    assert decision.ready


def test_unsupported_schema_version_blocks() -> None:
    contract = replace(_contract(), schema_version=4)
    codes = _codes(_evidence(), contract)
    assert codes == ["UNSUPPORTED_SCHEMA_VERSION"]


def test_missing_bypass_evidence_blocks() -> None:
    codes = _codes(_evidence(ruleset=_ruleset(bypass_actors=None)))
    assert "RULESET_BYPASS_EVIDENCE_MISSING" in codes


@pytest.mark.parametrize("field", ["target", "included_refs", "excluded_refs"])
def test_missing_ruleset_scope_blocks(field: str) -> None:
    codes = _codes(_evidence(ruleset=_ruleset(**{field: None})))
    assert "RULESET_SCOPE_MISSING" in codes


def test_ruleset_scoped_away_from_pr_base_blocks() -> None:
    ruleset = _ruleset(included_refs=("refs/heads/release/1.0",))
    assert "RULESET_SCOPE_MISMATCH" in _codes(_evidence(ruleset=ruleset))


def test_ruleset_excluding_pr_base_blocks() -> None:
    ruleset = _ruleset(excluded_refs=("refs/heads/main",))
    assert "RULESET_SCOPE_MISMATCH" in _codes(_evidence(ruleset=ruleset))


def test_ruleset_with_non_branch_target_blocks() -> None:
    codes = _codes(_evidence(ruleset=_ruleset(target="tag")))
    assert "RULESET_SCOPE_MISMATCH" in codes


def test_changes_requested_review_blocks() -> None:
    codes = _codes(_evidence(review_states=("CHANGES_REQUESTED",)))
    assert "CHANGES_REQUESTED" in codes


def test_unresolved_review_thread_blocks() -> None:
    codes = _codes(_evidence(review_threads=(True, False)))
    assert "UNRESOLVED_REVIEW_THREAD" in codes


def test_draft_pull_request_blocks() -> None:
    assert "DRAFT_PULL_REQUEST" in _codes(_evidence(is_draft=True))


@pytest.mark.parametrize(
    "section",
    ["check_runs", "reviews", "review_threads", "code_scanning"],
)
def test_incomplete_pagination_blocks(section: str) -> None:
    codes = _codes(_evidence(incomplete_sections=frozenset({section})))
    assert "INCOMPLETE_EVIDENCE" in codes


@pytest.mark.parametrize(
    "field",
    [
        "pull_request_before",
        "check_runs",
        "ruleset",
        "code_scanning",
        "review_states",
        "review_threads",
        "is_draft",
        "merge_state",
    ],
)
def test_missing_evidence_fails_closed(field: str) -> None:
    codes = _codes(_evidence(**{field: None}))
    assert "MISSING_EVIDENCE" in codes or "MISSING_PR_EVIDENCE" in codes


@pytest.mark.parametrize(
    "state",
    ["BEHIND", "BLOCKED", "DIRTY", "DRAFT", "UNKNOWN", "HAS_HOOKS", "BROKEN", "rebased"],
)
def test_blocking_merge_states_block(state: str) -> None:
    assert "BLOCKING_MERGE_STATE" in _codes(_evidence(merge_state=state))


def test_unstable_with_advisory_check_failure_does_not_block() -> None:
    advisory = CheckRunEvidence("codecov/patch", 42, HEAD_SHA, "failure")
    evidence = _evidence(
        merge_state="UNSTABLE",
        check_runs=(*_passing_runs(), advisory),
    )
    decision = evaluate_merge_readiness(_contract(), evidence, HEAD_SHA)
    assert decision.ready


def test_blocker_ordering_is_deterministic() -> None:
    evidence = _evidence(
        is_draft=True,
        merge_state="BLOCKED",
        ruleset=None,
        review_states=("CHANGES_REQUESTED",),
        review_threads=(False,),
        check_runs=None,
    )
    first = evaluate_merge_readiness(_contract(), evidence, HEAD_SHA)
    second = evaluate_merge_readiness(_contract(), evidence, HEAD_SHA)
    assert first.blockers == second.blockers
    assert list(first.blockers) == sorted(first.blockers)
    assert len(first.blockers) >= 5
