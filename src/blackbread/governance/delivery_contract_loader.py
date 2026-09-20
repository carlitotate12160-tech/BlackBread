"""Strict loader for the schema-v3 agent-delivery contract.

Decodes and validates ``.github/agent-delivery.json`` from the trusted
repository checkout (resolved from this module, never the caller's working
directory), enforces the supported static delivery policy, and constructs the
immutable ``DeliveryContract``. Every rejection raises a sanitized
``ContractValidationError``; the loader never writes, exits, or does I/O
beyond the contract read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn

from blackbread.governance.merge_readiness import (
    CodeScanningRequirement,
    DeliveryContract,
    RequiredStatusCheck,
)

_SUPPORTED_SCHEMA_VERSION = 3
_STATUS_CHECK_KEYS = frozenset({"context", "integration_id"})
_CODE_SCANNING_KEYS = frozenset({"tool", "security_alerts_threshold", "alerts_threshold"})
_ROOT_KEYS = frozenset({"schema_version", "agent_delivery"})

# Fixed delivery-authority invariants: a contract that weakens them is
# unsupported regardless of how the evaluator would score it. Fields the
# evaluator consumes (review thread resolution, changes-requested, branch
# currency, approvals, checks, scanning) are validated and passed through.
_STATIC_POLICY: dict[str, bool] = {
    "owner_instruction_required": True,
    "feature_branch_commit_push_allowed": True,
    "pull_request_required": True,
    "direct_push_main_allowed": False,
    "force_push_allowed": False,
    "expected_head_sha_required": True,
    "require_code_owner_review": False,
    "require_last_push_approval": False,
    "require_extra_approval_for_unattributed_changes": False,
    "dismiss_stale_reviews": True,
    "require_ai_bot_comment_disposition": False,
    "allow_blocking_debt": False,
}
_EVALUATED_KEYS = frozenset(
    {
        "required_approving_reviews",
        "require_review_thread_resolution",
        "allow_changes_requested",
        "require_branch_up_to_date",
        "required_status_checks",
        "required_code_scanning",
        "ruleset_id",
    }
)
_DELIVERY_KEYS = frozenset(_STATIC_POLICY) | _EVALUATED_KEYS
_SECURITY_THRESHOLDS = frozenset({"none", "all", "medium_or_higher", "high_or_higher", "critical"})
_ALERTS_THRESHOLDS = frozenset({"none", "all", "errors_and_warnings", "errors"})


class ContractValidationError(Exception):
    """Sanitized contract rejection; ``code`` is a stable machine code."""

    def __init__(self, code: str) -> None:
        super().__init__(f"delivery contract rejected: {code}")
        self.code = code


def _fail(code: str) -> NoReturn:
    raise ContractValidationError(code) from None


def default_contract_path() -> Path:
    """The contract inside the trusted checkout, independent of any CWD."""
    return Path(__file__).resolve().parents[3] / ".github" / "agent-delivery.json"


def load_delivery_contract(path: Path | None = None) -> DeliveryContract:
    """Decode, strictly validate, and return the delivery contract."""
    data = _read_json(default_contract_path() if path is None else path)
    if not isinstance(data, dict) or frozenset(data) != _ROOT_KEYS:
        _fail("CONTRACT_ROOT_KEYS_INVALID")
    version = data["schema_version"]
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version != _SUPPORTED_SCHEMA_VERSION
    ):
        _fail("CONTRACT_SCHEMA_VERSION_INVALID")
    delivery = data["agent_delivery"]
    if not isinstance(delivery, dict) or frozenset(delivery) != _DELIVERY_KEYS:
        _fail("CONTRACT_DELIVERY_INVALID")
    _enforce_static_policy(delivery)
    reviews = _bounded_int(delivery["required_approving_reviews"], "CONTRACT_REVIEWS_INVALID", 0)
    ruleset_id = _bounded_int(delivery["ruleset_id"], "CONTRACT_RULESET_ID_INVALID", 1)
    thread_resolution = _strict_bool(delivery["require_review_thread_resolution"])
    changes_requested = _strict_bool(delivery["allow_changes_requested"])
    branch_currency = _strict_bool(delivery["require_branch_up_to_date"])
    return DeliveryContract(
        schema_version=version,
        ruleset_id=ruleset_id,
        required_approving_reviews=reviews,
        require_review_thread_resolution=thread_resolution,
        allow_changes_requested=changes_requested,
        require_branch_up_to_date=branch_currency,
        required_status_checks=_status_checks(delivery["required_status_checks"]),
        required_code_scanning=_code_scanning(delivery["required_code_scanning"]),
    )


def _read_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _fail("CONTRACT_NOT_FOUND")
    except UnicodeDecodeError:
        _fail("CONTRACT_MALFORMED_JSON")
    except OSError:
        _fail("CONTRACT_UNREADABLE")
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError:
        _fail("CONTRACT_MALFORMED_JSON")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, value in pairs:
        if key in decoded:
            _fail("CONTRACT_DUPLICATE_KEY")
        decoded[key] = value
    return decoded


def _strict_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        _fail("CONTRACT_BOOLEAN_INVALID")
    return value


def _bounded_int(value: Any, code: str, minimum: int) -> int:
    # bool is an int subclass; it must never satisfy an integer field.
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        _fail(code)
    return value


def _enforce_static_policy(delivery: dict[str, Any]) -> None:
    for field, expected in _STATIC_POLICY.items():
        value = delivery[field]
        if not isinstance(value, bool):
            _fail("CONTRACT_BOOLEAN_INVALID")
        if value is not expected:
            _fail("CONTRACT_UNSUPPORTED_POLICY")


def _status_checks(raw: Any) -> tuple[RequiredStatusCheck, ...]:
    if not isinstance(raw, list):
        _fail("CONTRACT_STATUS_CHECKS_INVALID")
    checks: list[RequiredStatusCheck] = []
    seen: set[tuple[str, int | None]] = set()
    for item in raw:
        if not isinstance(item, dict) or frozenset(item) != _STATUS_CHECK_KEYS:
            _fail("CONTRACT_STATUS_CHECKS_INVALID")
        context = item["context"]
        if not isinstance(context, str) or not context.strip():
            _fail("CONTRACT_STATUS_CHECKS_INVALID")
        integration_id = item["integration_id"]
        if integration_id is not None:
            _bounded_int(integration_id, "CONTRACT_STATUS_CHECKS_INVALID", 1)
        key = (context, integration_id)
        if key in seen:
            _fail("CONTRACT_STATUS_CHECKS_INVALID")
        seen.add(key)
        checks.append(RequiredStatusCheck(context, integration_id))
    return tuple(checks)


def _code_scanning(raw: Any) -> tuple[CodeScanningRequirement, ...]:
    if not isinstance(raw, list):
        _fail("CONTRACT_CODE_SCANNING_INVALID")
    requirements: list[CodeScanningRequirement] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or frozenset(item) != _CODE_SCANNING_KEYS:
            _fail("CONTRACT_CODE_SCANNING_INVALID")
        tool = item["tool"]
        security = item["security_alerts_threshold"]
        alerts = item["alerts_threshold"]
        if not isinstance(tool, str) or not tool.strip():
            _fail("CONTRACT_CODE_SCANNING_INVALID")
        if security not in _SECURITY_THRESHOLDS or alerts not in _ALERTS_THRESHOLDS:
            _fail("CONTRACT_CODE_SCANNING_INVALID")
        if tool in seen:
            _fail("CONTRACT_CODE_SCANNING_INVALID")
        seen.add(tool)
        requirements.append(CodeScanningRequirement(tool, security, alerts))
    return tuple(requirements)
