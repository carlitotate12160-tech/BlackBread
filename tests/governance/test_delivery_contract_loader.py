"""Strict-validation proofs for the schema-v3 delivery contract loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from blackbread.governance.delivery_contract_loader import (
    ContractValidationError,
    default_contract_path,
    load_delivery_contract,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _delivery_dict(**overrides: Any) -> dict[str, Any]:
    delivery: dict[str, Any] = {
        "owner_instruction_required": True,
        "feature_branch_commit_push_allowed": True,
        "pull_request_required": True,
        "direct_push_main_allowed": False,
        "force_push_allowed": False,
        "expected_head_sha_required": True,
        "required_approving_reviews": 0,
        "require_code_owner_review": False,
        "require_last_push_approval": False,
        "require_extra_approval_for_unattributed_changes": False,
        "dismiss_stale_reviews": True,
        "require_review_thread_resolution": True,
        "allow_changes_requested": False,
        "require_ai_bot_comment_disposition": False,
        "require_branch_up_to_date": True,
        "required_status_checks": [
            {"context": "ci-ok", "integration_id": 15368},
            {"context": "GitGuardian Security Checks", "integration_id": 46505},
        ],
        "required_code_scanning": [
            {
                "tool": "CodeQL",
                "security_alerts_threshold": "high_or_higher",
                "alerts_threshold": "errors",
            }
        ],
        "allow_blocking_debt": False,
        "ruleset_id": 21644438,
    }
    delivery.update(overrides)
    return delivery


_UNSET = object()


def _contract_dict(delivery: Any = _UNSET) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "agent_delivery": _delivery_dict() if delivery is _UNSET else delivery,
    }


def _write(tmp_path: Path, payload: Any, *, raw: bool = False) -> Path:
    path = tmp_path / "agent-delivery.json"
    text = payload if raw else json.dumps(payload)
    path.write_text(text, encoding="utf-8")
    return path


def _code(excinfo: pytest.ExceptionInfo[ContractValidationError]) -> str:
    return excinfo.value.code


def test_loads_trusted_contract_from_repository_checkout() -> None:
    contract = load_delivery_contract()

    assert contract.schema_version == 3
    assert contract.ruleset_id == 21644438
    assert contract.require_branch_up_to_date is True
    contexts = {check.context for check in contract.required_status_checks}
    assert contexts == {"ci-ok", "GitGuardian Security Checks"}
    tools = {scan.tool for scan in contract.required_code_scanning}
    assert tools == {"CodeQL"}


def test_default_path_ignores_cwd_decoy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    decoy = tmp_path / ".github" / "agent-delivery.json"
    decoy.parent.mkdir(parents=True)
    decoy.write_text("{not json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    contract = load_delivery_contract()

    assert contract.ruleset_id == 21644438
    assert (
        default_contract_path() == (REPOSITORY_ROOT / ".github" / "agent-delivery.json").resolve()
    )


def test_missing_contract_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(tmp_path / "absent.json")
    assert _code(excinfo) == "CONTRACT_NOT_FOUND"


def test_malformed_json_fails_closed(tmp_path: Path) -> None:
    path = _write(tmp_path, "{not json", raw=True)
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_MALFORMED_JSON"


def test_invalid_utf8_is_malformed_not_uncaught(tmp_path: Path) -> None:
    path = tmp_path / "agent-delivery.json"
    path.write_bytes(b'{"schema_version": 3, "agent_delivery": \xff\xfe}')
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_MALFORMED_JSON"


def test_duplicate_root_keys_fail_closed(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '{"schema_version": 3, "schema_version": 3, "agent_delivery": {}}',
        raw=True,
    )
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_DUPLICATE_KEY"


def test_duplicate_nested_keys_fail_closed(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '{"schema_version": 3, "agent_delivery": {"ruleset_id": 1, "ruleset_id": 2}}',
        raw=True,
    )
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_DUPLICATE_KEY"


@pytest.mark.parametrize("payload", [[], "text", 3, None])
def test_non_object_root_fails_closed(tmp_path: Path, payload: Any) -> None:
    path = _write(tmp_path, payload)
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_ROOT_KEYS_INVALID"


@pytest.mark.parametrize("root", [{"schema_version": 3}, {"agent_delivery": {}}])
def test_root_key_set_must_be_exact(tmp_path: Path, root: dict[str, Any]) -> None:
    root["extra"] = True
    path = _write(tmp_path, root)
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_ROOT_KEYS_INVALID"


@pytest.mark.parametrize("version", [2, 4, "3", 3.0, True, None])
def test_schema_version_must_be_integer_three(tmp_path: Path, version: Any) -> None:
    path = _write(tmp_path, {"schema_version": version, "agent_delivery": _delivery_dict()})
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_SCHEMA_VERSION_INVALID"


@pytest.mark.parametrize("delivery", [[], "text", None])
def test_agent_delivery_must_be_object(tmp_path: Path, delivery: Any) -> None:
    path = _write(tmp_path, _contract_dict(delivery))
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_DELIVERY_INVALID"


def test_agent_delivery_key_set_must_be_exact(tmp_path: Path) -> None:
    for mutation in ("missing", "extra"):
        delivery = _delivery_dict()
        if mutation == "missing":
            del delivery["ruleset_id"]
        else:
            delivery["surprise"] = True
        path = _write(tmp_path, _contract_dict(delivery))
        with pytest.raises(ContractValidationError) as excinfo:
            load_delivery_contract(path)
        assert _code(excinfo) == "CONTRACT_DELIVERY_INVALID"


_STATIC_POLICY_FIELDS = (
    "owner_instruction_required",
    "feature_branch_commit_push_allowed",
    "pull_request_required",
    "direct_push_main_allowed",
    "force_push_allowed",
    "expected_head_sha_required",
    "require_code_owner_review",
    "require_last_push_approval",
    "require_extra_approval_for_unattributed_changes",
    "dismiss_stale_reviews",
    "require_ai_bot_comment_disposition",
    "allow_blocking_debt",
)

_EVALUATED_BOOLEAN_FIELDS = (
    "require_review_thread_resolution",
    "allow_changes_requested",
    "require_branch_up_to_date",
)


@pytest.mark.parametrize("field", _STATIC_POLICY_FIELDS)
def test_static_policy_value_is_fixed(tmp_path: Path, field: str) -> None:
    delivery = _delivery_dict(**{field: not _delivery_dict()[field]})
    path = _write(tmp_path, _contract_dict(delivery))
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_UNSUPPORTED_POLICY"


@pytest.mark.parametrize("field", _STATIC_POLICY_FIELDS + _EVALUATED_BOOLEAN_FIELDS)
@pytest.mark.parametrize("value", ["true", 1, 0, None, [], {}])
def test_every_boolean_field_rejects_non_bool(tmp_path: Path, field: str, value: Any) -> None:
    delivery = _delivery_dict(**{field: value})
    path = _write(tmp_path, _contract_dict(delivery))
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_BOOLEAN_INVALID"


def test_require_branch_up_to_date_flows_into_contract(tmp_path: Path) -> None:
    delivery = _delivery_dict(require_branch_up_to_date=False)
    path = _write(tmp_path, _contract_dict(delivery))

    contract = load_delivery_contract(path)

    assert contract.require_branch_up_to_date is False


@pytest.mark.parametrize("value", [True, "0", -1, 1.5, None])
def test_required_approving_reviews_must_be_non_negative_int(tmp_path: Path, value: Any) -> None:
    delivery = _delivery_dict(required_approving_reviews=value)
    path = _write(tmp_path, _contract_dict(delivery))
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_REVIEWS_INVALID"


@pytest.mark.parametrize("value", [False, 0, -9, "21644438", None])
def test_ruleset_id_must_be_positive_int(tmp_path: Path, value: Any) -> None:
    delivery = _delivery_dict(ruleset_id=value)
    path = _write(tmp_path, _contract_dict(delivery))
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_RULESET_ID_INVALID"


@pytest.mark.parametrize(
    "checks",
    [
        "ci-ok",
        [{"context": "ci-ok"}],
        [{"context": "ci-ok", "integration_id": 1, "extra": 1}],
        [{"context": "  ", "integration_id": 1}],
        [{"context": 7, "integration_id": 1}],
        [{"context": "ci-ok", "integration_id": True}],
        [{"context": "ci-ok", "integration_id": 0}],
        [{"context": "ci-ok", "integration_id": "15368"}],
        [
            {"context": "ci-ok", "integration_id": 15368},
            {"context": "ci-ok", "integration_id": 15368},
        ],
    ],
)
def test_required_status_checks_strict(tmp_path: Path, checks: Any) -> None:
    delivery = _delivery_dict(required_status_checks=checks)
    path = _write(tmp_path, _contract_dict(delivery))
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_STATUS_CHECKS_INVALID"


@pytest.mark.parametrize(
    "scanning",
    [
        "CodeQL",
        [{"tool": "CodeQL"}],
        [{"tool": "CodeQL", "security_alerts_threshold": "all", "alerts_threshold": "all", "x": 1}],
        [{"tool": " ", "security_alerts_threshold": "all", "alerts_threshold": "all"}],
        [{"tool": "CodeQL", "security_alerts_threshold": "bogus", "alerts_threshold": "all"}],
        [{"tool": "CodeQL", "security_alerts_threshold": "all", "alerts_threshold": "bogus"}],
        [{"tool": "CodeQL", "security_alerts_threshold": None, "alerts_threshold": "all"}],
        [
            {
                "tool": "CodeQL",
                "security_alerts_threshold": "all",
                "alerts_threshold": "all",
            },
            {
                "tool": "CodeQL",
                "security_alerts_threshold": "none",
                "alerts_threshold": "none",
            },
        ],
    ],
)
def test_required_code_scanning_strict(tmp_path: Path, scanning: Any) -> None:
    delivery = _delivery_dict(required_code_scanning=scanning)
    path = _write(tmp_path, _contract_dict(delivery))
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_CODE_SCANNING_INVALID"


@pytest.mark.parametrize("field", ["security_alerts_threshold", "alerts_threshold"])
@pytest.mark.parametrize("value", [[], {}, None, 7, True])
def test_non_string_thresholds_fail_closed(tmp_path: Path, field: str, value: Any) -> None:
    item = {
        "tool": "CodeQL",
        "security_alerts_threshold": "all",
        "alerts_threshold": "all",
        field: value,
    }
    delivery = _delivery_dict(required_code_scanning=[item])
    path = _write(tmp_path, _contract_dict(delivery))
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    assert _code(excinfo) == "CONTRACT_CODE_SCANNING_INVALID"


def test_error_message_never_embeds_input(tmp_path: Path) -> None:
    hostile = _delivery_dict(ruleset_id="D:\\secret\\path ghp_token123")
    path = _write(tmp_path, _contract_dict(hostile))
    with pytest.raises(ContractValidationError) as excinfo:
        load_delivery_contract(path)
    message = str(excinfo.value)
    assert "secret" not in message
    assert "ghp_token123" not in message
    assert excinfo.value.code == "CONTRACT_RULESET_ID_INVALID"
