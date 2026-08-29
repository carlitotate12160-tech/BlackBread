"""Deterministic repository-owned AI review policy gate."""

from __future__ import annotations

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
HTTP_SUCCESS_MIN = 200
HTTP_SUCCESS_MAX = 300
GITHUB_API_USER_AGENT = "BlackBread-ai-review-gate/1"
SAFETY_CRITICAL_PATH_PARTS = (
    "src/blackbread/ledger/",
    "src/blackbread/conductor/",
    "src/blackbread/policy/",
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
    if _is_safety_critical(evidence.get("changed_paths")):
        reasons.append("verified current-head CodeRabbit full-review evidence unavailable")
    return Decision(not reasons, tuple(reasons))


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

    def read(self) -> dict[str, object]:
        pull_url = f"https://api.github.com/repos/{self.repository}/pulls/{self.pull_number}"
        pull = self._request(pull_url)
        reviews = self._rest_pages(f"pulls/{self.pull_number}/reviews")
        issue_comments = self._rest_pages(f"issues/{self.pull_number}/comments")
        files = self._rest_pages(f"pulls/{self.pull_number}/files")
        verified_pull = self._request(pull_url)
        return {
            "evidence_read_success": True,
            "head_sha": pull["head"]["sha"],
            "verified_head_sha": verified_pull["head"]["sha"],
            "repository": self.repository,
            "changed_paths": [item["filename"] for item in files],
            "reviews": reviews,
            "issue_comments": issue_comments,
        }


def main() -> int:
    try:
        repository = os.environ["GITHUB_REPOSITORY"]
        pull_number = int(os.environ["PR_NUMBER"])
        token = os.environ["GITHUB_TOKEN"]
        evidence = GitHubEvidenceReader(repository, pull_number, token).read()
        decision = evaluate(evidence)
    except Exception as error:
        print(f"ai-review-gate denied: evidence read or policy evaluation failed: {error}")
        return 1
    if not decision.eligible:
        print("ai-review-gate denied: " + "; ".join(decision.reasons))
        return 1
    print("ai-review-gate passed for the current PR head")
    return 0


if __name__ == "__main__":
    sys.exit(main())
