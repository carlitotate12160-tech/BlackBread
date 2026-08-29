from copy import deepcopy

import pytest

from blackbread.governance.ai_review_gate import GitHubEvidenceReader, evaluate

HEAD = "aca9606cc6842c1282cb5c182efaef82fb6b2e64"
USER_AGENT = "BlackBread-ai-review-gate/1"


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
                "performed_via_github_app": {"slug": "qodo-code-review"},
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
