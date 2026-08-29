from copy import deepcopy

import pytest

from blackbread.governance.ai_review_gate import GitHubEvidenceReader, evaluate

HEAD = "aca9606cc6842c1282cb5c182efaef82fb6b2e64"
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


def test_authenticated_current_head_qodo_issue_comment_is_eligible(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence["reviews"] = []
    current_qodo_evidence["repository"] = REPOSITORY
    current_qodo_evidence["issue_comments"] = [_qodo_issue_comment()]

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
    current_qodo_evidence.update(repository=REPOSITORY, reviews=[], issue_comments=[comment])

    assert not evaluate(current_qodo_evidence).eligible


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
        if "?" not in url:
            return {"head": {"sha": HEAD}}
        return []

    monkeypatch.setattr(GitHubEvidenceReader, "_request", request)

    evidence = GitHubEvidenceReader(REPOSITORY, 13, "token").read()

    assert any("/issues/13/comments?per_page=100&page=1" in url for url in requested_urls)
    assert evidence["issue_comments"] == []


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
    }


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


def test_qodo_native_review_app_id_is_enforced(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence["reviews"][0]["performed_via_github_app"]["id"] = 999999

    assert not evaluate(current_qodo_evidence).eligible


def test_qodo_native_review_missing_app_id_fails_closed(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence["reviews"][0]["performed_via_github_app"].pop("id", None)

    assert not evaluate(current_qodo_evidence).eligible


def test_qodo_native_review_missing_app_fails_closed(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence["reviews"][0]["performed_via_github_app"] = None

    assert not evaluate(current_qodo_evidence).eligible


def test_qodo_native_review_correct_app_id_and_slug_accepted(
    current_qodo_evidence: dict[str, object],
) -> None:
    current_qodo_evidence["reviews"][0]["performed_via_github_app"] = {
        "id": 484649,
        "slug": "qodo-code-review",
    }

    assert evaluate(current_qodo_evidence).eligible
