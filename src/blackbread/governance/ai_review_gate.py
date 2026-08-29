"""Deterministic repository-owned AI review policy gate."""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import re
import sys
import urllib.parse
from dataclasses import dataclass
from typing import Any

QODO_LOGIN = "qodo-code-review[bot]"
QODO_USER_ID = 151058649
QODO_APP_SLUG = "qodo-code-review"
QODO_APP_ID = 484649
QODO_UPDATE_MARKER = "by qodo was updated up to the latest commit"
COMPLETED_QODO_STATES = {"COMMENTED"}
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
PAGE_SIZE = 100
MAX_GRAPHQL_PAGES = 10
HTTP_SUCCESS_MIN = 200
HTTP_SUCCESS_MAX = 300
GITHUB_API_USER_AGENT = "BlackBread-ai-review-gate/1"
STATUS_CONTEXT = "ai-review-gate"
MAX_DESCRIPTION_LENGTH = 140
SAFETY_CRITICAL_PATH_PARTS = (
    "src/blackbread/ledger/",
    "src/blackbread/conductor/",
    "src/blackbread/policy/",
    "src/blackbread/opsec/",
    "src/blackbread/identity/",
    "src/blackbread/authorization/",
    "src/blackbread/scope/",
    "src/blackbread/security/",
    "src/blackbread/leases/",
    "src/blackbread/kill_switch",
    "src/blackbread/capability/",
    "src/blackbread/capabilities/",
    "src/blackbread/gateway/",
    "src/blackbread/tenant",
    "src/blackbread/models/core.py",
    "config/capability-registry.json",
)

GRAPHQL_REVIEW_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $first: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: $first, after: $after) {
        nodes { isResolved }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class Decision:
    eligible: bool
    reasons: tuple[str, ...]


def _is_current_qodo_review(review: object, head_sha: str) -> bool:
    if not isinstance(review, dict):
        return False
    user = review.get("user")
    app = review.get("performed_via_github_app")
    return (
        isinstance(user, dict)
        and user.get("login") == QODO_LOGIN
        and user.get("id") == QODO_USER_ID
        and user.get("type") == "Bot"
        and isinstance(app, dict)
        and app.get("id") == QODO_APP_ID
        and app.get("slug") == QODO_APP_SLUG
        and review.get("state") in COMPLETED_QODO_STATES
        and review.get("commit_id") == head_sha
    )


def _is_current_qodo_issue_comment(comment: object, repository: str, head_sha: str) -> bool:
    if not isinstance(comment, dict):
        return False
    user = comment.get("user")
    app = comment.get("performed_via_github_app")
    body = comment.get("body")
    if not (
        isinstance(user, dict)
        and user.get("login") == QODO_LOGIN
        and user.get("id") == QODO_USER_ID
        and user.get("type") == "Bot"
        and isinstance(app, dict)
        and app.get("id") == QODO_APP_ID
        and app.get("slug") == QODO_APP_SLUG
        and isinstance(body, str)
    ):
        return False
    marker_urls = re.findall(
        rf"{re.escape(QODO_UPDATE_MARKER)}\s+(https://github\.com/[^\s]+)", body
    )
    expected_url = f"https://github.com/{repository}/commit/{head_sha}"
    return marker_urls == [expected_url]


def _is_safety_critical(paths: object) -> bool:
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        return True
    return any(
        path == part or path.startswith(part)
        for path in paths
        for part in SAFETY_CRITICAL_PATH_PARTS
    )


def _has_unresolved_threads(threads: object) -> bool:
    if not isinstance(threads, list):
        return True
    return any(
        not isinstance(thread, dict) or thread.get("isResolved") is not True for thread in threads
    )


def evaluate(evidence: object) -> Decision:
    if not isinstance(evidence, dict) or evidence.get("evidence_read_success") is not True:
        return Decision(False, ("evidence read failed",))

    head_sha = evidence.get("head_sha")
    if not isinstance(head_sha, str) or SHA_PATTERN.fullmatch(head_sha) is None:
        return Decision(False, ("invalid current head SHA",))
    if evidence.get("verified_head_sha") != head_sha:
        return Decision(False, ("current PR head changed during evidence collection",))

    reasons: list[str] = []
    reviews = evidence.get("reviews")
    repository = evidence.get("repository")
    comments = evidence.get("issue_comments")
    trusted_review = isinstance(reviews, list) and any(
        _is_current_qodo_review(review, head_sha) for review in reviews
    )
    trusted_comment = (
        isinstance(repository, str)
        and isinstance(comments, list)
        and any(
            _is_current_qodo_issue_comment(comment, repository, head_sha) for comment in comments
        )
    )
    if not trusted_review and not trusted_comment:
        reasons.append("missing current-head Qodo review")
    if _has_unresolved_threads(evidence.get("review_threads")):
        reasons.append("unresolved review threads")
    if _is_safety_critical(evidence.get("changed_paths")):
        reasons.append("verified current-head CodeRabbit full-review evidence unavailable")
    return Decision(not reasons, tuple(reasons))


def _bound_description(text: str) -> str:
    return text[:MAX_DESCRIPTION_LENGTH]


class GitHubEvidenceReader:
    def __init__(self, repository: str, pull_number: int, token: str) -> None:
        self.repository = repository
        self.pull_number = pull_number
        self.token = token

    def _request(self, url: str, payload: dict[str, object] | None = None) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise ValueError("untrusted GitHub API URL")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": GITHUB_API_USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if body:
            headers["Content-Type"] = "application/json"
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        connection = http.client.HTTPSConnection("api.github.com", timeout=20)
        try:
            connection.request("POST" if body else "GET", path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
        finally:
            connection.close()
        if not HTTP_SUCCESS_MIN <= response.status < HTTP_SUCCESS_MAX:
            raise ValueError(f"GitHub API returned HTTP {response.status}")
        return json.loads(response_body)

    def _rest_pages(self, endpoint: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for page in range(1, 11):
            url = (
                f"https://api.github.com/repos/{self.repository}/{endpoint}"
                f"?per_page={PAGE_SIZE}&page={page}"
            )
            items = self._request(url)
            if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                raise ValueError("unexpected GitHub REST response")
            results.extend(items)
            if len(items) < PAGE_SIZE:
                return results
        raise ValueError("GitHub REST evidence exceeds bounded pagination")

    def _graphql_review_threads(self) -> list[dict[str, Any]]:
        owner, _, name = self.repository.partition("/")
        threads: list[dict[str, Any]] = []
        after: str | None = None
        for _ in range(MAX_GRAPHQL_PAGES):
            variables: dict[str, object] = {
                "owner": owner,
                "name": name,
                "number": self.pull_number,
                "first": PAGE_SIZE,
            }
            if after is not None:
                variables["after"] = after
            result = self._request(
                "https://api.github.com/graphql",
                {"query": GRAPHQL_REVIEW_THREADS_QUERY, "variables": variables},
            )
            if not isinstance(result, dict) or result.get("errors"):
                raise ValueError("GraphQL review-thread response contains errors")
            pr_data = (
                result.get("data", {}).get("repository", {}).get("pullRequest")
                if isinstance(result, dict)
                else None
            )
            if not isinstance(pr_data, dict):
                raise ValueError("malformed GraphQL review-thread response")
            page = pr_data.get("reviewThreads")
            if not isinstance(page, dict):
                raise ValueError("malformed reviewThreads structure")
            nodes = page.get("nodes")
            if not isinstance(nodes, list) or not all(isinstance(n, dict) for n in nodes):
                raise ValueError("malformed review-thread nodes")
            threads.extend(nodes)
            page_info = page.get("pageInfo")
            if not isinstance(page_info, dict) or not isinstance(
                page_info.get("hasNextPage"), bool
            ):
                raise ValueError("malformed review-thread pagination")
            if not page_info["hasNextPage"]:
                return threads
            after = page_info.get("endCursor")
            if not isinstance(after, str):
                raise ValueError("malformed pagination cursor")
        raise ValueError("GraphQL review-thread pagination exceeds bounded limit")

    def read(self) -> dict[str, object]:
        pull_url = f"https://api.github.com/repos/{self.repository}/pulls/{self.pull_number}"
        pull = self._request(pull_url)
        reviews = self._rest_pages(f"pulls/{self.pull_number}/reviews")
        issue_comments = self._rest_pages(f"issues/{self.pull_number}/comments")
        files = self._rest_pages(f"pulls/{self.pull_number}/files")
        review_threads = self._graphql_review_threads()
        verified_pull = self._request(pull_url)
        return {
            "evidence_read_success": True,
            "head_sha": pull["head"]["sha"],
            "verified_head_sha": verified_pull["head"]["sha"],
            "repository": self.repository,
            "changed_paths": [item["filename"] for item in files],
            "reviews": reviews,
            "issue_comments": issue_comments,
            "review_threads": review_threads,
        }

    def fetch_head_sha(self) -> str:
        pull_url = f"https://api.github.com/repos/{self.repository}/pulls/{self.pull_number}"
        pull = self._request(pull_url)
        head = pull.get("head", {}).get("sha")
        if not isinstance(head, str) or SHA_PATTERN.fullmatch(head) is None:
            raise ValueError("authoritative PR head SHA unavailable")
        return head


class StatusPublisher:
    def __init__(self, repository: str, token: str) -> None:
        self.repository = repository
        self.token = token

    def publish(
        self,
        head_sha: str,
        state: str,
        description: str,
    ) -> None:
        if not SHA_PATTERN.fullmatch(head_sha):
            raise ValueError("invalid status target SHA")
        if state not in ("pending", "success", "failure"):
            raise ValueError("invalid status state")
        url = f"https://api.github.com/repos/{self.repository}/statuses/{head_sha}"
        payload: dict[str, object] = {
            "state": state,
            "context": STATUS_CONTEXT,
            "description": _bound_description(description),
        }
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": GITHUB_API_USER_AGENT,
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        body = json.dumps(payload).encode()
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise ValueError("untrusted GitHub API URL")
        connection = http.client.HTTPSConnection("api.github.com", timeout=20)
        try:
            connection.request("POST", parsed.path, body=body, headers=headers)
            response = connection.getresponse()
            response.read()
        finally:
            connection.close()
        if not HTTP_SUCCESS_MIN <= response.status < HTTP_SUCCESS_MAX:
            raise ValueError(f"GitHub status API returned HTTP {response.status}")


def run_gate(repository: str, pull_number: int, token: str) -> int:
    reader = GitHubEvidenceReader(repository, pull_number, token)
    publisher = StatusPublisher(repository, token)
    head_sha: str | None = None
    try:
        head_sha = reader.fetch_head_sha()
        publisher.publish(head_sha, "pending", "evaluating AI review evidence")
        evidence = reader.read()
        decision = evaluate(evidence)
        verified_head = evidence.get("verified_head_sha")
        if verified_head != head_sha:
            publisher.publish(head_sha, "failure", "head changed during evaluation")
            return 1
        if decision.eligible:
            final_head = reader.fetch_head_sha()
            if final_head != head_sha:
                publisher.publish(head_sha, "failure", "head changed during evaluation")
                return 1
            publisher.publish(head_sha, "success", "AI review gate passed")
            return 0
        publisher.publish(head_sha, "failure", "; ".join(decision.reasons))
        return 1
    except Exception as error:
        if head_sha is not None:
            with contextlib.suppress(Exception):
                publisher.publish(head_sha, "failure", "gate evaluation error")
        print(f"ai-review-gate denied: {error}")
        return 1


def main() -> int:
    try:
        repository = os.environ["GITHUB_REPOSITORY"]
        pull_number = int(os.environ["PR_NUMBER"])
        token = os.environ["GITHUB_TOKEN"]
    except (KeyError, ValueError) as error:
        print(f"ai-review-gate denied: configuration error: {error}")
        return 1
    return run_gate(repository, pull_number, token)


if __name__ == "__main__":
    sys.exit(main())
