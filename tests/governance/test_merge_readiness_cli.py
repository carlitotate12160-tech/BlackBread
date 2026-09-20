"""Composition, output, and exit-code proofs for the merge-readiness CLI."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from collections.abc import Sequence
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pytest

import blackbread.governance.merge_readiness_cli as cli
from blackbread.governance.delivery_contract_loader import (
    ContractValidationError,
    load_delivery_contract,
)
from blackbread.governance.github_merge_evidence import EvidenceCollectionError
from blackbread.governance.github_merge_normalization import EvidenceNormalizationError
from blackbread.governance.github_merge_transport import TransportError
from blackbread.governance.merge_readiness import (
    CheckRunEvidence,
    CodeScanningAnalysis,
    CodeScanningEvidence,
    DeliveryContract,
    MergeEvidence,
    PullRequestIdentity,
    RulesetEvidence,
)

HEAD_SHA = "a" * 40
OTHER_SHA = "b" * 40
BASE_SHA = "c" * 40
MERGE_SHA = "d" * 40
PR_NUMBER = 104
REPOSITORY = "carlitotate12160-tech/BlackBread"

_ARGV = [
    "--repository",
    REPOSITORY,
    "--pull-request",
    str(PR_NUMBER),
    "--expected-head-sha",
    HEAD_SHA,
]


def _identity() -> PullRequestIdentity:
    return PullRequestIdentity(
        number=PR_NUMBER,
        head_sha=HEAD_SHA,
        base_sha=BASE_SHA,
        base_ref="main",
        potential_merge_sha=MERGE_SHA,
    )


def _ready_evidence() -> MergeEvidence:
    contract = load_delivery_contract()
    identity = _identity()
    return MergeEvidence(
        pull_request_before=identity,
        pull_request_after=identity,
        is_draft=False,
        merge_state="CLEAN",
        check_runs=(
            CheckRunEvidence("ci-ok", 15368, HEAD_SHA, "success"),
            CheckRunEvidence("GitGuardian Security Checks", 46505, HEAD_SHA, "success"),
        ),
        ruleset=RulesetEvidence(
            ruleset_id=21644438,
            enforcement="active",
            bypass_actors=(),
            status_checks=contract.required_status_checks,
            code_scanning=contract.required_code_scanning,
            target="branch",
            included_refs=("refs/heads/main",),
            excluded_refs=(),
            strict_branch_currency=True,
        ),
        code_scanning=CodeScanningEvidence(
            analyses=(CodeScanningAnalysis("CodeQL", HEAD_SHA, ""),),
            alerts=(),
            queried_ref=f"refs/pull/{PR_NUMBER}/head",
        ),
        review_states=(),
        review_threads=(),
        incomplete_sections=frozenset(),
    )


class _FakeTransport:
    """Records construction; exposes no usable network surface."""

    def __init__(self, token: str, calls: list[str]) -> None:
        calls.append(f"transport:{token}")


class _FakeCollector:
    """Returns canned evidence or raises; records collect() arguments."""

    def __init__(
        self,
        transport: Any,
        repository: str,
        calls: list[str],
        evidence: MergeEvidence | None,
        error: Exception | None,
    ) -> None:
        calls.append(f"collector:{repository}:{type(transport).__name__}")
        self._calls = calls
        self._evidence = evidence
        self._error = error

    def collect(self, pull_request: int, contract: DeliveryContract) -> MergeEvidence:
        self._calls.append(f"collect:{pull_request}:{contract.ruleset_id}")
        if self._error is not None:
            raise self._error
        assert self._evidence is not None
        return self._evidence


@pytest.fixture
def seam_state() -> dict[str, Any]:
    """Mutable evidence/error knobs shared with the fake collector."""
    return {"evidence": _ready_evidence(), "error": None}


@pytest.fixture
def bound(monkeypatch: pytest.MonkeyPatch, seam_state: dict[str, Any]) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(
        cli,
        "UrllibGitHubReadTransport",
        lambda token: _FakeTransport(token, calls),
    )
    monkeypatch.setattr(
        cli,
        "GitHubMergeEvidenceCollector",
        lambda transport, repository: _FakeCollector(
            transport, repository, calls, seam_state["evidence"], seam_state["error"]
        ),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "unit-test-token")
    return calls


def _run(argv: Sequence[str] | None = None) -> tuple[int, dict[str, Any], str]:
    """Run main(); returns (exit, parsed stdout JSON, raw stdout)."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.main(list(argv) if argv is not None else list(_ARGV))
    raw = buffer.getvalue()
    return code, json.loads(raw), raw


def test_ready_emits_deterministic_compact_json_and_exit_zero(
    bound: list[str],
) -> None:
    code, payload, raw = _run()

    assert code == 0
    assert payload == {
        "blockers": [],
        "expected_head_sha": HEAD_SHA,
        "pull_request": PR_NUMBER,
        "ready": True,
        "repository": REPOSITORY,
        "schema_version": 1,
        "status": "ready",
    }
    assert raw == json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def test_composition_order_and_exact_argument_flow(bound: list[str]) -> None:
    _run()

    collector_call = f"collector:{REPOSITORY}:_FakeTransport"
    collect_call = f"collect:{PR_NUMBER}:21644438"
    assert "transport:unit-test-token" in bound
    assert collector_call in bound
    assert collect_call in bound
    assert (
        bound.index("transport:unit-test-token")
        < bound.index(collector_call)
        < bound.index(collect_call)
    )


def test_expected_head_sha_reaches_evaluator_unchanged(bound: list[str]) -> None:
    code, payload, _ = _run([*_ARGV[:-1], OTHER_SHA])

    assert code == 2
    assert payload["errors"] == ["HEAD_SHA_MISMATCH"]


def test_valid_not_ready_emits_sorted_blockers_and_exit_one(
    bound: list[str], seam_state: dict[str, Any]
) -> None:
    evidence = _ready_evidence()
    seam_state["evidence"] = MergeEvidence(
        pull_request_before=evidence.pull_request_before,
        pull_request_after=evidence.pull_request_after,
        is_draft=True,
        merge_state="BLOCKED",
        check_runs=evidence.check_runs,
        ruleset=evidence.ruleset,
        code_scanning=evidence.code_scanning,
        review_states=evidence.review_states,
        review_threads=(False,),
        incomplete_sections=frozenset(),
    )

    code, payload, _ = _run()

    assert code == 1
    assert payload["status"] == "not_ready"
    assert payload["ready"] is False
    assert payload["blockers"] == [
        "BLOCKING_MERGE_STATE",
        "DRAFT_PULL_REQUEST",
        "UNRESOLVED_REVIEW_THREAD",
    ]


def test_incomplete_evidence_is_exit_two(bound: list[str], seam_state: dict[str, Any]) -> None:
    evidence = _ready_evidence()
    seam_state["evidence"] = MergeEvidence(
        pull_request_before=evidence.pull_request_before,
        pull_request_after=evidence.pull_request_after,
        is_draft=evidence.is_draft,
        merge_state=evidence.merge_state,
        check_runs=evidence.check_runs,
        ruleset=evidence.ruleset,
        code_scanning=evidence.code_scanning,
        review_states=evidence.review_states,
        review_threads=evidence.review_threads,
        incomplete_sections=frozenset({"check_runs"}),
    )

    code, payload, _ = _run()

    assert code == 2
    assert payload["errors"] == ["EVIDENCE_INCOMPLETE"]


def test_missing_evidence_section_is_exit_two(bound: list[str], seam_state: dict[str, Any]) -> None:
    evidence = _ready_evidence()
    seam_state["evidence"] = MergeEvidence(
        pull_request_before=evidence.pull_request_before,
        pull_request_after=evidence.pull_request_after,
        is_draft=evidence.is_draft,
        merge_state=evidence.merge_state,
        check_runs=None,
        ruleset=evidence.ruleset,
        code_scanning=evidence.code_scanning,
        review_states=evidence.review_states,
        review_threads=evidence.review_threads,
        incomplete_sections=frozenset(),
    )

    code, payload, _ = _run()

    assert code == 2
    assert payload["errors"] == ["UNCLASSIFIED_BLOCKER"]


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--repository", REPOSITORY],
        [*_ARGV[:4], "not-a-number", "--expected-head-sha", HEAD_SHA],
        ["--repository", REPOSITORY, "--pull-request", "0", "--expected-head-sha", HEAD_SHA],
        ["--repository", REPOSITORY, "--pull-request", "-7", "--expected-head-sha", HEAD_SHA],
        [*_ARGV[:-1], HEAD_SHA.upper()],
        [*_ARGV[:-1], "a" * 39],
        [*_ARGV[:-1], "g" * 40],
        [*_ARGV, "--unrecognized"],
    ],
)
def test_invalid_arguments_fail_before_transport(bound: list[str], argv: list[str]) -> None:
    code, payload, _ = _run(argv)

    assert code == 2
    assert payload["errors"] == ["CLI_ARGUMENTS_INVALID"]
    assert not any(call.startswith("transport:") for call in bound)


def test_missing_token_fails_before_transport(
    monkeypatch: pytest.MonkeyPatch, bound: list[str]
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN")

    code, payload, _ = _run()

    assert code == 2
    assert payload["errors"] == ["MISSING_GITHUB_TOKEN"]
    assert not any(call.startswith("transport:") for call in bound)


def test_contract_failure_precedes_transport(
    bound: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_invalid() -> DeliveryContract:
        raise ContractValidationError("CONTRACT_MALFORMED_JSON")

    monkeypatch.setattr(cli, "load_delivery_contract", raise_invalid)

    code, payload, _ = _run()

    assert code == 2
    assert payload["errors"] == ["CONTRACT_MALFORMED_JSON"]
    assert not any(call.startswith("transport:") for call in bound)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TransportError("unexpected HTTP status", status=503), "TRANSPORT_FAILURE"),
        (EvidenceCollectionError("INVALID_REPOSITORY"), "INVALID_REPOSITORY"),
        (EvidenceNormalizationError("MALFORMED_BODY"), "MALFORMED_BODY"),
    ],
)
def test_collection_failures_are_exit_two(
    bound: list[str], seam_state: dict[str, Any], error: Exception, expected: str
) -> None:
    seam_state["error"] = error

    code, payload, _ = _run()

    assert code == 2
    assert payload["errors"] == [expected]


def test_unknown_exception_is_sanitized(bound: list[str], seam_state: dict[str, Any]) -> None:
    seam_state["error"] = RuntimeError("hostile ghp_secret123 D:\\path details")

    code, payload, raw = _run()

    assert code == 2
    assert payload["errors"] == ["INTERNAL_ERROR"]
    assert "ghp_secret123" not in raw
    assert "hostile" not in raw


def test_token_never_reaches_output(
    bound: list[str], seam_state: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    seam_state["error"] = TransportError("network request failed")

    code, _, _ = _run()

    captured = capsys.readouterr()
    assert code == 2
    assert "unit-test-token" not in captured.out
    assert captured.err == ""


def test_cwd_decoy_contract_is_ignored(
    bound: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = tmp_path / ".github" / "agent-delivery.json"
    decoy.parent.mkdir(parents=True)
    decoy.write_text('{"schema_version": 2, "agent_delivery": {}}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    code, payload, _ = _run()

    assert code == 0
    assert payload["status"] == "ready"


def test_module_entrypoint_exits_two_without_network() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "blackbread.governance.merge_readiness_cli"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["errors"] == ["CLI_ARGUMENTS_INVALID"]
