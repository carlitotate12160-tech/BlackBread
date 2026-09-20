"""Fail-closed orchestration of live GitHub merge-readiness evidence."""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable, Mapping
from typing import Any, NoReturn

from blackbread.governance import github_merge_normalization as norm
from blackbread.governance import github_merge_transport as gh
from blackbread.governance.merge_readiness import (
    CheckRunEvidence,
    CodeScanningAlert,
    CodeScanningAnalysis,
    CodeScanningEvidence,
    DeliveryContract,
    MergeEvidence,
    PullRequestIdentity,
    RulesetEvidence,
)

_PAGE_SIZE = "100"
_MAX_PAGES = 100
_OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_CANONICAL_REPOSITORY_PATH_RE = re.compile(
    r"/repositories/(?P<repository_id>[0-9]+)(?P<suffix>/.+)"
)
_REVIEW_THREADS_QUERY = """query PullRequestReviewThreads(
  $owner: String!, $name: String!, $number: Int!, $after: String
) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number headRefOid baseRefOid baseRefName isDraft mergeable
      potentialMergeCommit { oid }
      reviewThreads(first: 100, after: $after) {
        nodes { isResolved }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


class EvidenceCollectionError(Exception):
    """Sanitized invalid-input or evidence-collection failure."""

    def __init__(self, code: str) -> None:
        super().__init__(f"merge evidence collection failed: {code}")
        self.code = code


def _fail(code: str) -> NoReturn:
    raise EvidenceCollectionError(code)


def _repository_parts(repository: str) -> tuple[str, str]:
    if not isinstance(repository, str) or repository.count("/") != 1:
        _fail("INVALID_REPOSITORY")
    owner, name = repository.split("/")
    valid = _OWNER_RE.fullmatch(owner) and _REPOSITORY_RE.fullmatch(name)
    if not valid or name in {".", ".."}:
        _fail("INVALID_REPOSITORY")
    return owner, name


def _attempt[T](action: Callable[[], T]) -> tuple[T | None, bool]:
    try:
        return action(), False
    except (
        EvidenceCollectionError,
        norm.EvidenceNormalizationError,
        gh.TransportError,
    ):
        return None, True


def _pagination_path_matches(candidate: str, bound_path: str) -> bool:
    if candidate == bound_path:
        return True
    bound_parts = bound_path.split("/", 4)
    if bound_parts[:2] != ["", "repos"] or not bound_parts[4:]:
        return False
    match = _CANONICAL_REPOSITORY_PATH_RE.fullmatch(candidate)
    if match is None or not match.group("repository_id").lstrip("0"):
        return False
    return match.group("suffix") == f"/{bound_parts[4]}"


def _next_page_number(
    next_url: str,
    *,
    path: str,
    params: Mapping[str, str],
    current_page: int,
) -> int:
    try:
        parsed = urllib.parse.urlsplit(next_url)
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        port = parsed.port
    except (TypeError, ValueError):
        _fail("PAGINATION_SEMANTICS")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.github.com"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not _pagination_path_matches(parsed.path, path)
    ):
        _fail("PAGINATION_SEMANTICS")
    if len(pairs) != len({key for key, _ in pairs}):
        _fail("PAGINATION_SEMANTICS")
    actual = dict(pairs)
    expected = {**params, "page": str(current_page + 1)}
    if actual != expected:
        _fail("PAGINATION_SEMANTICS")
    return current_page + 1


def _rest_bodies(
    transport: gh.GitHubReadTransport,
    path: str,
    params: Mapping[str, str],
) -> tuple[Any, ...]:
    bodies: list[Any] = []
    request_target = path
    request_params: Mapping[str, str] | None = params
    current_page = 1
    seen: set[str] = set()
    for _ in range(_MAX_PAGES):
        result = transport.rest_get(request_target, request_params)
        bodies.append(result.body)
        if result.next_url is None:
            return tuple(bodies)
        if result.next_url in seen:
            _fail("PAGINATION_CYCLE")
        current_page = _next_page_number(
            result.next_url, path=path, params=params, current_page=current_page
        )
        seen.add(result.next_url)
        # Treat the Link as cursor evidence only; retain the collector-bound repository path.
        request_target = path
        request_params = {**params, "page": str(current_page)}
    _fail("PAGINATION_LIMIT")


def _single_result(result: gh.TransportResult) -> Any:
    if result.next_url is not None:
        _fail("UNEXPECTED_PAGINATION")
    return result.body


class GitHubMergeEvidenceCollector:
    """Collect one PR's evidence without making a readiness decision."""

    def __init__(self, transport: gh.GitHubReadTransport, repository: str) -> None:
        self._transport = transport
        self._owner, self._name = _repository_parts(repository)
        self._repository_path = f"/repos/{self._owner}/{self._name}"

    def collect(self, pull_request_number: int, contract: DeliveryContract) -> MergeEvidence:
        self._validate_identifiers(pull_request_number, contract)
        before, _ = _attempt(lambda: self._pull_request(pull_request_number))
        ruleset, _ = _attempt(lambda: self._ruleset(contract.ruleset_id))
        checks, checks_failed = self._dependent(
            before, lambda observed: self._check_runs(observed.identity.head_sha)
        )
        scanning, scanning_failed = self._dependent(
            before, lambda observed: self._code_scanning(observed.identity, contract)
        )
        reviews, reviews_failed = _attempt(lambda: self._reviews(pull_request_number))
        threads, threads_failed = self._dependent(
            before, lambda observed: self._review_threads(observed.identity)
        )
        after, _ = _attempt(lambda: self._pull_request(pull_request_number))
        incomplete = self._incomplete_sections(
            checks_failed, scanning_failed, reviews_failed, threads_failed
        )
        return MergeEvidence(
            pull_request_before=before.identity if before is not None else None,
            pull_request_after=after.identity if after is not None else None,
            is_draft=after.is_draft if after is not None else None,
            merge_state=after.merge_state if after is not None else None,
            check_runs=checks,
            ruleset=ruleset,
            code_scanning=scanning,
            review_states=reviews,
            review_threads=threads,
            incomplete_sections=incomplete,
        )

    @staticmethod
    def _validate_identifiers(pull_request_number: int, contract: DeliveryContract) -> None:
        if (
            not isinstance(pull_request_number, int)
            or isinstance(pull_request_number, bool)
            or pull_request_number <= 0
        ):
            _fail("INVALID_PULL_REQUEST_NUMBER")
        if (
            not isinstance(contract.ruleset_id, int)
            or isinstance(contract.ruleset_id, bool)
            or contract.ruleset_id <= 0
        ):
            _fail("INVALID_RULESET_ID")

    @staticmethod
    def _dependent[T](
        observation: norm.PullRequestObservation | None,
        action: Callable[[norm.PullRequestObservation], T],
    ) -> tuple[T | None, bool]:
        if observation is None:
            return None, True
        return _attempt(lambda: action(observation))

    @staticmethod
    def _incomplete_sections(
        checks: bool, scanning: bool, reviews: bool, threads: bool
    ) -> frozenset[str]:
        pairs = (
            ("check_runs", checks),
            ("code_scanning", scanning),
            ("reviews", reviews),
            ("review_threads", threads),
        )
        return frozenset(name for name, failed in pairs if failed)

    def _pull_request(self, number: int) -> norm.PullRequestObservation:
        path = f"{self._repository_path}/pulls/{number}"
        return norm.normalize_pull_request(_single_result(self._transport.rest_get(path)))

    def _ruleset(self, ruleset_id: int) -> RulesetEvidence:
        path = f"{self._repository_path}/rulesets/{ruleset_id}"
        return norm.normalize_ruleset(_single_result(self._transport.rest_get(path)))

    def _check_runs(self, head_sha: str) -> tuple[CheckRunEvidence, ...]:
        path = f"{self._repository_path}/commits/{head_sha}/check-runs"
        pages = [
            norm.normalize_check_runs_page(body)
            for body in _rest_bodies(self._transport, path, {"per_page": _PAGE_SIZE})
        ]
        totals = {page.total_count for page in pages}
        runs = tuple(run for page in pages for run in page.check_runs)
        if len(totals) != 1 or len(runs) != pages[0].total_count:
            _fail("INCONSISTENT_TOTAL_COUNT")
        return runs

    def _code_scanning(
        self, identity: PullRequestIdentity, contract: DeliveryContract
    ) -> CodeScanningEvidence:
        if not identity.potential_merge_sha:
            _fail("MISSING_MERGE_CANDIDATE")
        queried_ref = f"refs/pull/{identity.number}/merge"
        analyses: list[CodeScanningAnalysis] = []
        alerts: list[CodeScanningAlert] = []
        tools = tuple(dict.fromkeys(item.tool for item in contract.required_code_scanning))
        for tool in tools:
            analyses.extend(self._analyses(tool, queried_ref, identity.potential_merge_sha))
            alerts.extend(self._alerts(tool, queried_ref, identity.potential_merge_sha))
        return CodeScanningEvidence(tuple(analyses), tuple(alerts), queried_ref)

    def _analyses(
        self, tool: str, queried_ref: str, merge_sha: str
    ) -> tuple[CodeScanningAnalysis, ...]:
        path = f"{self._repository_path}/code-scanning/analyses"
        params = {"ref": queried_ref, "tool_name": tool, "per_page": _PAGE_SIZE}
        items = tuple(
            item
            for body in _rest_bodies(self._transport, path, params)
            for item in norm.normalize_code_scanning_analyses(body, queried_ref=queried_ref)
        )
        if any(item.tool != tool or item.commit_sha != merge_sha for item in items):
            _fail("INCONSISTENT_PROVENANCE")
        return items

    def _alerts(self, tool: str, queried_ref: str, merge_sha: str) -> tuple[CodeScanningAlert, ...]:
        path = f"{self._repository_path}/code-scanning/alerts"
        params = {
            "ref": queried_ref,
            "tool_name": tool,
            "state": "open",
            "per_page": _PAGE_SIZE,
        }
        items = tuple(
            item
            for body in _rest_bodies(self._transport, path, params)
            for item in norm.normalize_code_scanning_alerts(
                body,
                queried_ref=queried_ref,
                expected_commit_sha=merge_sha,
                expected_tool=tool,
            )
        )
        if any(item.tool != tool or item.state != "open" for item in items):
            _fail("INCONSISTENT_PROVENANCE")
        return items

    def _reviews(self, number: int) -> tuple[str, ...]:
        path = f"{self._repository_path}/pulls/{number}/reviews"
        return tuple(
            state
            for body in _rest_bodies(self._transport, path, {"per_page": _PAGE_SIZE})
            for state in norm.normalize_reviews(body)
        )

    def _review_threads(self, initial: PullRequestIdentity) -> tuple[bool, ...]:
        resolved: list[bool] = []
        after: str | None = None
        seen: set[str] = set()
        for _ in range(_MAX_PAGES):
            result = self._transport.graphql_query(
                _REVIEW_THREADS_QUERY,
                {
                    "owner": self._owner,
                    "name": self._name,
                    "number": initial.number,
                    "after": after,
                },
            )
            if result.next_url is not None:
                _fail("PAGINATION_SEMANTICS")
            page = norm.normalize_review_threads_page(result.body)
            if page.observation.identity != initial:
                _fail("INTERMEDIATE_PR_DRIFT")
            resolved.extend(page.resolved)
            if not page.has_next_page:
                return tuple(resolved)
            cursor = page.end_cursor
            if cursor is None or cursor in seen:
                _fail("PAGINATION_CURSOR")
            seen.add(cursor)
            after = cursor
        _fail("PAGINATION_LIMIT")
