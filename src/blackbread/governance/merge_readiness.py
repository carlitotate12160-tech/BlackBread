"""Deterministic merge-readiness evaluation for the schema-v3 delivery contract.

Fail-closed over supplied evidence; no GitHub I/O. Schema v3 models only status
checks and code scanning; other ruleset rule types are evidence, never drift.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequiredStatusCheck:
    context: str
    integration_id: int | None


@dataclass(frozen=True, slots=True)
class CodeScanningRequirement:
    tool: str
    security_alerts_threshold: str
    alerts_threshold: str


@dataclass(frozen=True, slots=True)
class DeliveryContract:
    schema_version: int
    ruleset_id: int
    required_approving_reviews: int
    require_review_thread_resolution: bool
    allow_changes_requested: bool
    required_status_checks: tuple[RequiredStatusCheck, ...]
    required_code_scanning: tuple[CodeScanningRequirement, ...]


@dataclass(frozen=True, slots=True)
class PullRequestIdentity:
    number: int
    head_sha: str
    base_sha: str
    base_ref: str
    potential_merge_sha: str


@dataclass(frozen=True, slots=True)
class CheckRunEvidence:
    context: str
    integration_id: int | None
    head_sha: str
    conclusion: str | None


@dataclass(frozen=True, slots=True)
class RulesetEvidence:
    ruleset_id: int
    enforcement: str
    bypass_actors: tuple[str, ...] | None = None
    status_checks: tuple[RequiredStatusCheck, ...] | None = None
    code_scanning: tuple[CodeScanningRequirement, ...] | None = None
    target: str | None = None
    included_refs: tuple[str, ...] | None = None
    excluded_refs: tuple[str, ...] | None = None
    unmodeled_rule_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CodeScanningAnalysis:
    tool: str
    commit_sha: str
    error: str | None


@dataclass(frozen=True, slots=True)
class CodeScanningAlert:
    tool: str
    state: str
    security_severity: str | None
    rule_severity: str | None


@dataclass(frozen=True, slots=True)
class CodeScanningEvidence:
    analyses: tuple[CodeScanningAnalysis, ...] | None
    alerts: tuple[CodeScanningAlert, ...] | None
    queried_ref: str | None = None


@dataclass(frozen=True, slots=True)
class MergeEvidence:
    pull_request_before: PullRequestIdentity | None
    pull_request_after: PullRequestIdentity | None
    is_draft: bool | None
    merge_state: str | None
    check_runs: tuple[CheckRunEvidence, ...] | None
    ruleset: RulesetEvidence | None
    code_scanning: CodeScanningEvidence | None
    review_states: tuple[str, ...] | None
    review_threads: tuple[bool, ...] | None
    incomplete_sections: frozenset[str]


@dataclass(frozen=True, slots=True, order=True)
class MergeBlocker:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class MergeReadinessDecision:
    ready: bool
    blockers: tuple[MergeBlocker, ...]


_SECURITY_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_RULE_SEVERITY_RANK = {"note": 0, "warning": 1, "error": 2}
_SECURITY_THRESHOLD_MIN = {
    "all": 0,
    "medium_or_higher": 1,
    "high_or_higher": 2,
    "critical": 3,
    "none": 99,
}
_ALERTS_THRESHOLD_MIN = {"all": 0, "errors_and_warnings": 1, "errors": 2, "none": 99}
_PASSING_MERGE_STATES = {"CLEAN", "UNSTABLE"}
_SUPPORTED_SCHEMA_VERSION = 3


def evaluate_merge_readiness(
    contract: DeliveryContract,
    evidence: MergeEvidence,
    expected_head_sha: str,
) -> MergeReadinessDecision:
    if contract.schema_version != _SUPPORTED_SCHEMA_VERSION:
        blocker = MergeBlocker("UNSUPPORTED_SCHEMA_VERSION", str(contract.schema_version))
        return MergeReadinessDecision(ready=False, blockers=(blocker,))
    blockers = (
        _identity_blockers(evidence, expected_head_sha)
        + _check_run_blockers(contract, evidence)
        + _ruleset_blockers(contract, evidence)
        + _scanning_blockers(contract, evidence)
        + _review_blockers(contract, evidence)
        + _pull_request_state_blockers(evidence)
    )
    ordered = tuple(sorted(set(blockers)))
    return MergeReadinessDecision(ready=not ordered, blockers=ordered)


def _identity_blockers(evidence: MergeEvidence, expected_head_sha: str) -> list[MergeBlocker]:
    before = evidence.pull_request_before
    after = evidence.pull_request_after
    if before is None or after is None:
        return [MergeBlocker("MISSING_PR_EVIDENCE", "before/after pull request identity")]
    blockers: list[MergeBlocker] = []
    if before != after:
        blockers.append(MergeBlocker("PR_IDENTITY_DRIFT", "before/after identities differ"))
    if after.head_sha != expected_head_sha:
        blockers.append(MergeBlocker("HEAD_SHA_MISMATCH", f"head {after.head_sha}"))
    if not after.potential_merge_sha:
        blockers.append(MergeBlocker("MISSING_MERGE_CANDIDATE", "no potential merge SHA"))
    return blockers


def _check_run_blockers(contract: DeliveryContract, evidence: MergeEvidence) -> list[MergeBlocker]:
    runs = evidence.check_runs
    if runs is None:
        return [MergeBlocker("MISSING_EVIDENCE", "check run evidence")]
    blockers: list[MergeBlocker] = []
    if "check_runs" in evidence.incomplete_sections:
        blockers.append(MergeBlocker("INCOMPLETE_EVIDENCE", "check run pagination"))
    after = evidence.pull_request_after
    head_sha = after.head_sha if after is not None else None
    for required in contract.required_status_checks:
        same_context = [run for run in runs if run.context == required.context]
        if not same_context:
            blockers.append(MergeBlocker("REQUIRED_CHECK_MISSING", required.context))
            continue
        pinned = [run for run in same_context if run.integration_id == required.integration_id]
        if not pinned:
            blockers.append(MergeBlocker("REQUIRED_CHECK_INTEGRATION_MISMATCH", required.context))
            continue
        current = [run for run in pinned if head_sha is None or run.head_sha == head_sha]
        if not current:
            blockers.append(MergeBlocker("REQUIRED_CHECK_STALE", required.context))
            continue
        if any(run.conclusion != "success" for run in current):
            blockers.append(MergeBlocker("REQUIRED_CHECK_FAILING", required.context))
    return blockers


def _ruleset_blockers(contract: DeliveryContract, evidence: MergeEvidence) -> list[MergeBlocker]:
    ruleset = evidence.ruleset
    if ruleset is None:
        return [MergeBlocker("MISSING_EVIDENCE", "ruleset evidence")]
    blockers: list[MergeBlocker] = []
    if ruleset.ruleset_id != contract.ruleset_id:
        blockers.append(
            MergeBlocker("RULESET_ID_MISMATCH", f"{ruleset.ruleset_id} != {contract.ruleset_id}")
        )
    if ruleset.enforcement != "active":
        blockers.append(MergeBlocker("RULESET_INACTIVE", ruleset.enforcement))
    if ruleset.bypass_actors is None:
        blockers.append(
            MergeBlocker("RULESET_BYPASS_EVIDENCE_MISSING", "bypass actors uncollected")
        )
    elif ruleset.bypass_actors:
        blockers.append(MergeBlocker("RULESET_BYPASS_ACTOR", ",".join(ruleset.bypass_actors)))
    blockers.extend(_ruleset_scope_blockers(ruleset, evidence.pull_request_after))
    if frozenset(ruleset.status_checks or ()) != frozenset(contract.required_status_checks):
        blockers.append(MergeBlocker("RULESET_STATUS_CHECK_DRIFT", "live checks differ"))
    if frozenset(ruleset.code_scanning or ()) != frozenset(contract.required_code_scanning):
        blockers.append(MergeBlocker("RULESET_CODE_SCANNING_DRIFT", "live scanning differs"))
    return blockers


def _ruleset_scope_blockers(
    ruleset: RulesetEvidence,
    after: PullRequestIdentity | None,
) -> list[MergeBlocker]:
    included = ruleset.included_refs
    excluded = ruleset.excluded_refs
    if ruleset.target is None or included is None or excluded is None:
        return [MergeBlocker("RULESET_SCOPE_MISSING", "ruleset ref scope not collected")]
    if ruleset.target != "branch":
        return [MergeBlocker("RULESET_SCOPE_MISMATCH", f"target {ruleset.target}")]
    if after is None or not after.base_ref:
        return []
    ref = f"refs/heads/{after.base_ref}"
    if ref not in included or ref in excluded:
        return [MergeBlocker("RULESET_SCOPE_MISMATCH", f"{ref} outside ruleset scope")]
    return []


def _scanning_blockers(contract: DeliveryContract, evidence: MergeEvidence) -> list[MergeBlocker]:
    scanning = evidence.code_scanning
    if scanning is None:
        return [MergeBlocker("MISSING_EVIDENCE", "code scanning evidence")]
    blockers: list[MergeBlocker] = []
    if "code_scanning" in evidence.incomplete_sections:
        blockers.append(MergeBlocker("INCOMPLETE_EVIDENCE", "code scanning pagination"))
    if scanning.analyses is None:
        blockers.append(MergeBlocker("MISSING_EVIDENCE", "code scanning analyses"))
    if scanning.alerts is None:
        blockers.append(MergeBlocker("MISSING_EVIDENCE", "code scanning alerts"))
    after = evidence.pull_request_after
    blockers.extend(_queried_ref_blockers(scanning, after))
    merge_sha = after.potential_merge_sha if after is not None else None
    for requirement in contract.required_code_scanning:
        if scanning.analyses is not None and merge_sha:
            blockers.extend(_analysis_blockers(requirement, scanning.analyses, merge_sha))
        if scanning.alerts is not None:
            blockers.extend(_alert_blockers(requirement, scanning.alerts))
    return blockers


def _queried_ref_blockers(
    scanning: CodeScanningEvidence,
    after: PullRequestIdentity | None,
) -> list[MergeBlocker]:
    if scanning.queried_ref is None:
        return [MergeBlocker("MISSING_EVIDENCE", "code scanning queried ref")]
    expected = f"refs/pull/{after.number}/merge" if after is not None else None
    if scanning.queried_ref != expected:
        return [MergeBlocker("CODE_SCANNING_REF_MISMATCH", scanning.queried_ref)]
    return []


def _analysis_blockers(
    requirement: CodeScanningRequirement,
    analyses: tuple[CodeScanningAnalysis, ...],
    merge_sha: str,
) -> list[MergeBlocker]:
    tool_analyses = [a for a in analyses if a.tool == requirement.tool]
    if not tool_analyses:
        return [MergeBlocker("CODE_SCANNING_ANALYSIS_MISSING", requirement.tool)]
    current = [a for a in tool_analyses if a.commit_sha == merge_sha]
    if not current:
        return [MergeBlocker("CODE_SCANNING_ANALYSIS_STALE", requirement.tool)]
    blockers: list[MergeBlocker] = []
    for analysis in current:
        if analysis.error is None:
            blockers.append(MergeBlocker("INCOMPLETE_EVIDENCE", f"{requirement.tool} error state"))
        elif analysis.error:
            blockers.append(MergeBlocker("CODE_SCANNING_ANALYSIS_ERROR", analysis.error))
    return blockers


def _alert_blockers(
    requirement: CodeScanningRequirement,
    alerts: tuple[CodeScanningAlert, ...],
) -> list[MergeBlocker]:
    security_min = _SECURITY_THRESHOLD_MIN.get(requirement.security_alerts_threshold)
    alerts_min = _ALERTS_THRESHOLD_MIN.get(requirement.alerts_threshold)
    blockers: list[MergeBlocker] = []
    if security_min is None:
        blockers.append(
            MergeBlocker("UNKNOWN_SECURITY_THRESHOLD", requirement.security_alerts_threshold)
        )
    if alerts_min is None:
        blockers.append(MergeBlocker("UNKNOWN_ALERTS_THRESHOLD", requirement.alerts_threshold))
    for alert in alerts:
        if alert.tool == requirement.tool and alert.state == "open":
            blockers.extend(_single_alert_blockers(alert, security_min, alerts_min))
    return blockers


def _single_alert_blockers(
    alert: CodeScanningAlert,
    security_min: int | None,
    alerts_min: int | None,
) -> list[MergeBlocker]:
    if alert.security_severity is not None:
        rank = _SECURITY_SEVERITY_RANK.get(alert.security_severity)
        if rank is None:
            return [MergeBlocker("UNKNOWN_ALERT_SEVERITY", alert.security_severity)]
        if security_min is not None and rank >= security_min:
            return [MergeBlocker("CODE_SCANNING_ALERT", f"security {alert.security_severity}")]
        return []
    rank = _RULE_SEVERITY_RANK.get(alert.rule_severity or "")
    if rank is None:
        return [MergeBlocker("UNKNOWN_ALERT_SEVERITY", alert.rule_severity or "absent")]
    if alerts_min is not None and rank >= alerts_min:
        return [MergeBlocker("CODE_SCANNING_ALERT", f"rule {alert.rule_severity}")]
    return []


def _review_blockers(contract: DeliveryContract, evidence: MergeEvidence) -> list[MergeBlocker]:
    blockers: list[MergeBlocker] = []
    if evidence.review_states is None:
        blockers.append(MergeBlocker("MISSING_EVIDENCE", "review evidence"))
    else:
        if "reviews" in evidence.incomplete_sections:
            blockers.append(MergeBlocker("INCOMPLETE_EVIDENCE", "review pagination"))
        if not contract.allow_changes_requested and "CHANGES_REQUESTED" in evidence.review_states:
            blockers.append(MergeBlocker("CHANGES_REQUESTED", "a review requested changes"))
        approvals = evidence.review_states.count("APPROVED")
        if approvals < contract.required_approving_reviews:
            blockers.append(MergeBlocker("INSUFFICIENT_APPROVALS", str(approvals)))
    if evidence.review_threads is None:
        blockers.append(MergeBlocker("MISSING_EVIDENCE", "review thread evidence"))
    else:
        if "review_threads" in evidence.incomplete_sections:
            blockers.append(MergeBlocker("INCOMPLETE_EVIDENCE", "review thread pagination"))
        if contract.require_review_thread_resolution and not all(evidence.review_threads):
            blockers.append(MergeBlocker("UNRESOLVED_REVIEW_THREAD", "unresolved thread"))
    return blockers


def _pull_request_state_blockers(evidence: MergeEvidence) -> list[MergeBlocker]:
    blockers: list[MergeBlocker] = []
    if evidence.is_draft is None:
        blockers.append(MergeBlocker("MISSING_EVIDENCE", "draft state"))
    elif evidence.is_draft:
        blockers.append(MergeBlocker("DRAFT_PULL_REQUEST", "pull request is a draft"))
    if evidence.merge_state is None:
        blockers.append(MergeBlocker("MISSING_EVIDENCE", "merge state"))
    elif evidence.merge_state not in _PASSING_MERGE_STATES:
        blockers.append(MergeBlocker("BLOCKING_MERGE_STATE", evidence.merge_state))
    return blockers
