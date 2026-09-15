"""Proofs for pure, strict GitHub merge-evidence normalization (GOV-LIVE-GATES-001D1).

A "clean" fixture must normalize successfully unless noted. Malformed,
ambiguous, or inconsistent variants must raise ``EvidenceNormalizationError``
with a stable code and never leak the input.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from blackbread.governance import github_merge_normalization as norm
from blackbread.governance.github_merge_normalization import (
    CheckRunPage,
    EvidenceNormalizationError,
    PullRequestObservation,
    ReviewThreadPage,
    normalize_check_runs_page,
    normalize_code_scanning_alerts,
    normalize_code_scanning_analyses,
    normalize_pull_request,
    normalize_review_threads_page,
    normalize_reviews,
    normalize_ruleset,
)
from blackbread.governance.merge_readiness import (
    CheckRunEvidence,
    CodeScanningAlert,
    CodeScanningAnalysis,
    CodeScanningRequirement,
    DeliveryContract,
    MergeEvidence,
    PullRequestIdentity,
    RequiredStatusCheck,
    RulesetEvidence,
    evaluate_merge_readiness,
)

HEAD_SHA, BASE_SHA, MERGE_SHA = "1" * 40, "b" * 40, "2" * 40
REF = "refs/pull/91/merge"
SECRET = "unit-test-dummy-secret-marker"  # noqa: S105 -- sentinel, not a real credential

# --- Fixture builders --------------------------------------------------------


def _pr_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "number": 91,
        "head": {"sha": HEAD_SHA},
        "base": {"sha": BASE_SHA, "ref": "main"},
        "merge_commit_sha": MERGE_SHA,
        "draft": False,
        "mergeable_state": "clean",
    }
    return {**body, **overrides}


def _check_runs_body(**overrides: Any) -> dict[str, Any]:
    run = {"name": "ci-ok", "head_sha": HEAD_SHA, "conclusion": "success", "app": {"id": 15368}}
    return {"total_count": 1, "check_runs": [run], **overrides}


_RUN_BAD_APP = {"name": "x", "head_sha": HEAD_SHA, "conclusion": None, "app": "nope"}
_RUN_BOOL_ID = {"name": "x", "head_sha": HEAD_SHA, "conclusion": None, "app": {"id": True}}


def _rule(rule_type: str, **params: Any) -> dict[str, Any]:
    return {"type": rule_type, "parameters": params}


_CHECK_RULE = _rule(
    "required_status_checks", required_status_checks=[{"context": "ci-ok", "integration_id": 15368}]
)
_SCAN_RULE = _rule(
    "code_scanning",
    code_scanning_tools=[
        {
            "tool": "CodeQL",
            "security_alerts_threshold": "high_or_higher",
            "alerts_threshold": "errors",
        }
    ],
)
# bool is an int subclass, so a JSON true must not slip through as an integration id.
_BOOL_ID_RULE = _rule(
    "required_status_checks", required_status_checks=[{"context": "c", "integration_id": True}]
)


def _ruleset_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": 21644438,
        "enforcement": "active",
        "bypass_actors": [],
        "target": "branch",
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [_CHECK_RULE, _SCAN_RULE, {"type": "deletion"}],
    }
    return {**body, **overrides}


def _analysis(**overrides: Any) -> dict[str, Any]:
    item = {"tool": {"name": "CodeQL"}, "commit_sha": MERGE_SHA, "error": "", "ref": REF}
    return {**item, **overrides}


def _alert(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "tool": {"name": "CodeQL"},
        "state": "open",
        "rule": {"security_severity_level": "high", "severity": "error"},
        "most_recent_instance": {"ref": REF, "commit_sha": MERGE_SHA},
    }
    return {**item, **overrides}


def _threads(**overrides: Any) -> dict[str, Any]:
    page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [{"isResolved": True}]}
    return {**page, **overrides}


def _thread_pr(**overrides: Any) -> dict[str, Any]:
    pr: dict[str, Any] = {
        "number": 91,
        "headRefOid": HEAD_SHA,
        "baseRefOid": BASE_SHA,
        "baseRefName": "main",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "potentialMergeCommit": {"oid": MERGE_SHA},
        "reviewThreads": _threads(),
    }
    return {**pr, **overrides}


def _threads_body(pull_request: Any = None) -> dict[str, Any]:
    return {"data": {"repository": {"pullRequest": pull_request or _thread_pr()}}}


def _bad_pr(**overrides: Any) -> dict[str, Any]:
    return _threads_body(_thread_pr(**overrides))


def _analyses(body: Any) -> tuple[CodeScanningAnalysis, ...]:
    return normalize_code_scanning_analyses(body, queried_ref=REF)


def _alerts(body: Any) -> tuple[CodeScanningAlert, ...]:
    return normalize_code_scanning_alerts(
        body, queried_ref=REF, expected_commit_sha=MERGE_SHA, expected_tool="CodeQL"
    )


def _raises(code: str, func: Any, payload: Any) -> None:
    with pytest.raises(EvidenceNormalizationError) as excinfo:
        func(payload)
    assert excinfo.value.code == code


def _contract() -> DeliveryContract:
    return DeliveryContract(
        schema_version=3,
        ruleset_id=21644438,
        required_approving_reviews=0,
        require_review_thread_resolution=True,
        allow_changes_requested=False,
        required_status_checks=(RequiredStatusCheck("ci-ok", 15368),),
        required_code_scanning=(CodeScanningRequirement("CodeQL", "high_or_higher", "errors"),),
    )


def _evidence_for(observation: PullRequestObservation) -> MergeEvidence:
    """Evidence whose ruleset is itself normalizer output, so composition is real."""
    return MergeEvidence(
        pull_request_before=observation.identity,
        pull_request_after=observation.identity,
        is_draft=observation.is_draft,
        merge_state=observation.merge_state,
        check_runs=(CheckRunEvidence("ci-ok", 15368, observation.identity.head_sha, "success"),),
        ruleset=normalize_ruleset(_ruleset_body(rules=[_CHECK_RULE, _SCAN_RULE])),
        code_scanning=None,
        review_states=(),
        review_threads=(True,),
        incomplete_sections=frozenset(),
    )


def test_records_are_frozen_and_slotted() -> None:
    identity = PullRequestIdentity(91, HEAD_SHA, BASE_SHA, "main", MERGE_SHA)
    observation = PullRequestObservation(identity=identity, is_draft=False, merge_state="CLEAN")
    page = CheckRunPage(check_runs=(), total_count=0)
    threads = ReviewThreadPage(observation, resolved=(), has_next_page=False, end_cursor=None)
    for obj, field in (
        (observation, "is_draft"),
        (page, "total_count"),
        (threads, "has_next_page"),
    ):
        assert not hasattr(obj, "__dict__")
        with pytest.raises(AttributeError):
            setattr(obj, field, 1)


def test_error_is_stable_and_never_leaks_input(capsys: pytest.CaptureFixture[str]) -> None:
    messages = []
    for func in (normalize_pull_request, normalize_reviews, normalize_ruleset):
        with pytest.raises(EvidenceNormalizationError) as excinfo:
            func(None)
        assert excinfo.value.code == "MALFORMED_BODY"
        messages.append(str(excinfo.value))
    assert messages == ["evidence normalization failed: MALFORMED_BODY"] * 3
    poisoned = _pr_body(head={"sha": SECRET}, number="not-an-int")
    with pytest.raises(EvidenceNormalizationError) as excinfo:
        normalize_pull_request(poisoned)
    assert SECRET not in str(excinfo.value)
    assert SECRET not in repr(excinfo.value)
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_normalize_pull_request_clean_fixture_and_unknown_state() -> None:
    assert normalize_pull_request(_pr_body()) == PullRequestObservation(
        identity=PullRequestIdentity(91, HEAD_SHA, BASE_SHA, "main", MERGE_SHA),
        is_draft=False,
        merge_state="CLEAN",
    )
    # An unknown external enum is preserved verbatim for the evaluator to reject.
    assert normalize_pull_request(_pr_body(mergeable_state="has_hooks")).merge_state == "HAS_HOOKS"


def test_normalize_check_runs_page_clean_and_empty() -> None:
    assert normalize_check_runs_page(_check_runs_body()) == CheckRunPage(
        check_runs=(CheckRunEvidence("ci-ok", 15368, HEAD_SHA, "success"),), total_count=1
    )
    empty = normalize_check_runs_page(_check_runs_body(check_runs=[], total_count=0))
    assert empty == CheckRunPage(check_runs=(), total_count=0)


def test_normalize_ruleset_clean_fixture() -> None:
    assert normalize_ruleset(_ruleset_body()) == RulesetEvidence(
        ruleset_id=21644438,
        enforcement="active",
        bypass_actors=(),
        status_checks=(RequiredStatusCheck("ci-ok", 15368),),
        code_scanning=(CodeScanningRequirement("CodeQL", "high_or_higher", "errors"),),
        target="branch",
        included_refs=("refs/heads/main",),
        excluded_refs=(),
        unmodeled_rule_types=("deletion",),
    )


def test_normalize_collections_clean_and_empty() -> None:
    assert _analyses([_analysis()]) == (CodeScanningAnalysis("CodeQL", MERGE_SHA, ""),)
    assert _alerts([_alert()]) == (CodeScanningAlert("CodeQL", "open", "high", "error"),)
    assert normalize_reviews([{"state": "APPROVED"}, {"state": "NEW_STATE"}]) == (
        "APPROVED",
        "NEW_STATE",
    )
    # A successful terminal empty collection stays valid, never "missing".
    assert (_analyses([]), _alerts([]), normalize_reviews([])) == ((), (), ())


def test_normalize_review_threads_page_clean_fixture() -> None:
    assert normalize_review_threads_page(_threads_body()) == ReviewThreadPage(
        observation=PullRequestObservation(
            identity=PullRequestIdentity(91, HEAD_SHA, BASE_SHA, "main", MERGE_SHA),
            is_draft=False,
            merge_state="MERGEABLE",
        ),
        resolved=(True,),
        has_next_page=False,
        end_cursor=None,
    )


def test_check_run_app_identity_is_observed_never_substituted() -> None:
    missing_app = [{"name": "x", "head_sha": HEAD_SHA, "conclusion": None}]
    page = normalize_check_runs_page(_check_runs_body(check_runs=missing_app))
    assert page.check_runs[0].integration_id is None
    foreign = [{"name": "ci-ok", "head_sha": HEAD_SHA, "conclusion": "success", "app": {"id": 1}}]
    # The same-name foreign check keeps its observed id, not the expected 15368.
    page = normalize_check_runs_page(_check_runs_body(check_runs=foreign))
    assert page.check_runs[0] == CheckRunEvidence("ci-ok", 1, HEAD_SHA, "success")


@pytest.mark.parametrize(
    "instance",
    [{"ref": "refs/pull/1/merge", "commit_sha": MERGE_SHA}, {"ref": REF, "commit_sha": "9" * 40}],
)
def test_alert_wrong_provenance_for_expected_tool_raises(instance: dict[str, str]) -> None:
    _raises("INCONSISTENT_PROVENANCE", _alerts, [_alert(most_recent_instance=instance)])


def test_analysis_wrong_ref_raises_and_other_tool_alert_is_not_provenance_checked() -> None:
    _raises("INCONSISTENT_PROVENANCE", _analyses, [_analysis(ref="refs/pull/99/merge")])
    other = _alert(
        tool={"name": "ESLint"},
        most_recent_instance={"ref": "refs/pull/999/merge", "commit_sha": "stale"},
    )
    assert _alerts([other])[0].tool == "ESLint"  # not the contract's tool: not provenance-checked
    weird = _alert(rule={"security_severity_level": "extreme", "severity": None})
    assert _alerts([weird])[0].security_severity == "extreme"  # unknown severity preserved


def test_normalize_ruleset_absent_modeled_rules_stay_none() -> None:
    absent = normalize_ruleset(_ruleset_body(rules=[{"type": "deletion"}]))
    assert (absent.status_checks, absent.code_scanning) == (None, None)
    assert absent.unmodeled_rule_types == ("deletion",)  # unmodeled types are preserved
    no_rules = normalize_ruleset(_ruleset_body(rules=None))
    assert (no_rules.status_checks, no_rules.unmodeled_rule_types) == (None, ())


@pytest.mark.parametrize("rule", [_CHECK_RULE, _SCAN_RULE])
def test_normalize_ruleset_duplicate_modeled_rule_raises(rule: dict[str, Any]) -> None:
    _raises("DUPLICATE_MODELED_RULE", normalize_ruleset, _ruleset_body(rules=[rule, rule]))


def test_normalize_ruleset_bypass_missing_differs_from_empty() -> None:
    missing = _ruleset_body()
    del missing["bypass_actors"]
    assert normalize_ruleset(missing).bypass_actors is None
    assert normalize_ruleset(_ruleset_body(bypass_actors=[])).bypass_actors == ()
    present = _ruleset_body(bypass_actors=[{"actor_type": "Team", "actor_id": 42}])
    assert normalize_ruleset(present).bypass_actors == ("Team:42",)


def test_normalize_ruleset_scope_missing_conditions_is_none() -> None:
    body = _ruleset_body()
    del body["conditions"]
    del body["target"]
    scope = normalize_ruleset(body)
    assert (scope.target, scope.included_refs, scope.excluded_refs) == (None, None, None)
    # A ref_name present but without include/exclude lists is still "not collected".
    partial = normalize_ruleset(_ruleset_body(conditions={"ref_name": {}}))
    assert (partial.included_refs, partial.excluded_refs) == (None, None)


def test_check_runs_page_total_count_consistency() -> None:
    _raises("INCONSISTENT_TOTAL_COUNT", normalize_check_runs_page, _check_runs_body(total_count=0))
    # A page may legitimately claim more total items than it itself carries.
    assert normalize_check_runs_page(_check_runs_body(total_count=99)).total_count == 99


def test_review_threads_page_exposes_full_observation_like_rest() -> None:
    """Both REST and GraphQL parsers must yield the identical record type."""
    rest = normalize_pull_request(_pr_body())
    page = normalize_review_threads_page(_threads_body())
    assert type(page.observation) is type(rest) is PullRequestObservation
    assert page.observation.identity == rest.identity


def test_review_threads_page_null_merge_commit_and_empty_threads_are_valid() -> None:
    null_merge = _thread_pr(potentialMergeCommit=None, reviewThreads=_threads(nodes=[]))
    page = normalize_review_threads_page(_threads_body(null_merge))
    assert page.observation.identity.potential_merge_sha == ""
    assert page.resolved == ()


def test_review_threads_page_cursor_rules() -> None:
    more = _threads(pageInfo={"hasNextPage": True, "endCursor": "cursor-1"})
    page = normalize_review_threads_page(_threads_body(_thread_pr(reviewThreads=more)))
    assert (page.has_next_page, page.end_cursor) == (True, "cursor-1")
    # "More pages" without a cursor cannot be paginated, so it fails closed.
    broken = _threads(pageInfo={"hasNextPage": True, "endCursor": None})
    _raises("MALFORMED_BODY", normalize_review_threads_page, _bad_pr(reviewThreads=broken))


def test_review_threads_page_graphql_errors_with_data_raises() -> None:
    body = _threads_body()
    body["errors"] = [{"message": "boom"}]
    _raises("GRAPHQL_ERROR", normalize_review_threads_page, body)


# --- Every malformed shape fails closed ---------------------------------------


@pytest.mark.parametrize(
    ("call", "payload"),
    [
        # Outer bodies of the wrong type are never a clean empty collection.
        (normalize_pull_request, "nope"),
        (normalize_pull_request, []),
        (normalize_check_runs_page, "nope"),
        (normalize_ruleset, ["not", "a", "dict"]),
        (_analyses, {}),
        (_alerts, "not-a-list"),
        (normalize_reviews, "not-a-list"),
        (normalize_review_threads_page, "not-a-dict"),
        (normalize_review_threads_page, {"data": {"repository": "not-a-dict"}}),
        (normalize_review_threads_page, {"data": {"repository": {"pullRequest": "x"}}}),
        (normalize_pull_request, _pr_body(number="91")),
        (normalize_pull_request, _pr_body(number=True)),
        (normalize_pull_request, _pr_body(head={"sha": ""})),
        (normalize_pull_request, _pr_body(base={"sha": BASE_SHA})),
        (normalize_pull_request, _pr_body(merge_commit_sha=12345)),
        (normalize_pull_request, _pr_body(draft="no")),
        (normalize_pull_request, _pr_body(mergeable_state="")),
        # A blank-but-truthy enum must not degrade into an empty merge state.
        (normalize_pull_request, _pr_body(mergeable_state="   ")),
        (normalize_check_runs_page, _check_runs_body(check_runs="not-a-list")),
        (normalize_check_runs_page, _check_runs_body(check_runs=[{"head_sha": HEAD_SHA}])),
        (normalize_check_runs_page, _check_runs_body(check_runs=[{"name": "x", "conclusion": 5}])),
        (normalize_check_runs_page, _check_runs_body(total_count="1")),
        # A present-but-malformed app, or a bool id, is malformed -- never "no app".
        (normalize_check_runs_page, _check_runs_body(check_runs=[_RUN_BAD_APP])),
        (normalize_check_runs_page, _check_runs_body(check_runs=[_RUN_BOOL_ID])),
        (normalize_ruleset, _ruleset_body(id="21644438")),
        (normalize_ruleset, _ruleset_body(enforcement="")),
        (normalize_ruleset, _ruleset_body(rules="not-a-list")),
        (normalize_ruleset, _ruleset_body(rules=[{"type": ""}])),
        (normalize_ruleset, _ruleset_body(rules=[_rule("required_status_checks")])),
        (normalize_ruleset, _ruleset_body(rules=[_rule("code_scanning", code_scanning_tools="x")])),
        (normalize_ruleset, _ruleset_body(rules=[_BOOL_ID_RULE])),
        (normalize_ruleset, _ruleset_body(bypass_actors="not-a-list")),
        (normalize_ruleset, _ruleset_body(bypass_actors=[{"actor_type": "Team"}])),
        (normalize_ruleset, _ruleset_body(bypass_actors=[{"actor_type": "T", "actor_id": "42"}])),
        # Present-but-malformed ref scope must raise, not look "not collected".
        (normalize_ruleset, _ruleset_body(conditions={"ref_name": {"include": [1]}})),
        (normalize_ruleset, _ruleset_body(conditions={"ref_name": {"include": "not-a-list"}})),
        (normalize_ruleset, _ruleset_body(conditions="not-a-dict")),
        (normalize_ruleset, _ruleset_body(conditions={"ref_name": "not-a-dict"})),
        (normalize_ruleset, _ruleset_body(target="   ")),
        (_analyses, [_analysis(tool={})]),
        (_analyses, [_analysis(commit_sha="")]),
        (_analyses, [_analysis(error=None)]),
        (_alerts, [_alert(tool={})]),
        (_alerts, [_alert(state="")]),
        (_alerts, [_alert(rule="not-a-dict")]),
        (_alerts, [_alert(rule={"security_severity_level": 5})]),
        (normalize_reviews, [{"state": ""}]),
        (normalize_reviews, [{}]),
        (normalize_review_threads_page, _bad_pr(number="91")),
        (normalize_review_threads_page, _bad_pr(headRefOid="")),
        (normalize_review_threads_page, _bad_pr(isDraft=None)),
        (normalize_review_threads_page, _bad_pr(mergeable="")),
        (normalize_review_threads_page, _bad_pr(potentialMergeCommit="not-a-dict")),
        (normalize_review_threads_page, _bad_pr(potentialMergeCommit={"oid": 5})),
        (normalize_review_threads_page, _bad_pr(reviewThreads="not-a-dict")),
        (normalize_review_threads_page, _bad_pr(reviewThreads=_threads(pageInfo="x"))),
        (normalize_review_threads_page, _bad_pr(reviewThreads=_threads(nodes="x"))),
        (normalize_review_threads_page, _bad_pr(reviewThreads=_threads(nodes=[{"isResolved": 1}]))),
    ],
)
def test_malformed_input_fails_closed(call: Any, payload: Any) -> None:
    with pytest.raises(EvidenceNormalizationError):
        call(payload)


def test_module_has_no_transport_or_io_dependency() -> None:
    tree = ast.parse(Path(norm.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    banned = {"urllib", "requests", "httpx", "os", "subprocess", "argparse"}
    banned.add("blackbread.governance.github_merge_transport")
    assert imported.isdisjoint(banned)
    assert not hasattr(norm, "main")


def test_normalized_evidence_composes_with_evaluator() -> None:
    observation = normalize_pull_request(_pr_body())
    page = normalize_review_threads_page(_threads_body())
    evidence = replace(
        _evidence_for(observation),
        review_states=normalize_reviews([{"state": "APPROVED"}]),
        review_threads=page.resolved,
    )
    decision = evaluate_merge_readiness(_contract(), evidence, HEAD_SHA)
    # code_scanning is left None deliberately: this proves composition, not readiness.
    assert any(b.code == "MISSING_EVIDENCE" for b in decision.blockers)
    assert not any(
        b.code
        in (
            "PR_IDENTITY_DRIFT",
            "RULESET_STATUS_CHECK_DRIFT",
            "RULESET_CODE_SCANNING_DRIFT",
            "UNRESOLVED_REVIEW_THREADS",
        )
        for b in decision.blockers
    )


def test_null_merge_candidate_blocks_only_via_the_evaluator() -> None:
    observation = normalize_pull_request(_pr_body(merge_commit_sha=None))
    assert observation.identity.potential_merge_sha == ""  # representable, not dropped
    decision = evaluate_merge_readiness(_contract(), _evidence_for(observation), HEAD_SHA)
    assert not decision.ready
    assert any(b.code == "MISSING_MERGE_CANDIDATE" for b in decision.blockers)
