"""Fail-closed merge-readiness proofs: missing, drifting, or partial evidence
must never produce ready=true."""

import io
import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from email.message import Message
from pathlib import Path
from typing import ClassVar

import pytest

from blackbread.governance.github_merge_evidence import (
    GITHUB_API_BASE,
    MergeEvidenceCollector,
    TransportError,
    TransportResult,
    UrllibGitHubTransport,
    main,
)
from blackbread.governance.merge_readiness import (
    BlockerCode,
    CheckRunEvidence,
    CodeScanningAlertEvidence,
    CodeScanningAnalysisEvidence,
    CodeScanningRequirement,
    DeliveryContract,
    EvidenceSnapshot,
    PullRequestIdentity,
    RulesetEvidence,
    evaluate_readiness,
)

REPO = "carlitotate12160-tech/BlackBread"
PR_NUMBER = 91
HEAD = "a" * 40
BASE = "b" * 40
MERGE = "c" * 40
RULESET_ID = 21644438
CONTRACT = str(Path(__file__).parents[2] / ".github/agent-delivery.json")


def _contract() -> DeliveryContract:
    return DeliveryContract(
        ruleset_id=RULESET_ID,
        require_branch_up_to_date=True,
        require_review_thread_resolution=True,
        allow_changes_requested=False,
        required_status_checks=("ci-ok", "GitGuardian Security Checks"),
        required_code_scanning=(
            CodeScanningRequirement(
                tool="CodeQL",
                security_alerts_threshold="high_or_higher",
                alerts_threshold="errors",
            ),
        ),
    )


def _identity(**overrides: object) -> PullRequestIdentity:
    base = {"head_sha": HEAD, "base_sha": BASE, "potential_merge_commit_sha": MERGE}
    return PullRequestIdentity(**{**base, **overrides})


def _ruleset(**overrides: object) -> RulesetEvidence:
    base = {
        "ruleset_id": RULESET_ID,
        "enforcement": "active",
        "required_status_check_contexts": ("ci-ok", "GitGuardian Security Checks"),
        "strict_status_checks": True,
        "code_scanning_tools": _contract().required_code_scanning,
        "unknown_rule_types": (),
    }
    return RulesetEvidence(**{**base, **overrides})


def _check_run(check_run_id: int, name: str, conclusion: str | None) -> CheckRunEvidence:
    return CheckRunEvidence(
        check_run_id=check_run_id, name=name, status="completed", conclusion=conclusion
    )


def _analysis(**overrides: object) -> CodeScanningAnalysisEvidence:
    base = {
        "tool": "CodeQL",
        "commit_sha": MERGE,
        "error": None,
        "created_at": "2026-09-13T10:00:00Z",
    }
    return CodeScanningAnalysisEvidence(**{**base, **overrides})


def _alert(
    number: int, state: str, security: str | None, severity: str | None
) -> CodeScanningAlertEvidence:
    return CodeScanningAlertEvidence(
        number=number,
        state=state,
        tool="CodeQL",
        security_severity_level=security,
        severity=severity,
    )


def _snapshot(**overrides: object) -> EvidenceSnapshot:
    base = {
        "repository": REPO,
        "ruleset": _ruleset(),
        "pull_request_before": _identity(),
        "pull_request_after": _identity(),
        "merge_state_status": "CLEAN",
        "unresolved_review_threads": 0,
        "changes_requested": False,
        "check_runs": (
            _check_run(1, "ci-ok", "success"),
            _check_run(2, "GitGuardian Security Checks", "success"),
        ),
        "analyses": (_analysis(),),
        "alerts": (),
        "errors": (),
    }
    return EvidenceSnapshot(**{**base, **overrides})


def _codes(snapshot: EvidenceSnapshot) -> set[BlockerCode]:
    report = evaluate_readiness(_contract(), snapshot, HEAD)
    return {blocker.code for blocker in report.blockers}


def test_ready_when_all_evidence_clean() -> None:
    report = evaluate_readiness(_contract(), _snapshot(), HEAD)
    assert report.ready is True
    assert report.blockers == ()
    assert report.observed_head_sha == HEAD
    assert report.base_sha == BASE
    assert report.potential_merge_commit_sha == MERGE
    assert report.ruleset_id == RULESET_ID


def test_code_scanning_gates() -> None:
    errored = _snapshot(analyses=(_analysis(error="SARIF upload failed"),), alerts=())
    assert BlockerCode.CODE_SCANNING_ANALYSIS_ERROR in _codes(errored)
    assert BlockerCode.CODE_SCANNING_RULE_MISSING in _codes(
        _snapshot(ruleset=_ruleset(code_scanning_tools=None))
    )
    assert BlockerCode.RULESET_UNAVAILABLE in _codes(_snapshot(ruleset=None))
    drifted = _ruleset(
        code_scanning_tools=(
            CodeScanningRequirement(
                tool="CodeQL",
                security_alerts_threshold="medium_or_higher",
                alerts_threshold="errors",
            ),
        )
    )
    assert BlockerCode.CODE_SCANNING_RULE_MISMATCH in _codes(_snapshot(ruleset=drifted))
    stale = _analysis(commit_sha="d" * 40)
    assert BlockerCode.CODE_SCANNING_ANALYSIS_MISSING in _codes(_snapshot(analyses=(stale,)))
    assert BlockerCode.CODE_SCANNING_ANALYSIS_MISSING in _codes(_snapshot(analyses=()))


def test_alert_thresholds_block_exactly() -> None:
    assert BlockerCode.CODE_SCANNING_SECURITY_ALERTS in _codes(
        _snapshot(alerts=(_alert(7, "open", "high", "error"),))
    )
    assert BlockerCode.CODE_SCANNING_ALERTS in _codes(
        _snapshot(alerts=(_alert(9, "open", None, "error"),))
    )
    # Negative controls: below-threshold or non-open alerts never block.
    assert _codes(_snapshot(alerts=(_alert(8, "open", "medium", "warning"),))) == set()
    assert _codes(_snapshot(alerts=(_alert(10, "dismissed", "critical", "error"),))) == set()


def test_required_check_gates() -> None:
    missing = _snapshot(check_runs=(_check_run(1, "ci-ok", "success"),))
    assert BlockerCode.REQUIRED_CHECK_MISSING in _codes(missing)
    failing = _snapshot(
        check_runs=(
            _check_run(1, "ci-ok", "failure"),
            _check_run(2, "GitGuardian Security Checks", "success"),
        )
    )
    assert BlockerCode.REQUIRED_CHECK_NOT_SUCCESS in _codes(failing)
    superseded = _snapshot(
        check_runs=(
            _check_run(1, "ci-ok", "failure"),
            _check_run(2, "GitGuardian Security Checks", "success"),
            _check_run(3, "ci-ok", "success"),
        )
    )
    assert _codes(superseded) == set()


def test_review_merge_state_and_ruleset_gates() -> None:
    assert BlockerCode.UNRESOLVED_REVIEW_THREADS in _codes(_snapshot(unresolved_review_threads=1))
    assert BlockerCode.CHANGES_REQUESTED in _codes(_snapshot(changes_requested=True))
    assert BlockerCode.RULESET_INACTIVE in _codes(
        _snapshot(ruleset=_ruleset(enforcement="evaluate"))
    )
    assert BlockerCode.RULESET_MISMATCH in _codes(_snapshot(ruleset=_ruleset(ruleset_id=1)))
    assert BlockerCode.RULESET_UNKNOWN_RULE in _codes(
        _snapshot(ruleset=_ruleset(unknown_rule_types=("brand_new_rule",)))
    )
    assert BlockerCode.STATUS_CHECK_RULE_MISSING in _codes(
        _snapshot(ruleset=_ruleset(required_status_check_contexts=None))
    )
    assert BlockerCode.STATUS_CHECK_RULE_MISMATCH in _codes(
        _snapshot(ruleset=_ruleset(required_status_check_contexts=("ci-ok",)))
    )


@pytest.mark.parametrize("state", ["BLOCKED", "BEHIND", "DIRTY", "DRAFT", "UNSTABLE", "UNKNOWN"])
def test_non_clean_merge_state_blocks(state: str) -> None:
    assert BlockerCode.MERGE_STATE_NOT_CLEAN in _codes(_snapshot(merge_state_status=state))


@pytest.mark.parametrize(
    "drift",
    [
        {"head_sha": "f" * 40},
        {"base_sha": "0" * 40},
        {"potential_merge_commit_sha": "9" * 40},
    ],
)
def test_identity_drift_blocks(drift: dict[str, str]) -> None:
    assert BlockerCode.IDENTITY_DRIFT in _codes(_snapshot(pull_request_after=_identity(**drift)))
    report = evaluate_readiness(_contract(), _snapshot(), "e" * 40)
    assert BlockerCode.EXPECTED_HEAD_MISMATCH in {b.code for b in report.blockers}


def test_missing_or_errored_evidence_blocks() -> None:
    assert BlockerCode.EVIDENCE_INCOMPLETE in _codes(_snapshot(pull_request_after=None))
    assert BlockerCode.EVIDENCE_INCOMPLETE in _codes(_snapshot(analyses=None, alerts=None))
    errored = _snapshot(errors=("alerts: HTTP 500",))
    assert BlockerCode.EVIDENCE_INCOMPLETE in _codes(errored)


# --- Collector fixtures ------------------------------------------------------

_RULESET_BODY = {
    "id": RULESET_ID,
    "name": "main-branch-protection",
    "enforcement": "active",
    "rules": [
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": True,
                "required_status_checks": [
                    {"context": "ci-ok", "integration_id": 15368},
                    {"context": "GitGuardian Security Checks", "integration_id": 46505},
                ],
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
        {"type": "pull_request", "parameters": {"required_approving_review_count": 0}},
    ],
}

_ANALYSIS_BODY = [
    {
        "id": 501,
        "ref": f"refs/pull/{PR_NUMBER}/merge",
        "commit_sha": MERGE,
        "error": "",
        "created_at": "2026-09-13T10:00:00Z",
        "tool": {"name": "CodeQL"},
    }
]


def _pr_body(
    head: str = HEAD,
    merge_state: str = "CLEAN",
    unresolved: int = 0,
    decision: str | None = None,
) -> dict[str, object]:
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "headRefOid": head,
                    "baseRefOid": BASE,
                    "mergeStateStatus": merge_state,
                    "reviewDecision": decision,
                    "potentialMergeCommit": {"oid": MERGE},
                    "reviewThreads": {
                        "nodes": [{"isResolved": False} for _ in range(unresolved)],
                        "pageInfo": {"hasNextPage": False},
                    },
                }
            }
        }
    }


class _FakeTransport:
    """Deterministic transport; a list value replays its results in call order."""

    def __init__(self, routes: Mapping[tuple[str, str], object]) -> None:
        self._routes = {
            key: list(value) if isinstance(value, list) else [value]
            for key, value in routes.items()
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: object | None = None,
    ) -> TransportResult:
        queue = self._routes.get((method, path))
        if not queue:
            raise TransportError(f"unrouted request: {method} {path}")
        result = queue.pop(0)
        if isinstance(result, TransportResult):
            return result
        if isinstance(result, BaseException):
            raise result
        return TransportResult(200, result, None)


def _green_routes() -> dict[tuple[str, str], object]:
    check_runs = {
        "check_runs": [
            {"id": 1, "name": "ci-ok", "status": "completed", "conclusion": "success"},
            {
                "id": 2,
                "name": "GitGuardian Security Checks",
                "status": "completed",
                "conclusion": "success",
            },
        ],
    }
    return {
        ("GET", f"/repos/{REPO}/rulesets/{RULESET_ID}"): TransportResult(200, _RULESET_BODY, None),
        ("POST", "/graphql"): [_pr_body(), _pr_body()],
        ("GET", f"/repos/{REPO}/commits/{HEAD}/check-runs"): TransportResult(200, check_runs, None),
        ("GET", f"/repos/{REPO}/code-scanning/analyses"): [
            TransportResult(200, _ANALYSIS_BODY, None),
            TransportResult(200, [], None),
        ],
        ("GET", f"/repos/{REPO}/code-scanning/alerts"): [
            TransportResult(200, [], None),
            TransportResult(200, [], None),
        ],
    }


def test_collect_is_fail_closed_and_toctou_safe() -> None:
    snapshot = MergeEvidenceCollector(_FakeTransport(_green_routes()), REPO).collect(
        PR_NUMBER, _contract()
    )
    report = evaluate_readiness(_contract(), snapshot, HEAD)
    assert snapshot.errors == ()
    assert report.ready is True, report.blockers

    empty = MergeEvidenceCollector(_FakeTransport({}), REPO).collect(PR_NUMBER, _contract())
    report = evaluate_readiness(_contract(), empty, HEAD)
    assert report.ready is False
    assert empty.errors != ()
    assert BlockerCode.EVIDENCE_INCOMPLETE in {b.code for b in report.blockers}

    drifted = _green_routes()
    drifted[("POST", "/graphql")] = [_pr_body(), _pr_body(head="f" * 40)]
    snapshot = MergeEvidenceCollector(_FakeTransport(drifted), REPO).collect(PR_NUMBER, _contract())
    report = evaluate_readiness(_contract(), snapshot, HEAD)
    assert BlockerCode.IDENTITY_DRIFT in {b.code for b in report.blockers}

    truncated = _pr_body()
    pull_request = truncated["data"]["repository"]["pullRequest"]
    pull_request["reviewThreads"]["pageInfo"] = {"hasNextPage": True}
    routes = _green_routes()
    routes[("POST", "/graphql")] = [truncated, _pr_body()]
    snapshot = MergeEvidenceCollector(_FakeTransport(routes), REPO).collect(PR_NUMBER, _contract())
    assert any("pull_request" in error for error in snapshot.errors)


# --- Module CLI and token hygiene --------------------------------------------

_CLI_ARGS = [
    "--repository",
    REPO,
    "--pr",
    str(PR_NUMBER),
    "--expected-head",
    HEAD,
    "--contract",
    CONTRACT,
]


def test_cli_exit_codes_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_CLI_ARGS, transport=_FakeTransport(_green_routes())) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is True
    assert payload["expected_head_sha"] == HEAD
    assert payload["ruleset_id"] == RULESET_ID

    routes = _green_routes()
    routes[("POST", "/graphql")] = [_pr_body(unresolved=2), _pr_body(unresolved=2)]
    assert main(_CLI_ARGS, transport=_FakeTransport(routes)) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is False
    assert "unresolved_review_threads" in {b["code"] for b in payload["blockers"]}


def test_transport_sends_token_only_in_header(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "unit-test-secret-token"  # noqa: S105
    captured: dict[str, object] = {}

    class _Response:
        status = 200
        headers: ClassVar[dict[str, str]] = {}

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps(_pr_body()).encode()

    def fake_urlopen(request: urllib.request.Request, timeout: float = 0) -> _Response:
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = UrllibGitHubTransport(token).request("POST", "/graphql", json_body={"query": "x"})
    assert result.status == 200
    assert captured["auth"] == f"Bearer {token}"
    assert token not in str(captured["url"])
    assert token not in str(result.body)


def test_transport_rejects_non_github_urls_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert main(_CLI_ARGS) == 2
    transport = UrllibGitHubTransport("t")
    with pytest.raises(TransportError):
        transport.request("GET", "https://evil.example.com/x")
    with pytest.raises(ValueError, match="https"):
        UrllibGitHubTransport("t", base_url="http://api.github.com")
    assert GITHUB_API_BASE == "https://api.github.com"

    def refused(request: urllib.request.Request, timeout: float = 0) -> object:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", refused)
    with pytest.raises(TransportError):
        transport.request("GET", "/repos/x/y/rulesets/1")

    def http_error(request: urllib.request.Request, timeout: float = 0) -> object:
        raise urllib.error.HTTPError(request.full_url, 404, "nf", Message(), io.BytesIO(b"{}"))

    monkeypatch.setattr("urllib.request.urlopen", http_error)
    assert transport.request("GET", "/repos/x/y/rulesets/1").status == 404
