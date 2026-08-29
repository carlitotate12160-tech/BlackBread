import json
from copy import deepcopy

import pytest

from blackbread.governance.ai_review_gate import (
    PAGE_SIZE,
    STATUS_CONTEXT,
    GitHubEvidenceReader,
    StatusPublisher,
    evaluate,
    run_gate,
)

HEAD = "aca9606cc6842c1282cb5c182efaef82fb6b2e64"
HEAD2 = "b" * 40
USER_AGENT = "BlackBread-ai-review-gate/1"
REPOSITORY = "carlitotate12160-tech/BlackBread"
QODO_MARKER = (
    "[Code review](https://example.invalid/review) by qodo was updated up to the latest "
    f"commit\nhttps://github.com/{REPOSITORY}/commit/{HEAD}"
)


def _qodo_issue_comment(body: str = QODO_MARKER) -> dict[str, object]:
    return {
        "user": {
            "login": "qodo-code-review[bot]",
            "id": 151058649,
            "type": "Bot",
        },
        "performed_via_github_app": {
            "id": 484649,
            "slug": "qodo-code-review",
        },
        "body": body,
    }


def _resolved_threads(count: int = 1) -> list[dict[str, object]]:
    return [{"isResolved": True} for _ in range(count)]


def _unresolved_threads(count: int = 1) -> list[dict[str, object]]:
    return [{"isResolved": False} for _ in range(count)]


# ---------------------------------------------------------------------------
# Qodo issue-comment evidence
# ---------------------------------------------------------------------------


def test_authenticated_current_head_qodo_issue_comment_is_eligible(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence["reviews"] = []
    current_qodo_evidence["repository"] = REPOSITORY
    current_qodo_evidence["issue_comments"] = [_qodo_issue_comment()]
    current_qodo_evidence["review_threads"] = _resolved_threads()

    assert evaluate(current_qodo_evidence).eligible


@pytest.mark.parametrize(
    ("mutation"),
    [
        lambda comment: comment["user"].update(login="repository-owner"),
        lambda comment: comment["user"].update(id=1),
        lambda comment: comment["performed_via_github_app"].update(id=1),
        lambda comment: comment["performed_via_github_app"].update(slug="wrong-app"),
        lambda comment: comment.update(performed_via_github_app=None),
        lambda comment: comment.update(body=QODO_MARKER.replace(HEAD, "0" * 40)),
        lambda comment: comment.update(body=QODO_MARKER.replace(HEAD, HEAD[:7])),
        lambda comment: comment.update(body=QODO_MARKER.replace(HEAD, "not-a-sha")),
        lambda comment: comment.update(
            body=QODO_MARKER.replace(REPOSITORY, "another-owner/another-repository")
        ),
        lambda comment: comment.update(body=f"{QODO_MARKER}\n{QODO_MARKER}"),
        lambda comment: comment.update(body="No current review marker"),
    ],
    ids=[
        "owner-copied-marker",
        "wrong-user-id",
        "wrong-app-id",
        "wrong-app-slug",
        "missing-app",
        "stale-sha",
        "short-sha",
        "malformed-sha",
        "wrong-repository",
        "ambiguous-markers",
        "missing-marker",
    ],
)
def test_qodo_issue_comment_evidence_fails_closed(
    current_qodo_evidence: dict[str, object], mutation: object
) -> None:
    comment = _qodo_issue_comment()
    mutation(comment)
    current_qodo_evidence.update(
        repository=REPOSITORY,
        reviews=[],
        issue_comments=[comment],
        review_threads=_resolved_threads(),
    )

    assert not evaluate(current_qodo_evidence).eligible


# ---------------------------------------------------------------------------
# Reader: issue comments + review threads
# ---------------------------------------------------------------------------


def test_reader_fetches_bounded_issue_comments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_urls: list[str] = []

    def request(
        self: GitHubEvidenceReader,
        url: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        requested_urls.append(url)
        if payload is not None:
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [],
                                "pageInfo": {"hasNextPage": False},
                            }
                        }
                    }
                }
            }
        if "?" not in url:
            return {"head": {"sha": HEAD}}
        return []

    monkeypatch.setattr(GitHubEvidenceReader, "_request", request)

    evidence = GitHubEvidenceReader(REPOSITORY, 13, "token").read()

    assert any("/issues/13/comments?per_page=100&page=1" in url for url in requested_urls)
    assert evidence["issue_comments"] == []
    assert evidence["review_threads"] == []


def test_github_requests_use_repository_owned_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_headers: list[dict[str, str]] = []

    class Response:
        status = 200

        def read(self) -> bytes:
            return b"{}"

    class Connection:
        def __init__(self, host: str, timeout: int) -> None:
            assert host == "api.github.com"
            assert timeout == 20

        def request(
            self,
            method: str,
            path: str,
            body: bytes | None,
            headers: dict[str, str],
        ) -> None:
            captured_headers.append(headers)

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "blackbread.governance.ai_review_gate.http.client.HTTPSConnection", Connection
    )
    reader = GitHubEvidenceReader("owner/repository", 13, "token")

    reader._request("https://api.github.com/repos/owner/repository/pulls/13")

    assert captured_headers
    assert all(headers["User-Agent"] == USER_AGENT for headers in captured_headers)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def current_qodo_evidence() -> dict[str, object]:
    return {
        "evidence_read_success": True,
        "head_sha": HEAD,
        "verified_head_sha": HEAD,
        "changed_paths": ["README.md"],
        "reviews": [
            {
                "user": {
                    "login": "qodo-code-review[bot]",
                    "id": 151058649,
                    "type": "Bot",
                },
                "performed_via_github_app": {"id": 484649, "slug": "qodo-code-review"},
                "state": "COMMENTED",
                "commit_id": HEAD,
            }
        ],
        "review_threads": _resolved_threads(),
    }


# ---------------------------------------------------------------------------
# Qodo native review tests
# ---------------------------------------------------------------------------


def test_current_trusted_qodo_review_without_unresolved_threads_is_eligible(
    current_qodo_evidence: dict[str, object],
) -> None:
    assert evaluate(current_qodo_evidence).eligible


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda evidence: evidence.update(reviews=[]), "missing current-head Qodo review"),
        (
            lambda evidence: evidence["reviews"][0].update(commit_id="0" * 40),
            "missing current-head Qodo review",
        ),
        (
            lambda evidence: evidence["reviews"][0]["user"].update(login="untrusted[bot]"),
            "missing current-head Qodo review",
        ),
        (
            lambda evidence: evidence["reviews"][0].update(state="PENDING"),
            "missing current-head Qodo review",
        ),
        (lambda evidence: evidence.update(evidence_read_success=False), "evidence read failed"),
    ],
)
def test_qodo_policy_fails_closed(
    current_qodo_evidence: dict[str, object], mutation: object, reason: str
) -> None:
    evidence = deepcopy(current_qodo_evidence)
    mutation(evidence)

    decision = evaluate(evidence)

    assert not decision.eligible
    assert reason in decision.reasons


def test_current_head_change_invalidates_old_qodo_review(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence["verified_head_sha"] = "1" * 40

    decision = evaluate(current_qodo_evidence)

    assert not decision.eligible
    assert "current PR head changed during evidence collection" in decision.reasons


# ---------------------------------------------------------------------------
# Safety-critical paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "src/blackbread/ledger/append.py",
        "src/blackbread/conductor/service.py",
        "src/blackbread/policy/kernel.py",
        "src/blackbread/authorization/lease.py",
        "src/blackbread/scope/manifest.py",
        "src/blackbread/security/vault.py",
        "src/blackbread/leases/model.py",
        "src/blackbread/kill_switch.py",
        "src/blackbread/capabilities/gateway.py",
        "src/blackbread/tenant_context.py",
        "src/blackbread/models/core.py",
        "config/capability-registry.json",
    ],
)
def test_safety_critical_paths_fail_closed_without_verified_coderabbit_evidence(
    current_qodo_evidence: dict[str, object],
    path: str,
) -> None:
    current_qodo_evidence["changed_paths"] = [path]

    decision = evaluate(current_qodo_evidence)

    assert not decision.eligible
    assert "verified current-head CodeRabbit full-review evidence unavailable" in decision.reasons


# ---------------------------------------------------------------------------
# Qodo identity enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [("id", 1), ("type", "User")],
)
def test_qodo_user_identity_fields_are_enforced(
    current_qodo_evidence: dict[str, object], field: str, value: object
) -> None:
    current_qodo_evidence["reviews"][0]["user"][field] = value

    assert not evaluate(current_qodo_evidence).eligible


def test_qodo_app_slug_is_enforced(current_qodo_evidence: dict[str, object]) -> None:
    current_qodo_evidence["reviews"][0]["performed_via_github_app"]["slug"] = "unexpected"

    assert not evaluate(current_qodo_evidence).eligible


@pytest.mark.parametrize(
    ("mutation", "label"),
    [
        (lambda app: app.update(id=999999), "wrong-app-id"),
        (lambda app: app.pop("id", None), "missing-app-id"),
        (lambda review: review.update(performed_via_github_app=None), "missing-app"),
    ],
    ids=["wrong-app-id", "missing-app-id", "missing-app"],
)
def test_qodo_native_review_app_identity_fails_closed(
    current_qodo_evidence: dict[str, object], mutation: object, label: str
) -> None:
    mutation(
        current_qodo_evidence["reviews"][0]["performed_via_github_app"]
        if label != "missing-app"
        else current_qodo_evidence["reviews"][0]
    )

    assert not evaluate(current_qodo_evidence).eligible


# ---------------------------------------------------------------------------
# Thread resolution enforcement (GOV-GAP-003)
# ---------------------------------------------------------------------------


def test_all_threads_resolved_is_eligible(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence["review_threads"] = _resolved_threads(5)

    assert evaluate(current_qodo_evidence).eligible


def test_one_unresolved_thread_denies(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence["review_threads"] = [
        {"isResolved": True},
        {"isResolved": False},
    ]

    decision = evaluate(current_qodo_evidence)

    assert not decision.eligible
    assert "unresolved review threads" in decision.reasons


def test_multiple_unresolved_threads_deny(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence["review_threads"] = _unresolved_threads(3)

    decision = evaluate(current_qodo_evidence)

    assert not decision.eligible
    assert "unresolved review threads" in decision.reasons


def test_unresolved_non_qodo_thread_also_denies(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence["review_threads"] = [{"isResolved": False}]

    decision = evaluate(current_qodo_evidence)

    assert not decision.eligible
    assert "unresolved review threads" in decision.reasons


def test_missing_review_threads_fails_closed(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence.pop("review_threads", None)

    decision = evaluate(current_qodo_evidence)

    assert not decision.eligible
    assert "unresolved review threads" in decision.reasons


def test_malformed_thread_response_fails_closed(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence["review_threads"] = "not-a-list"

    decision = evaluate(current_qodo_evidence)

    assert not decision.eligible
    assert "unresolved review threads" in decision.reasons


def test_non_boolean_is_resolved_fails_closed(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence["review_threads"] = [{"isResolved": "false"}]

    decision = evaluate(current_qodo_evidence)

    assert not decision.eligible
    assert "unresolved review threads" in decision.reasons


# ---------------------------------------------------------------------------
# GraphQL review-thread fetching
# ---------------------------------------------------------------------------


def test_reader_fetches_review_threads_via_graphql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graphql_called: list[dict[str, object]] = []

    def request(
        self: GitHubEvidenceReader,
        url: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        if payload is not None:
            graphql_called.append(payload)
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [{"isResolved": True}, {"isResolved": False}],
                                "pageInfo": {"hasNextPage": False},
                            }
                        }
                    }
                }
            }
        if "?" not in url:
            return {"head": {"sha": HEAD}}
        return []

    monkeypatch.setattr(GitHubEvidenceReader, "_request", request)

    evidence = GitHubEvidenceReader(REPOSITORY, 13, "token").read()

    assert evidence["review_threads"] == [{"isResolved": True}, {"isResolved": False}]
    assert any(
        "/graphql" in str(c.get("query", "")) or "reviewThreads" in str(c.get("query", ""))
        for c in graphql_called
    )


def test_graphql_api_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def request(
        self: GitHubEvidenceReader,
        url: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        if payload is not None:
            raise ValueError("GraphQL API failure")
        if "?" not in url:
            return {"head": {"sha": HEAD}}
        return []

    monkeypatch.setattr(GitHubEvidenceReader, "_request", request)

    with pytest.raises(ValueError, match="GraphQL API failure"):
        GitHubEvidenceReader(REPOSITORY, 13, "token").read()


def test_graphql_malformed_response_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def request(
        self: GitHubEvidenceReader,
        url: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        if payload is not None:
            return {"data": {"repository": {"pullRequest": None}}}
        if "?" not in url:
            return {"head": {"sha": HEAD}}
        return []

    monkeypatch.setattr(GitHubEvidenceReader, "_request", request)

    with pytest.raises(ValueError, match="malformed"):
        GitHubEvidenceReader(REPOSITORY, 13, "token").read()


def test_graphql_pagination_overflow_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = [0]

    def request(
        self: GitHubEvidenceReader,
        url: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        if payload is not None:
            call_count[0] += 1
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [{"isResolved": True}] * PAGE_SIZE,
                                "pageInfo": {"hasNextPage": True, "endCursor": "cursor"},
                            }
                        }
                    }
                }
            }
        if "?" not in url:
            return {"head": {"sha": HEAD}}
        return []

    monkeypatch.setattr(GitHubEvidenceReader, "_request", request)

    with pytest.raises(ValueError, match="pagination"):
        GitHubEvidenceReader(REPOSITORY, 13, "token").read()


def test_graphql_errors_with_partial_data_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def request(
        self: GitHubEvidenceReader,
        url: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        if payload is not None:
            return {
                "errors": [{"message": "internal error"}],
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [],
                                "pageInfo": {"hasNextPage": False},
                            }
                        }
                    }
                },
            }
        if "?" not in url:
            return {"head": {"sha": HEAD}}
        return []

    monkeypatch.setattr(GitHubEvidenceReader, "_request", request)

    with pytest.raises(ValueError, match="errors"):
        GitHubEvidenceReader(REPOSITORY, 13, "token").read()


def test_graphql_missing_page_info_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def request(
        self: GitHubEvidenceReader,
        url: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        if payload is not None:
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [{"isResolved": True}],
                            }
                        }
                    }
                }
            }
        if "?" not in url:
            return {"head": {"sha": HEAD}}
        return []

    monkeypatch.setattr(GitHubEvidenceReader, "_request", request)

    with pytest.raises(ValueError, match=r"malformed.*pagination"):
        GitHubEvidenceReader(REPOSITORY, 13, "token").read()


def test_graphql_non_boolean_has_next_page_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def request(
        self: GitHubEvidenceReader,
        url: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        if payload is not None:
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [{"isResolved": True}],
                                "pageInfo": {"hasNextPage": "true"},
                            }
                        }
                    }
                }
            }
        if "?" not in url:
            return {"head": {"sha": HEAD}}
        return []

    monkeypatch.setattr(GitHubEvidenceReader, "_request", request)

    with pytest.raises(ValueError, match=r"malformed.*pagination"):
        GitHubEvidenceReader(REPOSITORY, 13, "token").read()


# ---------------------------------------------------------------------------
# Status publisher
# ---------------------------------------------------------------------------


class _FakeConnection:
    def __init__(self, host: str, timeout: int) -> None:
        assert host == "api.github.com"
        assert timeout == 20
        self.requests: list[dict[str, object]] = []
        self._response_status = 201

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
    ) -> None:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "body": json.loads(body) if body else None,
                "headers": headers,
            }
        )

    def getresponse(self) -> object:
        class Resp:
            status = self._response_status

            def read(self) -> bytes:
                return b"{}"

        return Resp()

    def close(self) -> None:
        pass


def test_status_publisher_targets_authoritative_pr_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection("api.github.com", 20)
    monkeypatch.setattr(
        "blackbread.governance.ai_review_gate.http.client.HTTPSConnection",
        lambda host, timeout: conn,
    )
    publisher = StatusPublisher(REPOSITORY, "token")

    publisher.publish(HEAD, "pending", "evaluating")

    assert len(conn.requests) == 1
    req = conn.requests[0]
    assert req["method"] == "POST"
    assert req["path"] == f"/repos/{REPOSITORY}/statuses/{HEAD}"


def test_status_publisher_context_is_exactly_ai_review_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection("api.github.com", 20)
    monkeypatch.setattr(
        "blackbread.governance.ai_review_gate.http.client.HTTPSConnection",
        lambda host, timeout: conn,
    )
    publisher = StatusPublisher(REPOSITORY, "token")

    publisher.publish(HEAD, "success", "passed")

    body = conn.requests[0]["body"]
    assert body["context"] == STATUS_CONTEXT


def test_status_publisher_rejects_invalid_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = StatusPublisher(REPOSITORY, "token")

    with pytest.raises(ValueError, match="invalid status target SHA"):
        publisher.publish("short", "pending", "test")


def test_status_publisher_rejects_invalid_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = StatusPublisher(REPOSITORY, "token")

    with pytest.raises(ValueError, match="invalid status state"):
        publisher.publish(HEAD, "unknown", "test")


def test_status_publisher_bounds_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection("api.github.com", 20)
    monkeypatch.setattr(
        "blackbread.governance.ai_review_gate.http.client.HTTPSConnection",
        lambda host, timeout: conn,
    )
    publisher = StatusPublisher(REPOSITORY, "token")

    long_desc = "x" * 500
    publisher.publish(HEAD, "pending", long_desc)

    body = conn.requests[0]["body"]
    assert len(body["description"]) <= 140


# ---------------------------------------------------------------------------
# run_gate orchestration
# ---------------------------------------------------------------------------


def _mock_reader(monkeypatch: pytest.MonkeyPatch, head: str = HEAD) -> list[str]:
    published: list[dict[str, str]] = []

    def fetch_head_sha(self: GitHubEvidenceReader) -> str:
        return head

    def read(self: GitHubEvidenceReader) -> dict[str, object]:
        return {
            "evidence_read_success": True,
            "head_sha": head,
            "verified_head_sha": head,
            "repository": REPOSITORY,
            "changed_paths": ["README.md"],
            "reviews": [
                {
                    "user": {
                        "login": "qodo-code-review[bot]",
                        "id": 151058649,
                        "type": "Bot",
                    },
                    "performed_via_github_app": {"id": 484649, "slug": "qodo-code-review"},
                    "state": "COMMENTED",
                    "commit_id": head,
                }
            ],
            "issue_comments": [],
            "review_threads": _resolved_threads(),
        }

    monkeypatch.setattr(GitHubEvidenceReader, "fetch_head_sha", fetch_head_sha)
    monkeypatch.setattr(GitHubEvidenceReader, "read", read)
    return published


def _mock_publisher(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    published: list[dict[str, str]] = []

    def publish(
        self: StatusPublisher,
        head_sha: str,
        state: str,
        description: str,
    ) -> None:
        published.append({"sha": head_sha, "state": state, "description": description})

    monkeypatch.setattr(StatusPublisher, "publish", publish)
    return published


def test_run_gate_eligible_publishes_success_to_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_reader(monkeypatch)
    published = _mock_publisher(monkeypatch)

    result = run_gate(REPOSITORY, 13, "token")

    assert result == 0
    states = [p["state"] for p in published]
    assert states == ["pending", "success"]
    assert all(p["sha"] == HEAD for p in published)


def test_run_gate_head_race_after_success_re_fetches_and_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_calls = [0]

    def fetch_head_sha(self: GitHubEvidenceReader) -> str:
        fetch_calls[0] += 1
        return HEAD if fetch_calls[0] == 1 else HEAD2

    def read(self: GitHubEvidenceReader) -> dict[str, object]:
        return {
            "evidence_read_success": True,
            "head_sha": HEAD,
            "verified_head_sha": HEAD,
            "repository": REPOSITORY,
            "changed_paths": ["README.md"],
            "reviews": [
                {
                    "user": {
                        "login": "qodo-code-review[bot]",
                        "id": 151058649,
                        "type": "Bot",
                    },
                    "performed_via_github_app": {"id": 484649, "slug": "qodo-code-review"},
                    "state": "COMMENTED",
                    "commit_id": HEAD,
                }
            ],
            "issue_comments": [],
            "review_threads": _resolved_threads(),
        }

    monkeypatch.setattr(GitHubEvidenceReader, "fetch_head_sha", fetch_head_sha)
    monkeypatch.setattr(GitHubEvidenceReader, "read", read)
    published = _mock_publisher(monkeypatch)

    result = run_gate(REPOSITORY, 13, "token")

    assert result == 1
    assert "success" not in [p["state"] for p in published]
    failure_to_head = [p for p in published if p["sha"] == HEAD and p["state"] == "failure"]
    assert failure_to_head


def test_run_gate_ineligible_publishes_failure_to_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def read(self: GitHubEvidenceReader) -> dict[str, object]:
        return {
            "evidence_read_success": True,
            "head_sha": HEAD,
            "verified_head_sha": HEAD,
            "repository": REPOSITORY,
            "changed_paths": ["README.md"],
            "reviews": [],
            "issue_comments": [],
            "review_threads": _resolved_threads(),
        }

    monkeypatch.setattr(GitHubEvidenceReader, "fetch_head_sha", lambda self: HEAD)
    monkeypatch.setattr(GitHubEvidenceReader, "read", read)
    published = _mock_publisher(monkeypatch)

    result = run_gate(REPOSITORY, 13, "token")

    assert result == 1
    states = [p["state"] for p in published]
    assert states == ["pending", "failure"]
    assert all(p["sha"] == HEAD for p in published)


def test_run_gate_head_race_never_publishes_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def read(self: GitHubEvidenceReader) -> dict[str, object]:
        return {
            "evidence_read_success": True,
            "head_sha": HEAD,
            "verified_head_sha": HEAD2,
            "repository": REPOSITORY,
            "changed_paths": ["README.md"],
            "reviews": [],
            "issue_comments": [],
            "review_threads": _resolved_threads(),
        }

    monkeypatch.setattr(GitHubEvidenceReader, "fetch_head_sha", lambda self: HEAD)
    monkeypatch.setattr(GitHubEvidenceReader, "read", read)
    published = _mock_publisher(monkeypatch)

    result = run_gate(REPOSITORY, 13, "token")

    assert result == 1
    assert "success" not in [p["state"] for p in published]
    failure_to_head = [p for p in published if p["sha"] == HEAD and p["state"] == "failure"]
    assert failure_to_head


def test_run_gate_exception_after_h_publishes_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def read(self: GitHubEvidenceReader) -> dict[str, object]:
        raise ValueError("evidence collection failed")

    monkeypatch.setattr(GitHubEvidenceReader, "fetch_head_sha", lambda self: HEAD)
    monkeypatch.setattr(GitHubEvidenceReader, "read", read)
    published = _mock_publisher(monkeypatch)

    result = run_gate(REPOSITORY, 13, "token")

    assert result == 1
    failure_to_head = [p for p in published if p["sha"] == HEAD and p["state"] == "failure"]
    assert failure_to_head


def test_run_gate_missing_head_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fetch_head_sha(self: GitHubEvidenceReader) -> str:
        raise ValueError("PR not found")

    monkeypatch.setattr(GitHubEvidenceReader, "fetch_head_sha", fetch_head_sha)
    published = _mock_publisher(monkeypatch)

    result = run_gate(REPOSITORY, 13, "token")

    assert result == 1
    assert published == []


def test_run_gate_pending_published_before_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_order: list[str] = []

    def fetch_head_sha(self: GitHubEvidenceReader) -> str:
        call_order.append("fetch_head")
        return HEAD

    def read(self: GitHubEvidenceReader) -> dict[str, object]:
        call_order.append("read")
        return {
            "evidence_read_success": True,
            "head_sha": HEAD,
            "verified_head_sha": HEAD,
            "repository": REPOSITORY,
            "changed_paths": ["README.md"],
            "reviews": [],
            "issue_comments": [],
            "review_threads": _resolved_threads(),
        }

    def publish(
        self: StatusPublisher,
        head_sha: str,
        state: str,
        description: str,
    ) -> None:
        call_order.append(f"publish:{state}")

    monkeypatch.setattr(GitHubEvidenceReader, "fetch_head_sha", fetch_head_sha)
    monkeypatch.setattr(GitHubEvidenceReader, "read", read)
    monkeypatch.setattr(StatusPublisher, "publish", publish)

    run_gate(REPOSITORY, 13, "token")

    assert call_order.index("publish:pending") < call_order.index("read")
