"""Command-line interface for merge readiness evaluation."""

import argparse
import json
import os
import re
import sys
from typing import Any, NoReturn

from blackbread.governance import github_merge_normalization as norm
from blackbread.governance.github_merge_evidence import (
    EvidenceCollectionError,
    GitHubMergeEvidenceCollector,
)
from blackbread.governance.github_merge_transport import TransportError, UrllibGitHubReadTransport
from blackbread.governance.merge_readiness import (
    CodeScanningRequirement,
    DeliveryContract,
    RequiredStatusCheck,
    evaluate_merge_readiness,
)

_ALLOWED_EXIT_1_BLOCKERS = frozenset(
    {
        "REQUIRED_CHECK_MISSING",
        "REQUIRED_CHECK_INTEGRATION_MISMATCH",
        "REQUIRED_CHECK_STALE",
        "REQUIRED_CHECK_FAILING",
        "RULESET_ID_MISMATCH",
        "RULESET_INACTIVE",
        "RULESET_BYPASS_ACTOR",
        "RULESET_SCOPE_MISMATCH",
        "RULESET_STATUS_CHECK_DRIFT",
        "RULESET_CODE_SCANNING_DRIFT",
        "CODE_SCANNING_ANALYSIS_MISSING",
        "CODE_SCANNING_ANALYSIS_STALE",
        "CODE_SCANNING_ANALYSIS_ERROR",
        "CODE_SCANNING_ALERT",
        "CHANGES_REQUESTED",
        "INSUFFICIENT_APPROVALS",
        "UNRESOLVED_REVIEW_THREAD",
        "DRAFT_PULL_REQUEST",
        "BLOCKING_MERGE_STATE",
    }
)

_EXPECTED_ROOT_KEYS = frozenset({"schema_version", "agent_delivery"})
_EXPECTED_AD_KEYS = frozenset(
    {
        "owner_instruction_required",
        "feature_branch_commit_push_allowed",
        "pull_request_required",
        "direct_push_main_allowed",
        "force_push_allowed",
        "expected_head_sha_required",
        "required_approving_reviews",
        "require_code_owner_review",
        "require_last_push_approval",
        "require_extra_approval_for_unattributed_changes",
        "dismiss_stale_reviews",
        "require_review_thread_resolution",
        "allow_changes_requested",
        "require_ai_bot_comment_disposition",
        "require_branch_up_to_date",
        "required_status_checks",
        "required_code_scanning",
        "allow_blocking_debt",
        "ruleset_id",
    }
)


def _fail_exit_2(error_code: str) -> NoReturn:
    out = {"errors": [error_code], "ready": False, "schema_version": 1, "status": "error"}
    sys.stdout.write(json.dumps(out, sort_keys=True, separators=(",", ":")) + "\n")
    sys.exit(2)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    d: dict[str, Any] = {}
    for k, v in pairs:
        if k in d:
            raise ValueError(f"Duplicate key: {k}")
        d[k] = v
    return d


def _check_type(val: Any, expected: type) -> None:
    if type(val) is not expected:
        _fail_exit_2("CONTRACT_INVALID_TYPE")


def _parse_status_checks(raw_checks: Any) -> tuple[RequiredStatusCheck, ...]:
    _check_type(raw_checks, list)
    parsed = []
    seen = set()
    for rc in raw_checks:
        _check_type(rc, dict)
        if set(rc.keys()) != {"context", "integration_id"}:
            _fail_exit_2("CONTRACT_INVALID_STATUS_CHECK")
        _check_type(rc["context"], str)
        if not rc["context"].strip():
            _fail_exit_2("CONTRACT_INVALID_STATUS_CHECK")
        if rc["integration_id"] is not None:
            _check_type(rc["integration_id"], int)
            if rc["integration_id"] <= 0:
                _fail_exit_2("CONTRACT_INVALID_STATUS_CHECK")
        key = (rc["context"], rc["integration_id"])
        if key in seen:
            _fail_exit_2("CONTRACT_INVALID_STATUS_CHECK")
        seen.add(key)
        parsed.append(
            RequiredStatusCheck(context=rc["context"], integration_id=rc["integration_id"])
        )
    return tuple(parsed)


def _parse_code_scanning(raw_scans: Any) -> tuple[CodeScanningRequirement, ...]:
    _check_type(raw_scans, list)
    parsed = []
    seen = set()
    valid_thresholds = {"none", "errors", "errors_and_warnings", "all"}
    for rs in raw_scans:
        _check_type(rs, dict)
        if set(rs.keys()) != {"tool", "security_alerts_threshold", "alerts_threshold"}:
            _fail_exit_2("CONTRACT_INVALID_CODE_SCANNING")
        _check_type(rs["tool"], str)
        if not rs["tool"].strip():
            _fail_exit_2("CONTRACT_INVALID_CODE_SCANNING")
        _check_type(rs["security_alerts_threshold"], str)
        _check_type(rs["alerts_threshold"], str)
        if rs["security_alerts_threshold"] not in valid_thresholds or rs["alerts_threshold"] not in valid_thresholds:
            _fail_exit_2("CONTRACT_INVALID_CODE_SCANNING")
        if rs["tool"] in seen:
            _fail_exit_2("CONTRACT_INVALID_CODE_SCANNING")
        seen.add(rs["tool"])
        parsed.append(
            CodeScanningRequirement(
                tool=rs["tool"],
                security_alerts_threshold=rs["security_alerts_threshold"],
                alerts_threshold=rs["alerts_threshold"],
            )
        )
    return tuple(parsed)


def _load_contract() -> DeliveryContract:
    try:
        with open(".github/agent-delivery.json", encoding="utf-8") as f:
            data = json.load(f, object_pairs_hook=_reject_duplicates)
    except FileNotFoundError:
        _fail_exit_2("CONTRACT_NOT_FOUND")
    except ValueError:
        _fail_exit_2("CONTRACT_MALFORMED_JSON")
    except Exception:
        _fail_exit_2("CONTRACT_READ_ERROR")

    _check_type(data, dict)
    if set(data.keys()) != _EXPECTED_ROOT_KEYS:
        _fail_exit_2("CONTRACT_ROOT_KEYS_INVALID")

    schema_version = data["schema_version"]
    _check_type(schema_version, int)
    if schema_version != 3:  # noqa: PLR2004
        _fail_exit_2("CONTRACT_UNSUPPORTED_SCHEMA")

    ad = data["agent_delivery"]
    _check_type(ad, dict)
    if set(ad.keys()) != _EXPECTED_AD_KEYS:
        _fail_exit_2("CONTRACT_KEYS_INVALID")

    for k in _EXPECTED_AD_KEYS:
        if k not in {
            "required_status_checks",
            "required_code_scanning",
            "required_approving_reviews",
            "ruleset_id",
        }:
            _check_type(ad[k], bool)

    _check_type(ad["required_approving_reviews"], int)
    if ad["required_approving_reviews"] < 0:
        _fail_exit_2("CONTRACT_INVALID_REVIEWS")
    _check_type(ad["ruleset_id"], int)
    if ad["ruleset_id"] <= 0:
        _fail_exit_2("CONTRACT_INVALID_RULESET")

    return DeliveryContract(
        schema_version=schema_version,
        ruleset_id=ad["ruleset_id"],
        required_approving_reviews=ad["required_approving_reviews"],
        require_review_thread_resolution=ad["require_review_thread_resolution"],
        allow_changes_requested=ad["allow_changes_requested"],
        required_status_checks=_parse_status_checks(ad["required_status_checks"]),
        required_code_scanning=_parse_code_scanning(ad["required_code_scanning"]),
    )


def _emit_ready_exit_0(args: argparse.Namespace) -> NoReturn:
    out = {
        "blockers": [],
        "expected_head_sha": args.expected_head_sha,
        "pull_request": args.pull_request,
        "ready": True,
        "repository": args.repository,
        "schema_version": 1,
        "status": "ready",
    }
    sys.stdout.write(json.dumps(out, sort_keys=True, separators=(",", ":")) + "\n")
    sys.exit(0)


def _emit_not_ready_exit_1(args: argparse.Namespace, blocker_codes: list[str]) -> NoReturn:
    out = {
        "blockers": blocker_codes,
        "expected_head_sha": args.expected_head_sha,
        "pull_request": args.pull_request,
        "ready": False,
        "repository": args.repository,
        "schema_version": 1,
        "status": "not_ready",
    }
    sys.stdout.write(json.dumps(out, sort_keys=True, separators=(",", ":")) + "\n")
    sys.exit(1)


class _StrictParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        _fail_exit_2("CLI_ARGUMENTS_INVALID")

_SHA_REGEX = re.compile(r"^[0-9a-f]{40}$")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = _StrictParser(description="Merge Readiness CLI")
    parser.add_argument("--repository", required=True, type=str)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--expected-head-sha", required=True, type=str)

    try:
        return parser.parse_args(argv)
    except Exception:
        _fail_exit_2("CLI_ARGUMENTS_INVALID")

def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    if not _SHA_REGEX.match(args.expected_head_sha):
        _fail_exit_2("CLI_ARGUMENTS_INVALID")

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        _fail_exit_2("MISSING_GITHUB_TOKEN")

    try:
        contract = _load_contract()
        transport = UrllibGitHubReadTransport(token)
        collector = GitHubMergeEvidenceCollector(transport, args.repository)

        evidence = collector.collect(args.pull_request, contract)
        if evidence.incomplete_sections:
            _fail_exit_2("EVIDENCE_INCOMPLETE")

        decision = evaluate_merge_readiness(contract, evidence, args.expected_head_sha)

        blocker_codes = sorted({b.code for b in decision.blockers})
        if "HEAD_SHA_MISMATCH" in blocker_codes:
            _fail_exit_2("HEAD_SHA_MISMATCH")

        if decision.ready:
            _emit_ready_exit_0(args)

        all_allowlisted = all(code in _ALLOWED_EXIT_1_BLOCKERS for code in blocker_codes)

        if not all_allowlisted:
            _fail_exit_2("UNCLASSIFIED_BLOCKER")

        _emit_not_ready_exit_1(args, blocker_codes)

    except TransportError:
        _fail_exit_2("TRANSPORT_FAILURE")
    except EvidenceCollectionError:
        _fail_exit_2("EVIDENCE_COLLECTION_FAILURE")
    except norm.EvidenceNormalizationError:
        _fail_exit_2("NORMALIZATION_FAILURE")
    except Exception:
        _fail_exit_2("INTERNAL_ERROR")


if __name__ == "__main__":
    main()
