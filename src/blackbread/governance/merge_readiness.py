"""Fail-closed merge-readiness evaluation against the delivery contract.

The read-only collector in ``blackbread.governance.github_merge_evidence``
produces an immutable :class:`EvidenceSnapshot`; :func:`evaluate_readiness`
compares it with the machine contract in ``.github/agent-delivery.json``
(schema version 3) and reports blockers only. The live GitHub ruleset remains
the merge authority; nothing here grants merge capability.
"""

from enum import StrEnum
from typing import NamedTuple

_SEC_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_SEC_MIN = {"critical": 4, "high_or_higher": 3, "medium_or_higher": 2, "all": 1, "none": 5}
_ALERT_RANK = {"error": 3, "warning": 2, "note": 1}
_ALERT_MIN = {"errors": 3, "errors_and_warnings": 2, "all": 1, "none": 4}


class CodeScanningRequirement(NamedTuple):
    """One ``code_scanning`` tool rule; shared by contract and live evidence."""

    tool: str
    security_alerts_threshold: str
    alerts_threshold: str


class DeliveryContract(NamedTuple):
    """The ``agent_delivery`` merge gates the evaluator consumes (schema v3)."""

    ruleset_id: int
    require_branch_up_to_date: bool
    require_review_thread_resolution: bool
    allow_changes_requested: bool
    required_status_checks: tuple[str, ...]
    required_code_scanning: tuple[CodeScanningRequirement, ...]


class PullRequestIdentity(NamedTuple):
    """Identity bound before and after collection; any change is drift."""

    head_sha: str
    base_sha: str
    potential_merge_commit_sha: str | None


class CheckRunEvidence(NamedTuple):
    check_run_id: int
    name: str
    status: str
    conclusion: str | None


class CodeScanningAnalysisEvidence(NamedTuple):
    tool: str
    commit_sha: str
    error: str | None
    created_at: str


class CodeScanningAlertEvidence(NamedTuple):
    number: int
    state: str
    tool: str
    security_severity_level: str | None
    severity: str | None


class RulesetEvidence(NamedTuple):
    """Normalized live ruleset view; ``None`` marks a missing/unreadable part."""

    ruleset_id: int | None
    enforcement: str | None
    required_status_check_contexts: tuple[str, ...] | None
    strict_status_checks: bool | None
    code_scanning_tools: tuple[CodeScanningRequirement, ...] | None
    unknown_rule_types: tuple[str, ...]


class EvidenceSnapshot(NamedTuple):
    """One read-only collection result bound to a pull request merge head."""

    repository: str
    ruleset: RulesetEvidence | None
    pull_request_before: PullRequestIdentity | None
    pull_request_after: PullRequestIdentity | None
    merge_state_status: str | None
    unresolved_review_threads: int | None
    changes_requested: bool | None
    check_runs: tuple[CheckRunEvidence, ...] | None
    analyses: tuple[CodeScanningAnalysisEvidence, ...] | None
    alerts: tuple[CodeScanningAlertEvidence, ...] | None
    errors: tuple[str, ...]


class BlockerCode(StrEnum):
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    EXPECTED_HEAD_MISMATCH = "expected_head_mismatch"
    IDENTITY_DRIFT = "identity_drift"
    RULESET_UNAVAILABLE = "ruleset_unavailable"
    RULESET_INACTIVE = "ruleset_inactive"
    RULESET_MISMATCH = "ruleset_mismatch"
    RULESET_UNKNOWN_RULE = "ruleset_unknown_rule"
    STATUS_CHECK_RULE_MISSING = "status_check_rule_missing"
    STATUS_CHECK_RULE_MISMATCH = "status_check_rule_mismatch"
    CODE_SCANNING_RULE_MISSING = "code_scanning_rule_missing"
    CODE_SCANNING_RULE_MISMATCH = "code_scanning_rule_mismatch"
    CODE_SCANNING_ANALYSIS_MISSING = "code_scanning_analysis_missing"
    CODE_SCANNING_ANALYSIS_ERROR = "code_scanning_analysis_error"
    CODE_SCANNING_SECURITY_ALERTS = "code_scanning_security_alerts"
    CODE_SCANNING_ALERTS = "code_scanning_alerts"
    UNSUPPORTED_THRESHOLD = "unsupported_threshold"
    REQUIRED_CHECK_MISSING = "required_check_missing"
    REQUIRED_CHECK_NOT_SUCCESS = "required_check_not_success"
    UNRESOLVED_REVIEW_THREADS = "unresolved_review_threads"
    CHANGES_REQUESTED = "changes_requested"
    MERGE_STATE_NOT_CLEAN = "merge_state_not_clean"


class Blocker(NamedTuple):
    code: BlockerCode
    detail: str


class ReadinessReport(NamedTuple):
    ready: bool
    repository: str
    ruleset_id: int | None
    expected_head_sha: str
    observed_head_sha: str | None
    base_sha: str | None
    potential_merge_commit_sha: str | None
    blockers: tuple[Blocker, ...]
    evidence_errors: tuple[str, ...]


def evaluate_readiness(
    contract: DeliveryContract, snapshot: EvidenceSnapshot, expected_head_sha: str
) -> ReadinessReport:
    """Evaluate one snapshot; missing or contradictory evidence always blocks."""
    out: list[Blocker] = []
    _check_ruleset(contract, snapshot.ruleset, out)
    _check_identity(snapshot, expected_head_sha, out)
    _check_status_checks(contract, snapshot.check_runs, out)
    _check_code_scanning(contract, snapshot, out)
    _check_review_gates(contract, snapshot, out)
    out.extend(Blocker(BlockerCode.EVIDENCE_INCOMPLETE, e) for e in snapshot.errors)
    bound = snapshot.pull_request_after or snapshot.pull_request_before
    return ReadinessReport(
        ready=not out,
        repository=snapshot.repository,
        ruleset_id=snapshot.ruleset.ruleset_id if snapshot.ruleset else None,
        expected_head_sha=expected_head_sha,
        observed_head_sha=bound.head_sha if bound else None,
        base_sha=bound.base_sha if bound else None,
        potential_merge_commit_sha=bound.potential_merge_commit_sha if bound else None,
        blockers=tuple(sorted(out, key=lambda b: (b.code.value, b.detail))),
        evidence_errors=snapshot.errors,
    )


def _ruleset_checks(
    contract: DeliveryContract, ruleset: RulesetEvidence
) -> tuple[tuple[bool, BlockerCode, str], ...]:
    """Build the ordered blocker checks for one ruleset."""
    contexts = ruleset.required_status_check_contexts
    strict = ruleset.strict_status_checks
    tools = ruleset.code_scanning_tools
    return (
        (
            ruleset.ruleset_id != contract.ruleset_id,
            BlockerCode.RULESET_MISMATCH,
            f"expected {contract.ruleset_id}, observed {ruleset.ruleset_id}",
        ),
        (
            ruleset.enforcement != "active",
            BlockerCode.RULESET_INACTIVE,
            f"enforcement={ruleset.enforcement}",
        ),
        (
            bool(ruleset.unknown_rule_types),
            BlockerCode.RULESET_UNKNOWN_RULE,
            ",".join(sorted(ruleset.unknown_rule_types)),
        ),
        (
            contexts is None or strict is None,
            BlockerCode.STATUS_CHECK_RULE_MISSING,
            "required_status_checks rule missing or unreadable",
        ),
        (
            contexts is not None
            and (
                tuple(contract.required_status_checks) != contexts
                or strict != contract.require_branch_up_to_date
            ),
            BlockerCode.STATUS_CHECK_RULE_MISMATCH,
            f"contexts={contexts} strict={strict}",
        ),
        (
            tools is None,
            BlockerCode.CODE_SCANNING_RULE_MISSING,
            "code_scanning rule missing or unreadable",
        ),
        (
            tools is not None and tuple(contract.required_code_scanning) != tools,
            BlockerCode.CODE_SCANNING_RULE_MISMATCH,
            f"tools={tools}",
        ),
    )


def _check_ruleset(
    contract: DeliveryContract, ruleset: RulesetEvidence | None, out: list[Blocker]
) -> None:
    if ruleset is None:
        out.append(Blocker(BlockerCode.RULESET_UNAVAILABLE, "no ruleset evidence"))
        return
    checks = _ruleset_checks(contract, ruleset)
    out.extend(Blocker(code, detail) for failed, code, detail in checks if failed)


def _check_identity(snapshot: EvidenceSnapshot, expected_head_sha: str, out: list[Blocker]) -> None:
    before, after = snapshot.pull_request_before, snapshot.pull_request_after
    if before is None or after is None:
        out.append(Blocker(BlockerCode.EVIDENCE_INCOMPLETE, "pull request identity unreadable"))
        return
    if after.head_sha != expected_head_sha:
        out.append(
            Blocker(
                BlockerCode.EXPECTED_HEAD_MISMATCH,
                f"expected {expected_head_sha}, observed {after.head_sha}",
            )
        )
    if before != after:
        out.append(
            Blocker(
                BlockerCode.IDENTITY_DRIFT,
                "head, base, or potential merge commit changed during collection",
            )
        )


def _check_status_checks(
    contract: DeliveryContract,
    check_runs: tuple[CheckRunEvidence, ...] | None,
    out: list[Blocker],
) -> None:
    if check_runs is None:
        out.append(Blocker(BlockerCode.EVIDENCE_INCOMPLETE, "check-run evidence unavailable"))
        return
    latest: dict[str, CheckRunEvidence] = {}
    for run in check_runs:
        current = latest.get(run.name)
        if current is None or run.check_run_id > current.check_run_id:
            latest[run.name] = run
    for context in contract.required_status_checks:
        found = latest.get(context)
        if found is None:
            out.append(Blocker(BlockerCode.REQUIRED_CHECK_MISSING, context))
        elif found.status != "completed" or found.conclusion != "success":
            out.append(
                Blocker(
                    BlockerCode.REQUIRED_CHECK_NOT_SUCCESS,
                    f"{context}: status={found.status} conclusion={found.conclusion}",
                )
            )


def _check_code_scanning(
    contract: DeliveryContract, snapshot: EvidenceSnapshot, out: list[Blocker]
) -> None:
    identity = snapshot.pull_request_after or snapshot.pull_request_before
    shas = (
        {s for s in (identity.head_sha, identity.potential_merge_commit_sha) if s}
        if identity
        else set()
    )
    for req in contract.required_code_scanning:
        if snapshot.analyses is None:
            out.append(
                Blocker(BlockerCode.EVIDENCE_INCOMPLETE, f"{req.tool}: analyses unavailable")
            )
        elif not (
            current := [a for a in snapshot.analyses if a.tool == req.tool and a.commit_sha in shas]
        ):
            out.append(
                Blocker(
                    BlockerCode.CODE_SCANNING_ANALYSIS_MISSING,
                    f"{req.tool}: no analysis for the merge candidate",
                )
            )
        elif (latest := max(current, key=lambda a: a.created_at)).error:
            out.append(
                Blocker(BlockerCode.CODE_SCANNING_ANALYSIS_ERROR, f"{req.tool}: {latest.error}")
            )
        _check_alert_thresholds(req, snapshot.alerts, out)


def _check_alert_thresholds(
    req: CodeScanningRequirement,
    alerts: tuple[CodeScanningAlertEvidence, ...] | None,
    out: list[Blocker],
) -> None:
    if alerts is None:
        out.append(Blocker(BlockerCode.EVIDENCE_INCOMPLETE, f"{req.tool}: alerts unavailable"))
        return
    security_min = _SEC_MIN.get(req.security_alerts_threshold)
    alert_min = _ALERT_MIN.get(req.alerts_threshold)
    if security_min is None or alert_min is None:
        out.append(
            Blocker(
                BlockerCode.UNSUPPORTED_THRESHOLD,
                f"{req.tool}: {req.security_alerts_threshold}/{req.alerts_threshold}",
            )
        )
        return
    open_alerts = [a for a in alerts if a.state == "open" and a.tool == req.tool]
    if any(_SEC_RANK.get(a.security_severity_level or "", 0) >= security_min for a in open_alerts):
        out.append(
            Blocker(
                BlockerCode.CODE_SCANNING_SECURITY_ALERTS,
                f"{req.tool}: open security alert at or above {req.security_alerts_threshold}",
            )
        )
    if any(_ALERT_RANK.get(a.severity or "", 0) >= alert_min for a in open_alerts):
        out.append(
            Blocker(
                BlockerCode.CODE_SCANNING_ALERTS,
                f"{req.tool}: open alert at or above {req.alerts_threshold}",
            )
        )


def _check_review_gates(
    contract: DeliveryContract, snapshot: EvidenceSnapshot, out: list[Blocker]
) -> None:
    threads = snapshot.unresolved_review_threads
    checks = (
        (
            threads is None,
            BlockerCode.EVIDENCE_INCOMPLETE,
            "review-thread evidence unavailable",
        ),
        (
            threads is not None and contract.require_review_thread_resolution and threads > 0,
            BlockerCode.UNRESOLVED_REVIEW_THREADS,
            f"{threads} unresolved review thread(s)",
        ),
        (
            snapshot.changes_requested is None,
            BlockerCode.EVIDENCE_INCOMPLETE,
            "review-decision evidence unavailable",
        ),
        (
            snapshot.changes_requested is True and not contract.allow_changes_requested,
            BlockerCode.CHANGES_REQUESTED,
            "a changes-requested review remains",
        ),
        (
            snapshot.merge_state_status is None,
            BlockerCode.EVIDENCE_INCOMPLETE,
            "merge-state evidence unavailable",
        ),
        (
            snapshot.merge_state_status is not None and snapshot.merge_state_status != "CLEAN",
            BlockerCode.MERGE_STATE_NOT_CLEAN,
            f"mergeStateStatus={snapshot.merge_state_status}",
        ),
    )
    out.extend(Blocker(code, detail) for failed, code, detail in checks if failed)
