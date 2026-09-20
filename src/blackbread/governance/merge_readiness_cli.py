"""Read-only merge-readiness CLI composing transport, collector, and evaluator.

Advisory only: it cannot merge, write to GitHub, enable auto-merge, alter a
branch, authorize execution, or advance engineering state. It emits exactly
one sanitized, deterministic, compact JSON line on stdout; exception text,
remote text, token material, paths, and raw evidence never reach stdout/stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from typing import Any, NoReturn

from blackbread.governance import github_merge_normalization as norm
from blackbread.governance.delivery_contract_loader import (
    ContractValidationError,
    load_delivery_contract,
)
from blackbread.governance.github_merge_evidence import (
    EvidenceCollectionError,
    GitHubMergeEvidenceCollector,
)
from blackbread.governance.github_merge_transport import (
    TransportError,
    UrllibGitHubReadTransport,
)
from blackbread.governance.merge_readiness import (
    DeliveryContract,
    MergeReadinessDecision,
    evaluate_merge_readiness,
)

_HEAD_SHA_RE = re.compile(r"[0-9a-f]{40}")

# The only evaluator outcomes that are substantive merge blockers (exit 1).
# Everything else -- missing, incomplete, or inconsistent evidence, identity
# drift, head mismatch, unknown remote states -- is a validity failure (exit 2).
_SUBSTANTIVE_BLOCKERS = frozenset(
    {
        "BLOCKING_MERGE_STATE",
        "CHANGES_REQUESTED",
        "CODE_SCANNING_ALERT",
        "CODE_SCANNING_ANALYSIS_ERROR",
        "CODE_SCANNING_ANALYSIS_MISSING",
        "CODE_SCANNING_ANALYSIS_STALE",
        "DRAFT_PULL_REQUEST",
        "INSUFFICIENT_APPROVALS",
        "REQUIRED_CHECK_FAILING",
        "REQUIRED_CHECK_INTEGRATION_MISMATCH",
        "REQUIRED_CHECK_MISSING",
        "REQUIRED_CHECK_STALE",
        "RULESET_BYPASS_ACTOR",
        "RULESET_CODE_SCANNING_DRIFT",
        "RULESET_ID_MISMATCH",
        "RULESET_INACTIVE",
        "RULESET_SCOPE_MISMATCH",
        "RULESET_STATUS_CHECK_DRIFT",
        "UNRESOLVED_REVIEW_THREAD",
    }
)


class _ArgumentError(Exception):
    """Internal marker so argparse failures bypass its stderr/exit path."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _ArgumentError from None


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _Parser(
        prog="python -m blackbread.governance.merge_readiness_cli",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--expected-head-sha", required=True)
    return parser.parse_args(argv)


def _emit(payload: dict[str, Any], exit_code: int) -> int:
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    return exit_code


def _error(code: str) -> int:
    payload = {"errors": [code], "ready": False, "schema_version": 1, "status": "error"}
    return _emit(payload, 2)


def _collect(
    args: argparse.Namespace, contract: DeliveryContract, token: str
) -> MergeReadinessDecision | int:
    """Compose transport -> collector -> evaluator; emit-and-return int on failure."""
    try:
        transport = UrllibGitHubReadTransport(token)
        collector = GitHubMergeEvidenceCollector(transport, args.repository)
        evidence = collector.collect(args.pull_request, contract)
        if evidence.incomplete_sections:
            return _error("EVIDENCE_INCOMPLETE")
        return evaluate_merge_readiness(contract, evidence, args.expected_head_sha)
    except TransportError:
        return _error("TRANSPORT_FAILURE")
    except (EvidenceCollectionError, norm.EvidenceNormalizationError) as exc:
        return _error(exc.code)
    except Exception:
        return _error("INTERNAL_ERROR")


def _emit_decision(args: argparse.Namespace, decision: MergeReadinessDecision) -> int:
    codes = sorted({blocker.code for blocker in decision.blockers})
    if "HEAD_SHA_MISMATCH" in codes:
        return _error("HEAD_SHA_MISMATCH")
    if decision.ready:
        status, blockers, exit_code = "ready", [], 0
    elif all(code in _SUBSTANTIVE_BLOCKERS for code in codes):
        status, blockers, exit_code = "not_ready", codes, 1
    else:
        return _error("UNCLASSIFIED_BLOCKER")
    payload = {
        "blockers": blockers,
        "expected_head_sha": args.expected_head_sha,
        "pull_request": args.pull_request,
        "ready": decision.ready,
        "repository": args.repository,
        "schema_version": 1,
        "status": status,
    }
    return _emit(payload, exit_code)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
    except _ArgumentError:
        return _error("CLI_ARGUMENTS_INVALID")
    if args.pull_request <= 0 or _HEAD_SHA_RE.fullmatch(args.expected_head_sha) is None:
        return _error("CLI_ARGUMENTS_INVALID")
    try:
        contract = load_delivery_contract()
    except ContractValidationError as exc:
        return _error(exc.code)
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return _error("MISSING_GITHUB_TOKEN")
    outcome = _collect(args, contract, token)
    if isinstance(outcome, int):
        return outcome
    return _emit_decision(args, outcome)


if __name__ == "__main__":
    raise SystemExit(main())
