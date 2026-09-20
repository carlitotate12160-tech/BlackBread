"""Proofs for fail-closed live GitHub merge-evidence collection."""

from __future__ import annotations

import urllib.parse
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from blackbread.governance import github_merge_evidence as collector_module
from blackbread.governance.github_merge_evidence import (
    EvidenceCollectionError,
    GitHubMergeEvidenceCollector,
)
from blackbread.governance.github_merge_transport import TransportError, TransportResult
from blackbread.governance.merge_readiness import (
    CodeScanningRequirement,
    DeliveryContract,
    RequiredStatusCheck,
    evaluate_merge_readiness,
)

HEAD_SHA = "1" * 40
BASE_SHA = "b" * 40
MERGE_SHA = "2" * 40
OTHER_SHA = "3" * 40
REF = "refs/pull/91/head"
_MARKERS = MappingProxyType(
    {"checks": "check_runs", "analyses": "code_scanning", "alerts": "code_scanning"}
)


def _contract(**overrides: object) -> DeliveryContract:
    contract = DeliveryContract(
        schema_version=3,
        ruleset_id=21644438,
        required_approving_reviews=0,
        require_review_thread_resolution=True,
        allow_changes_requested=False,
        require_branch_up_to_date=True,
        required_status_checks=(
            RequiredStatusCheck("ci-ok", 15368),
            RequiredStatusCheck("GitGuardian Security Checks", 46505),
        ),
        required_code_scanning=(CodeScanningRequirement("CodeQL", "high_or_higher", "errors"),),
    )
    return replace(contract, **overrides)


def _pr(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "number": 91,
        "head": {"sha": HEAD_SHA},
        "base": {"sha": BASE_SHA, "ref": "main"},
        "merge_commit_sha": MERGE_SHA,
        "draft": False,
        "mergeable_state": "clean",
    }
    return {**body, **overrides}


def _run(name: str = "ci-ok", app_id: int | None = 15368) -> dict[str, Any]:
    app = None if app_id is None else {"id": app_id}
    return {"name": name, "head_sha": HEAD_SHA, "conclusion": "success", "app": app}


def _checks(runs: list[dict[str, Any]] | None = None, total: int | None = None) -> dict[str, Any]:
    items = runs if runs is not None else [_run(), _run("GitGuardian Security Checks", 46505)]
    return {"total_count": len(items) if total is None else total, "check_runs": items}


def _ruleset() -> dict[str, Any]:
    return {
        "id": 21644438,
        "enforcement": "active",
        "bypass_actors": [],
        "target": "branch",
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "ci-ok", "integration_id": 15368},
                        {"context": "GitGuardian Security Checks", "integration_id": 46505},
                    ],
                    "strict_required_status_checks_policy": True,
                },
            },
            {
                "type": "code_scanning",
                "parameters": {
                    "code_scanning_tools": [
                        {
                            "tool": "CodeQL",
                            "security_alerts_threshold": "high_or_higher",
                            "alerts_threshold": "errors",
                        }
                    ]
                },
            },
        ],
    }


def _analysis(**overrides: Any) -> dict[str, Any]:
    item = {"tool": {"name": "CodeQL"}, "commit_sha": HEAD_SHA, "error": "", "ref": REF}
    return {**item, **overrides}


def _alert(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "tool": {"name": "CodeQL"},
        "state": "open",
        "rule": {"security_severity_level": "low", "severity": "note"},
        "most_recent_instance": {"ref": REF, "commit_sha": HEAD_SHA},
    }
    return {**item, **overrides}


def _thread_body(
    *,
    cursor: str | None = None,
    more: bool = False,
    resolved: list[bool] | None = None,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pr = {
        "number": 91,
        "headRefOid": HEAD_SHA,
        "baseRefOid": BASE_SHA,
        "baseRefName": "main",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "potentialMergeCommit": {"oid": MERGE_SHA},
        "reviewThreads": {
            "nodes": [{"isResolved": value} for value in (resolved or [])],
            "pageInfo": {"hasNextPage": more, "endCursor": cursor},
        },
    }
    pr.update(identity or {})
    return {"data": {"repository": {"pullRequest": pr}}}


def _result(body: Any, next_url: str | None = None) -> TransportResult:
    return TransportResult(status=200, body=body, next_url=next_url)


def _next(path: str, params: dict[str, str], page: int = 2) -> str:
    query = urllib.parse.urlencode({**params, "page": str(page)})
    return f"https://api.github.com{path}?{query}"


class _FakeTransport:
    def __init__(
        self,
        rest_pages: dict[str, list[TransportResult | Exception]] | None = None,
        thread_pages: list[TransportResult | Exception] | None = None,
        pr_bodies: list[dict[str, Any]] | None = None,
    ) -> None:
        self.rest_pages = rest_pages or {}
        self.thread_pages = thread_pages or [_result(_thread_body())]
        self.pr_bodies = pr_bodies or [_pr(), _pr()]
        self.rest_calls: list[tuple[str, dict[str, str] | None]] = []
        self.graphql_calls: list[tuple[str, dict[str, Any]]] = []
        self._counts: dict[str, int] = {}

    def rest_get(self, path_or_url: str, params: dict[str, str] | None = None) -> TransportResult:
        self.rest_calls.append((path_or_url, params))
        section = self._section(path_or_url)
        index = self._counts.get(section, 0)
        self._counts[section] = index + 1
        if section in self.rest_pages:
            return self._take(self.rest_pages[section], index)
        defaults = {
            "pr": lambda: _result(self.pr_bodies[min(index, len(self.pr_bodies) - 1)]),
            "ruleset": lambda: _result(_ruleset()),
            "checks": lambda: _result(_checks()),
            "analyses": lambda: _result([_analysis()]),
            "alerts": lambda: _result([]),
            "reviews": lambda: _result([]),
        }
        return defaults[section]()

    def graphql_query(
        self, document: str, variables: dict[str, Any] | None = None
    ) -> TransportResult:
        values = dict(variables or {})
        self.graphql_calls.append((document, values))
        return self._take(self.thread_pages, len(self.graphql_calls) - 1)

    @staticmethod
    def _take(items: list[TransportResult | Exception], index: int) -> TransportResult:
        item = items[index]
        if isinstance(item, Exception):
            raise item
        return item

    @staticmethod
    def _section(target: str) -> str:
        path = urllib.parse.urlsplit(target).path
        if path.endswith("/reviews"):
            return "reviews"
        if path.endswith("/check-runs"):
            return "checks"
        if path.endswith("/code-scanning/analyses"):
            return "analyses"
        if path.endswith("/code-scanning/alerts"):
            return "alerts"
        if "/rulesets/" in path:
            return "ruleset"
        return "pr"


def _collect(transport: _FakeTransport | None = None) -> tuple[_FakeTransport, Any]:
    fake = transport or _FakeTransport()
    evidence = GitHubMergeEvidenceCollector(fake, "owner/repo").collect(91, _contract())
    return fake, evidence


def _section_path(section: str) -> tuple[str, dict[str, str]]:
    paths = {
        "checks": (f"/repos/owner/repo/commits/{HEAD_SHA}/check-runs", {"per_page": "100"}),
        "analyses": (
            "/repos/owner/repo/code-scanning/analyses",
            {"ref": REF, "tool_name": "CodeQL", "per_page": "100"},
        ),
        "alerts": (
            "/repos/owner/repo/code-scanning/alerts",
            {"ref": REF, "tool_name": "CodeQL", "state": "open", "per_page": "100"},
        ),
        "reviews": ("/repos/owner/repo/pulls/91/reviews", {"per_page": "100"}),
    }
    return paths[section]


def test_complete_evidence_composes_to_ready_and_uses_exact_routes() -> None:
    fake, evidence = _collect()
    assert evaluate_merge_readiness(_contract(), evidence, HEAD_SHA).ready
    assert evidence.code_scanning and evidence.code_scanning.alerts == ()
    assert (evidence.review_states, evidence.review_threads) == ((), ())
    assert fake.rest_calls[0] == ("/repos/owner/repo/pulls/91", None)
    assert fake.rest_calls[-1] == ("/repos/owner/repo/pulls/91", None)
    assert ("/repos/owner/repo/rulesets/21644438", None) in fake.rest_calls
    assert fake.graphql_calls[0][1] == {
        "owner": "owner",
        "name": "repo",
        "number": 91,
        "after": None,
    }


def test_valid_multi_page_results_concatenate_exactly_once() -> None:
    pages: dict[str, list[TransportResult | Exception]] = {}
    for section in ("checks", "analyses", "alerts", "reviews"):
        path, params = _section_path(section)
        bodies = {
            "checks": (
                _checks([_run()], 2),
                _checks([_run("GitGuardian Security Checks", 46505)], 2),
            ),
            "analyses": ([_analysis()], [_analysis()]),
            "alerts": ([_alert()], [_alert()]),
            "reviews": ([{"state": "APPROVED"}], [{"state": "COMMENTED"}]),
        }[section]
        pages[section] = [_result(bodies[0], _next(path, params)), _result(bodies[1])]
    threads = [
        _result(_thread_body(cursor="c1", more=True, resolved=[True])),
        _result(_thread_body(resolved=[False])),
    ]
    _, evidence = _collect(_FakeTransport(pages, threads))
    assert evidence.check_runs is not None and len(evidence.check_runs) == 2
    assert evidence.code_scanning and len(evidence.code_scanning.analyses or ()) == 2
    assert len(evidence.code_scanning.alerts or ()) == 2
    assert evidence.review_states == ("APPROVED", "COMMENTED")
    assert evidence.review_threads == (True, False)


@pytest.mark.parametrize("section", ["checks", "analyses", "alerts", "reviews"])
def test_failed_non_first_rest_page_discards_complete_section(section: str) -> None:
    path, params = _section_path(section)
    first_body = {
        "checks": _checks([_run()], 2),
        "analyses": [_analysis()],
        "alerts": [_alert()],
        "reviews": [{"state": "APPROVED"}],
    }[section]
    fake = _FakeTransport(
        {
            section: [
                _result(first_body, _next(path, params)),
                TransportError("network request failed"),
            ]
        }
    )
    fake, evidence = _collect(fake)
    marker = _MARKERS.get(section, section)
    field = {"checks": "check_runs", "reviews": "review_states"}.get(section, "code_scanning")
    assert getattr(evidence, field) is None
    assert marker in evidence.incomplete_sections


def test_failed_non_first_thread_page_discards_threads() -> None:
    pages = [
        _result(_thread_body(cursor="c1", more=True, resolved=[True])),
        TransportError("network request failed"),
    ]
    _, evidence = _collect(_FakeTransport(thread_pages=pages))
    assert evidence.review_threads is None
    assert "review_threads" in evidence.incomplete_sections


@pytest.mark.parametrize(
    ("section", "mutation"),
    [
        ("checks", {"path": "/repos/owner/repo/commits/stale/check-runs"}),
        ("analyses", {"ref": "refs/pull/92/merge"}),
        ("alerts", {"tool_name": "Other"}),
        ("alerts", {"state": "dismissed"}),
        ("reviews", {"unexpected": "1"}),
    ],
)
def test_rest_continuations_reject_semantic_query_mutation(
    section: str, mutation: dict[str, str]
) -> None:
    path, params = _section_path(section)
    changed_path = mutation.get("path", path)
    changed_params = {**params, **{k: v for k, v in mutation.items() if k != "path"}}
    body = _checks([], 0) if section == "checks" else []
    fake = _FakeTransport({section: [_result(body, _next(changed_path, changed_params))]})
    _, evidence = _collect(fake)
    marker = _MARKERS.get(section, section)
    assert marker in evidence.incomplete_sections


def test_canonical_repository_next_link_rebinds_to_original_path() -> None:
    path, params = _section_path("reviews")
    canonical = "/repositories/1348286952/pulls/91/reviews"
    pages = {"reviews": [_result([], _next(canonical, params)), _result([])]}
    fake, evidence = _collect(_FakeTransport(pages))
    review_calls = [
        call for call in fake.rest_calls if _FakeTransport._section(call[0]) == "reviews"
    ]
    assert evidence.review_states == ()
    assert review_calls == [(path, params), (path, {**params, "page": "2"})]


@pytest.mark.parametrize(
    "canonical",
    [
        "/repositories/not-decimal/pulls/91/reviews",
        "/repositories/0/pulls/91/reviews",
        "/repositories/1348286952/pulls/92/reviews",
    ],
)
def test_invalid_canonical_repository_path_fails_closed(canonical: str) -> None:
    path, params = _section_path("reviews")
    pages = {"reviews": [_result([], _next(canonical, params)), _result([])]}
    fake, evidence = _collect(_FakeTransport(pages))
    review_calls = [
        call for call in fake.rest_calls if _FakeTransport._section(call[0]) == "reviews"
    ]
    assert evidence.review_states is None
    assert "reviews" in evidence.incomplete_sections
    assert review_calls == [(path, params)]


def test_rest_next_link_cycle_and_page_limit_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    path, params = _section_path("reviews")
    page_two = _next(path, params)
    cyclic = _FakeTransport({"reviews": [_result([], page_two), _result([], page_two)]})
    _, cycle_evidence = _collect(cyclic)
    assert cycle_evidence.review_states is None
    bad_totals = _FakeTransport({"checks": [_result(_checks([_run()], 2))]})
    _, total_evidence = _collect(bad_totals)
    assert total_evidence.check_runs is None
    monkeypatch.setattr(collector_module, "_MAX_PAGES", 1)
    limited = _FakeTransport({"reviews": [_result([], page_two)]})
    _, limit_evidence = _collect(limited)
    assert limit_evidence.review_states is None


@pytest.mark.parametrize("cursor", [None, "repeat"])
def test_missing_or_repeated_thread_cursor_fails_closed(cursor: str | None) -> None:
    first = _result(_thread_body(cursor=cursor, more=True))
    pages = [first]
    if cursor is not None:
        pages.append(_result(_thread_body(cursor=cursor, more=True)))
    _, evidence = _collect(_FakeTransport(thread_pages=pages))
    assert evidence.review_threads is None
    assert "review_threads" in evidence.incomplete_sections


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("head", {"sha": OTHER_SHA}),
        ("base", {"sha": OTHER_SHA, "ref": "main"}),
        ("base", {"sha": BASE_SHA, "ref": "release"}),
        ("merge_commit_sha", OTHER_SHA),
    ],
)
def test_before_after_pr_drift_is_preserved(field: str, value: Any) -> None:
    after = _pr(**{field: value})
    _, evidence = _collect(_FakeTransport(pr_bodies=[_pr(), after]))
    assert evidence.pull_request_before != evidence.pull_request_after
    decision = evaluate_merge_readiness(_contract(), evidence, HEAD_SHA)
    assert "PR_IDENTITY_DRIFT" in {blocker.code for blocker in decision.blockers}


def test_intermediate_thread_identity_aba_marks_section_incomplete() -> None:
    pages = [
        _result(_thread_body(cursor="c1", more=True)),
        _result(_thread_body(cursor="c2", more=True, identity={"headRefOid": OTHER_SHA})),
        _result(_thread_body()),
    ]
    fake, evidence = _collect(_FakeTransport(thread_pages=pages))
    assert evidence.review_threads is None
    assert "review_threads" in evidence.incomplete_sections
    assert len(fake.graphql_calls) == 2


@pytest.mark.parametrize("app_id", [None, 99999])
def test_observed_check_app_ids_are_never_substituted(app_id: int | None) -> None:
    runs = [_run(app_id=app_id), _run("GitGuardian Security Checks", 46505)]
    fake = _FakeTransport({"checks": [_result(_checks(runs))]})
    _, evidence = _collect(fake)
    assert evidence.check_runs and evidence.check_runs[0].integration_id == app_id
    assert not evaluate_merge_readiness(_contract(), evidence, HEAD_SHA).ready


@pytest.mark.parametrize(
    ("section", "body"),
    [
        ("analyses", [_analysis(tool={})]),
        ("analyses", [_analysis(tool={"name": "Other"})]),
        ("analyses", [_analysis(ref="refs/pull/91/merge")]),
        ("alerts", [_alert(tool={"name": "Other"})]),
        ("alerts", [_alert(most_recent_instance={"ref": REF, "commit_sha": OTHER_SHA})]),
        (
            "alerts",
            [_alert(most_recent_instance={"ref": "refs/pull/91/merge", "commit_sha": HEAD_SHA})],
        ),
    ],
)
def test_wrong_or_missing_codeql_provenance_discards_scanning(section: str, body: Any) -> None:
    fake = _FakeTransport({section: [_result(body)]})
    _, evidence = _collect(fake)
    assert evidence.code_scanning is None
    assert "code_scanning" in evidence.incomplete_sections


def test_historical_analyses_on_head_ref_are_collected_not_rejected() -> None:
    fake = _FakeTransport({"analyses": [_result([_analysis(), _analysis(commit_sha=OTHER_SHA)])]})
    _, evidence = _collect(fake)
    scanning = evidence.code_scanning
    assert scanning is not None
    assert "code_scanning" not in evidence.incomplete_sections
    assert {a.commit_sha for a in scanning.analyses or ()} == {HEAD_SHA, OTHER_SHA}
    assert evaluate_merge_readiness(_contract(), evidence, HEAD_SHA).ready


@pytest.mark.parametrize("repository", ["owner", "owner/repo/extra", "owner/repo?x=1", "../repo"])
def test_invalid_repository_is_sanitized_and_causes_zero_io(repository: str) -> None:
    fake = _FakeTransport()
    with pytest.raises(EvidenceCollectionError) as excinfo:
        GitHubMergeEvidenceCollector(fake, repository)
    assert repository not in str(excinfo.value)
    assert fake.rest_calls == [] and fake.graphql_calls == []


@pytest.mark.parametrize(
    ("number", "ruleset_id"), [(0, 21644438), (-1, 21644438), (True, 21644438), (91, 0)]
)
def test_invalid_identifiers_cause_zero_io(number: int, ruleset_id: int) -> None:
    fake = _FakeTransport()
    collector = GitHubMergeEvidenceCollector(fake, "owner/repo")
    with pytest.raises(EvidenceCollectionError):
        collector.collect(number, _contract(ruleset_id=ruleset_id))
    assert fake.rest_calls == [] and fake.graphql_calls == []


def test_collector_is_intentionally_unwired_and_has_no_execution_authority() -> None:
    source = Path(collector_module.__file__).read_text(encoding="utf-8")
    assert "evaluate_merge_readiness" not in source
    assert not hasattr(collector_module, "main")
    assert all(token not in source for token in ("getenv", "environ", "UrllibGitHubReadTransport"))
