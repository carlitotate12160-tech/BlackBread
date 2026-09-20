"""Pure strict normalization of decoded GitHub merge-evidence response bodies.

Every ``normalize_*`` function returns a fully-formed value or raises
``EvidenceNormalizationError`` -- no silent partial result, no I/O, no
pagination or readiness decision. Those belong to this module's consumer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from blackbread.governance.merge_readiness import (
    CheckRunEvidence,
    CodeScanningAlert,
    CodeScanningAnalysis,
    CodeScanningRequirement,
    PullRequestIdentity,
    RequiredStatusCheck,
    RulesetEvidence,
)

_STATUS_RULE = "required_status_checks"
_SCANNING_RULE = "code_scanning"

_MALFORMED_BODY = "MALFORMED_BODY"
_MALFORMED_ITEM = "MALFORMED_ITEM"
_DUPLICATE_RULE = "DUPLICATE_MODELED_RULE"
_INCONSISTENT_PROVENANCE = "INCONSISTENT_PROVENANCE"
_INCONSISTENT_TOTAL_COUNT = "INCONSISTENT_TOTAL_COUNT"
_GRAPHQL_ERROR = "GRAPHQL_ERROR"

_RuleModel = tuple[
    tuple[RequiredStatusCheck, ...] | None,
    tuple[CodeScanningRequirement, ...] | None,
    bool | None,
    tuple[str, ...],
]


class EvidenceNormalizationError(Exception):
    """Malformed/ambiguous/inconsistent fragment; the message never embeds input."""

    def __init__(self, code: str) -> None:
        super().__init__(f"evidence normalization failed: {code}")
        self.code = code


@dataclass(frozen=True, slots=True)
class PullRequestObservation:
    identity: PullRequestIdentity
    is_draft: bool
    merge_state: str


@dataclass(frozen=True, slots=True)
class CheckRunPage:
    check_runs: tuple[CheckRunEvidence, ...]
    total_count: int


@dataclass(frozen=True, slots=True)
class ReviewThreadPage:
    observation: PullRequestObservation
    resolved: tuple[bool, ...]
    has_next_page: bool
    end_cursor: str | None


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EvidenceNormalizationError(code)


def _str_field(source: Any, key: str, code: str = _MALFORMED_ITEM) -> str:
    """A required string field that is non-empty once stripped; raises otherwise."""
    value = source.get(key) if isinstance(source, dict) else None
    _require(isinstance(value, str) and bool(value.strip()), code)
    return cast(str, value)


def _int_field(value: Any, code: str = _MALFORMED_BODY) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), code)
    return cast(int, value)


def _opt_int_field(value: Any) -> int | None:
    # Absent stays None; a present non-integer (or bool) is malformed, not missing.
    _require(
        value is None or (isinstance(value, int) and not isinstance(value, bool)), _MALFORMED_ITEM
    )
    return cast("int | None", value)


def _bool_field(value: Any, code: str = _MALFORMED_BODY) -> bool:
    _require(isinstance(value, bool), code)
    return cast(bool, value)


def _identity(
    number: int, head_sha: str, base_sha: str, base_ref: str, merge_sha: str | None
) -> PullRequestIdentity:
    # A null merge commit becomes "" so the evaluator's own blocker rejects it.
    return PullRequestIdentity(
        number=number,
        head_sha=head_sha,
        base_sha=base_sha,
        base_ref=base_ref,
        potential_merge_sha=merge_sha or "",
    )


def _observation(
    identity: PullRequestIdentity, is_draft: bool, merge_state: str
) -> PullRequestObservation:
    return PullRequestObservation(
        identity=identity, is_draft=is_draft, merge_state=merge_state.strip().upper()
    )


def normalize_pull_request(body: Any) -> PullRequestObservation:
    _require(isinstance(body, dict), _MALFORMED_BODY)
    number = _int_field(body.get("number"))
    head_sha = _str_field(body.get("head"), "sha", _MALFORMED_BODY)
    base_sha = _str_field(body.get("base"), "sha", _MALFORMED_BODY)
    base_ref = _str_field(body.get("base"), "ref", _MALFORMED_BODY)
    merge_sha = body.get("merge_commit_sha")
    _require(merge_sha is None or isinstance(merge_sha, str), _MALFORMED_BODY)
    is_draft = _bool_field(body.get("draft"))
    merge_state = _str_field(body, "mergeable_state", _MALFORMED_BODY)
    identity = _identity(number, head_sha, base_sha, base_ref, merge_sha)
    return _observation(identity, is_draft, merge_state)


def normalize_check_runs_page(body: Any) -> CheckRunPage:
    def check_run(item: Any) -> CheckRunEvidence:
        context = _str_field(item, "name")
        head_sha = _str_field(item, "head_sha")
        conclusion, app = item.get("conclusion"), item.get("app")
        _require(conclusion is None or isinstance(conclusion, str), _MALFORMED_ITEM)
        # A present but non-dict app is malformed evidence, never "no app".
        _require(app is None or isinstance(app, dict), _MALFORMED_ITEM)
        integration_id = _opt_int_field(app.get("id") if app is not None else None)
        return CheckRunEvidence(
            context=context, integration_id=integration_id, head_sha=head_sha, conclusion=conclusion
        )

    _require(isinstance(body, dict), _MALFORMED_BODY)
    raw_runs = body.get("check_runs")
    _require(isinstance(raw_runs, list), _MALFORMED_BODY)
    total_count = _int_field(body.get("total_count"))
    # A page can never claim fewer total items than it actually carries.
    _require(total_count >= len(raw_runs), _INCONSISTENT_TOTAL_COUNT)
    runs = tuple(check_run(item) for item in raw_runs)
    return CheckRunPage(check_runs=runs, total_count=total_count)


def _modeled(matches: list[dict[str, Any]], param_key: str, parser: Callable[[Any], Any]) -> Any:
    if not matches:
        return None
    params = matches[0].get("parameters")
    items = params.get(param_key) if isinstance(params, dict) else None
    _require(isinstance(items, list), _MALFORMED_ITEM)
    return tuple(parser(item) for item in cast(list[Any], items))


def _strict_branch_currency(matches: list[dict[str, Any]]) -> bool | None:
    if not matches:
        return None
    params = matches[0].get("parameters")
    value = params.get("strict_required_status_checks_policy") if isinstance(params, dict) else None
    # Absent stays unobserved (None); a present non-boolean is malformed, never falsy-coerced.
    _require(value is None or isinstance(value, bool), _MALFORMED_ITEM)
    return cast("bool | None", value)


def _rules(rules: Any) -> _RuleModel:
    def status_check(item: Any) -> RequiredStatusCheck:
        context = _str_field(item, "context")
        return RequiredStatusCheck(
            context=context, integration_id=_opt_int_field(item.get("integration_id"))
        )

    def scanning_requirement(item: Any) -> CodeScanningRequirement:
        return CodeScanningRequirement(
            tool=_str_field(item, "tool"),
            security_alerts_threshold=_str_field(item, "security_alerts_threshold"),
            alerts_threshold=_str_field(item, "alerts_threshold"),
        )

    if rules is None:
        return None, None, None, ()
    _require(isinstance(rules, list), _MALFORMED_BODY)
    unmodeled: list[str] = []
    status_rules: list[dict[str, Any]] = []
    scanning_rules: list[dict[str, Any]] = []
    for rule in rules:
        rule_type = _str_field(rule, "type")
        if rule_type == _STATUS_RULE:
            status_rules.append(rule)
        elif rule_type == _SCANNING_RULE:
            scanning_rules.append(rule)
        else:
            unmodeled.append(rule_type)
    # A duplicated modeled rule is ambiguous -- never an arbitrary pick.
    _require(len(status_rules) <= 1, _DUPLICATE_RULE)
    _require(len(scanning_rules) <= 1, _DUPLICATE_RULE)
    status = _modeled(status_rules, "required_status_checks", status_check)
    scanning = _modeled(scanning_rules, "code_scanning_tools", scanning_requirement)
    strict = _strict_branch_currency(status_rules)
    return status, scanning, strict, tuple(unmodeled)


def normalize_ruleset(body: Any) -> RulesetEvidence:
    def string_tuple(value: Any) -> tuple[str, ...] | None:
        # Absent stays None (the evaluator blocks on it); present-but-wrong is malformed.
        if value is None:
            return None
        _require(isinstance(value, list), _MALFORMED_ITEM)
        _require(all(isinstance(item, str) for item in value), _MALFORMED_ITEM)
        return tuple(value)

    def bypass_actor(item: Any) -> str:
        actor_type = _str_field(item, "actor_type")
        actor_id = _int_field(item.get("actor_id"), _MALFORMED_ITEM)
        return f"{actor_type}:{actor_id}"

    def bypass_actors(value: Any) -> tuple[str, ...] | None:
        # Missing -> None; a genuine empty list -> ().
        if value is None:
            return None
        _require(isinstance(value, list), _MALFORMED_BODY)
        return tuple(bypass_actor(item) for item in value)

    _require(isinstance(body, dict), _MALFORMED_BODY)
    ruleset_id = _int_field(body.get("id"))
    enforcement = _str_field(body, "enforcement", _MALFORMED_BODY)
    status_checks, code_scanning, strict_currency, unmodeled = _rules(body.get("rules"))
    target = body.get("target")
    _require(target is None or (isinstance(target, str) and bool(target.strip())), _MALFORMED_BODY)
    conditions = body.get("conditions")
    _require(conditions is None or isinstance(conditions, dict), _MALFORMED_BODY)
    ref_name = conditions.get("ref_name") if conditions is not None else None
    _require(ref_name is None or isinstance(ref_name, dict), _MALFORMED_BODY)
    included = string_tuple(ref_name.get("include")) if ref_name is not None else None
    excluded = string_tuple(ref_name.get("exclude")) if ref_name is not None else None
    return RulesetEvidence(
        ruleset_id=ruleset_id,
        enforcement=enforcement,
        bypass_actors=bypass_actors(body.get("bypass_actors")),
        status_checks=status_checks,
        code_scanning=code_scanning,
        target=target,
        included_refs=included,
        excluded_refs=excluded,
        strict_branch_currency=strict_currency,
        unmodeled_rule_types=unmodeled,
    )


def normalize_code_scanning_analyses(
    body: Any, *, queried_ref: str
) -> tuple[CodeScanningAnalysis, ...]:
    def analysis(item: Any) -> CodeScanningAnalysis:
        tool = _str_field(item.get("tool") if isinstance(item, dict) else None, "name")
        commit_sha = _str_field(item, "commit_sha")
        error = item.get("error") if isinstance(item, dict) else None
        _require(isinstance(error, str), _MALFORMED_ITEM)
        _require(item.get("ref") == queried_ref, _INCONSISTENT_PROVENANCE)
        return CodeScanningAnalysis(tool=tool, commit_sha=commit_sha, error=error)

    _require(isinstance(body, list), _MALFORMED_BODY)
    return tuple(analysis(item) for item in body)


def normalize_code_scanning_alerts(
    body: Any, *, queried_ref: str, expected_commit_sha: str, expected_tool: str
) -> tuple[CodeScanningAlert, ...]:
    def alert(item: Any) -> CodeScanningAlert:
        _require(isinstance(item, dict), _MALFORMED_ITEM)
        tool = _str_field(item.get("tool"), "name")
        state = _str_field(item, "state")
        rule = item.get("rule")
        _require(isinstance(rule, dict), _MALFORMED_ITEM)
        security, severity = rule.get("security_severity_level"), rule.get("severity")
        _require(security is None or isinstance(security, str), _MALFORMED_ITEM)
        _require(severity is None or isinstance(severity, str), _MALFORMED_ITEM)
        if tool == expected_tool:
            # A mixed response's other-tool alerts pass through unvalidated.
            instance = item.get("most_recent_instance")
            ref = instance.get("ref") if isinstance(instance, dict) else None
            commit_sha = instance.get("commit_sha") if isinstance(instance, dict) else None
            _require(
                ref == queried_ref and commit_sha == expected_commit_sha, _INCONSISTENT_PROVENANCE
            )
        return CodeScanningAlert(
            tool=tool, state=state, security_severity=security, rule_severity=severity
        )

    _require(isinstance(body, list), _MALFORMED_BODY)
    return tuple(alert(item) for item in body)


def normalize_reviews(body: Any) -> tuple[str, ...]:
    _require(isinstance(body, list), _MALFORMED_BODY)
    return tuple(_str_field(item, "state") for item in body)


def _resolved(node: Any) -> bool:
    value = node.get("isResolved") if isinstance(node, dict) else None
    _require(isinstance(value, bool), _MALFORMED_ITEM)
    return cast(bool, value)


def normalize_review_threads_page(body: Any) -> ReviewThreadPage:
    _require(isinstance(body, dict), _MALFORMED_BODY)
    _require(not body.get("errors"), _GRAPHQL_ERROR)
    data = body.get("data")
    repository = data.get("repository") if isinstance(data, dict) else None
    pull_request = repository.get("pullRequest") if isinstance(repository, dict) else None
    _require(isinstance(pull_request, dict), _MALFORMED_BODY)
    pull_request = cast(dict[str, Any], pull_request)
    number = _int_field(pull_request.get("number"))
    head_sha = _str_field(pull_request, "headRefOid", _MALFORMED_BODY)
    base_sha = _str_field(pull_request, "baseRefOid", _MALFORMED_BODY)
    base_ref = _str_field(pull_request, "baseRefName", _MALFORMED_BODY)
    is_draft = _bool_field(pull_request.get("isDraft"))
    merge_state = _str_field(pull_request, "mergeable", _MALFORMED_BODY)
    merge_commit = pull_request.get("potentialMergeCommit")
    _require(merge_commit is None or isinstance(merge_commit, dict), _MALFORMED_BODY)
    merge_sha = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
    _require(merge_sha is None or isinstance(merge_sha, str), _MALFORMED_BODY)
    identity = _identity(number, head_sha, base_sha, base_ref, merge_sha)
    observation = _observation(identity, is_draft, merge_state)
    threads = pull_request.get("reviewThreads")
    _require(isinstance(threads, dict), _MALFORMED_BODY)
    threads = cast(dict[str, Any], threads)
    page_info, nodes = threads.get("pageInfo"), threads.get("nodes")
    _require(isinstance(page_info, dict) and isinstance(nodes, list), _MALFORMED_BODY)
    has_next = _bool_field(cast(dict[str, Any], page_info).get("hasNextPage"))
    end_cursor = cast(dict[str, Any], page_info).get("endCursor")
    _require(end_cursor is None or isinstance(end_cursor, str), _MALFORMED_BODY)
    _require(not has_next or bool(end_cursor), _MALFORMED_BODY)
    resolved = tuple(_resolved(node) for node in cast(list[Any], nodes))
    return ReviewThreadPage(
        observation=observation, resolved=resolved, has_next_page=has_next, end_cursor=end_cursor
    )
