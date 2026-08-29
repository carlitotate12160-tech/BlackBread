from typing import Any

import pytest

from blackbread.governance.ai_review_gate import (
    STATUS_CONTEXT,
    STATUS_DESCRIPTION_LIMIT,
    GitHubEvidenceReader,
    evaluate,
    run_gate,
)

HEAD = "a" * 40
NEW_HEAD = "b" * 40
REPOSITORY = "carlitotate12160-tech/BlackBread"


def _qodo_review() -> dict[str, object]:
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
        "state": "COMMENTED",
        "commit_id": HEAD,
    }


def _evidence(review_threads: object) -> dict[str, object]:
    return {
        "evidence_read_success": True,
        "head_sha": HEAD,
        "verified_head_sha": HEAD,
        "repository": REPOSITORY,
        "changed_paths": ["README.md"],
        "reviews": [_qodo_review()],
        "issue_comments": [],
        "review_threads": review_threads,
    }


def test_unresolved_current_head_qodo_thread_denies_eligibility() -> None:
    evidence = _evidence(
        [
            {
                "is_resolved": False,
                "author_login": "qodo-code-review",
                "commit_sha": HEAD,
            }
        ]
    )

    decision = evaluate(evidence)

    assert not decision.eligible
    assert "unresolved current-head Qodo review thread" in decision.reasons


def test_resolved_current_head_qodo_thread_is_eligible() -> None:
    evidence = _evidence(
        [
            {
                "is_resolved": True,
                "author_login": "qodo-code-review",
                "commit_sha": HEAD,
            }
        ]
    )

    assert evaluate(evidence).eligible


def test_missing_review_thread_evidence_fails_closed() -> None:
    evidence = _evidence(None)

    decision = evaluate(evidence)

    assert not decision.eligible
    assert "review-thread evidence unavailable" in decision.reasons


def test_stale_qodo_thread_does_not_substitute_for_current_head_thread_state() -> None:
    evidence = _evidence(
        [
            {
                "is_resolved": False,
                "author_login": "qodo-code-review",
                "commit_sha": NEW_HEAD,
            }
        ]
    )

    assert evaluate(evidence).eligible


def test_non_qodo_thread_is_not_used_as_qodo_gate_evidence() -> None:
    evidence = _evidence(
        [
            {
                "is_resolved": False,
                "author_login": "repository-owner",
                "commit_sha": HEAD,
            }
        ]
    )

    assert evaluate(evidence).eligible


def test_reader_fetches_and_normalizes_review_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_payloads: list[dict[str, object]] = []

    def request(
        self: GitHubEvidenceReader,
        url: str,
        payload: dict[str, object] | None = None,
    ) -> Any:
        if url.endswith("/graphql"):
            assert payload is not None
            requested_payloads.append(payload)
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [
                                    {
                                        "isResolved": False,
                                        "comments": {
                                            "nodes": [
                                                {
                                                    "author": {"login": "qodo-code-review"},
                                                    "commit": {"oid": HEAD},
                                                }
                                            ],
                                            "pageInfo": {"hasNextPage": False},
                                        },
                                    }
                                ],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    }
                }
            }
        if "/pulls/7?" in url:
            return []
        if url.endswith("/pulls/7"):
            return {"head": {"sha": HEAD}}
        return []

    monkeypatch.setattr(GitHubEvidenceReader, "_request", request)

    reader = GitHubEvidenceReader(REPOSITORY, 7, "token")
    evidence = reader.read(expected_head_sha=HEAD)

    assert evidence["review_threads"] == [
        {
            "is_resolved": False,
            "author_login": "qodo-code-review",
            "commit_sha": HEAD,
        }
    ]
    assert requested_payloads


def test_status_publisher_targets_exact_authoritative_sha_and_bounds_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object] | None]] = []

    def request(
        self: GitHubEvidenceReader,
        url: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        calls.append((url, payload))
        return {"state": "pending"}

    monkeypatch.setattr(GitHubEvidenceReader, "_request", request)
    reader = GitHubEvidenceReader(REPOSITORY, 7, "token")

    reader.publish_status(HEAD, "pending", "x" * 500)

    assert calls == [
        (
            f"https://api.github.com/repos/{REPOSITORY}/statuses/{HEAD}",
            {
                "state": "pending",
                "context": STATUS_CONTEXT,
                "description": "x" * STATUS_DESCRIPTION_LIMIT,
            },
        )
    ]


class FakeReader:
    def __init__(
        self,
        *,
        evidence: dict[str, object] | None = None,
        initial_head: str = HEAD,
    ) -> None:
        self.evidence = evidence or _evidence([])
        self.initial_head = initial_head
        self.statuses: list[tuple[str, str, str]] = []
        self.read_expected_heads: list[str] = []

    def read_head_sha(self) -> str:
        return self.initial_head

    def read(self, expected_head_sha: str) -> dict[str, object]:
        self.read_expected_heads.append(expected_head_sha)
        return self.evidence

    def publish_status(self, sha: str, state: str, description: str) -> None:
        self.statuses.append((sha, state, description))


def test_run_gate_publishes_pending_then_success_on_authoritative_head() -> None:
    reader = FakeReader()

    exit_code = run_gate(reader)

    assert exit_code == 0
    assert reader.read_expected_heads == [HEAD]
    assert [status[:2] for status in reader.statuses] == [
        (HEAD, "pending"),
        (HEAD, "success"),
    ]
    assert all(len(description) <= STATUS_DESCRIPTION_LIMIT for _, _, description in reader.statuses)


def test_run_gate_publishes_failure_on_same_head_when_policy_denies() -> None:
    evidence = _evidence(
        [
            {
                "is_resolved": False,
                "author_login": "qodo-code-review",
                "commit_sha": HEAD,
            }
        ]
    )
    reader = FakeReader(evidence=evidence)

    exit_code = run_gate(reader)

    assert exit_code == 1
    assert [status[:2] for status in reader.statuses] == [
        (HEAD, "pending"),
        (HEAD, "failure"),
    ]


def test_run_gate_fails_closed_if_evidence_collection_raises() -> None:
    class RaisingReader(FakeReader):
        def read(self, expected_head_sha: str) -> dict[str, object]:
            raise ValueError("evidence unavailable")

    reader = RaisingReader()

    exit_code = run_gate(reader)

    assert exit_code == 1
    assert [status[:2] for status in reader.statuses] == [
        (HEAD, "pending"),
        (HEAD, "failure"),
    ]


def test_run_gate_fails_closed_if_final_status_publication_raises() -> None:
    class FailingPublisher(FakeReader):
        def publish_status(self, sha: str, state: str, description: str) -> None:
            if state == "success":
                raise ValueError("status API unavailable")
            super().publish_status(sha, state, description)

    reader = FailingPublisher()

    assert run_gate(reader) == 1
    assert [status[:2] for status in reader.statuses] == [(HEAD, "pending")]
