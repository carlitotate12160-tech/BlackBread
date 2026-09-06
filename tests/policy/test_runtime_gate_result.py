"""Strict, digest-bound, non-executable RuntimeGateResult v1 contract."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from blackbread.policy.runtime_result import (
    OUTCOME_BY_REASON,
    RUNTIME_GATE_RESULT_SCHEMA,
    RUNTIME_GATE_RESULT_SCHEMA_VERSION,
    RuntimeGateResult,
)

PASSED = "PASSED_FOR_FINAL_DECISION"
EVALUATED_AT = datetime(2026, 9, 3, 12, 5, tzinfo=UTC)

EXPECTED_OUTCOME_BY_REASON = {
    "ADMISSION_BINDING_MISMATCH": "DENY",
    "RUNTIME_BINDING_MISMATCH": "DENY",
    "CAPABILITY_BINDING_MISMATCH": "DENY",
    "ADMISSION_NOT_ADMITTED": "DENY",
    "PROPOSAL_NOT_YET_VALID": "STALE_CONTEXT",
    "PROPOSAL_EXPIRED": "STALE_CONTEXT",
    "ENGAGEMENT_STATE_MISSING": "STALE_CONTEXT",
    "RUNTIME_CONTEXT_INCOHERENT": "STALE_CONTEXT",
    "ENGAGEMENT_STOPPED": "ENGAGEMENT_STOPPED",
    "OPSEC_STATE_MISSING": "OPSEC_HOLD",
    "OPSEC_BURNED": "OPSEC_HOLD",
    "OPSEC_HOT": "OPSEC_HOLD",
    "RUNTIME_SNAPSHOT_NOT_YET_VALID": "STALE_CONTEXT",
    "RUNTIME_SNAPSHOT_EXPIRED": "STALE_CONTEXT",
    "OPSEC_STATE_EXPIRED": "STALE_CONTEXT",
    "BUDGET_STATE_MISSING": "STALE_CONTEXT",
    "BUDGET_WINDOW_EXPIRED": "STALE_CONTEXT",
    "LOCK_STATE_MISSING": "STALE_CONTEXT",
    "APPROVAL_MISSING": "APPROVAL_REQUIRED",
    "APPROVAL_CLASS_MISMATCH": "APPROVAL_REQUIRED",
    "APPROVAL_TARGET_MISMATCH": "APPROVAL_REQUIRED",
    "APPROVAL_NOT_YET_VALID": "APPROVAL_REQUIRED",
    "APPROVAL_EXPIRED": "APPROVAL_REQUIRED",
    "APPROVAL_REVOKED": "APPROVAL_REQUIRED",
    "BUDGET_DEADLINE_EXCEEDED": "DENY",
    "BUDGET_CAPACITY_EXCEEDED": "DENY",
    "RESOURCE_LOCK_HELD": "WAIT_FOR_RESOURCE",
}


def _fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "schema_name": "policy.runtime.gate.result",
        "schema_version": 1,
        "tenant_id": "tenant-a",
        "engagement_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "proposal_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "proposal_digest": "1" * 64,
        "agent_instance_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "admission_result_digest": "2" * 64,
        "runtime_snapshot_digest": "3" * 64,
        "registry_schema_version": 1,
        "registry_digest": "4" * 64,
        "capability_id": "scout.passive_asset_intelligence.v1",
        "supply_chain_digest": "5" * 64,
        "approval_class": "AUTO_WITH_MANIFEST",
        "network_path": "CONTROL_PLANE_PASSIVE",
        "requested_target_requests": 0,
        "requested_cost_microunits": 2_000_000,
        "requested_deadline_seconds": 30,
        "evaluated_at": EVALUATED_AT,
        "outcome": PASSED,
        "reason_code": None,
    }
    fields.update(overrides)
    return fields


def _result(**overrides: object) -> RuntimeGateResult:
    return RuntimeGateResult.build(_fields(**overrides))


def test_runtime_gate_result_is_strict_digest_bound_and_non_executable() -> None:
    result = _result()
    assert result.schema_name == RUNTIME_GATE_RESULT_SCHEMA
    assert result.schema_version == RUNTIME_GATE_RESULT_SCHEMA_VERSION
    assert result.outcome == PASSED
    assert result.reason_code is None
    assert result.model_config["strict"] is True
    assert result.model_config["extra"] == "forbid"
    with pytest.raises(ValidationError):
        result.outcome = "DENY"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        RuntimeGateResult.build({**_fields(), "executable_token": "forged"})
    forbidden = {
        "allow",
        "decision_id",
        "policy_decision_id",
        "lease_id",
        "work_order_id",
        "executable_token",
        "target_effect",
    }
    assert forbidden.isdisjoint(RuntimeGateResult.model_fields)
    assert "ALLOW" not in result.model_dump_json()


def test_outcome_reason_compatibility_is_closed_and_exact() -> None:
    assert isinstance(OUTCOME_BY_REASON, MappingProxyType)
    assert dict(OUTCOME_BY_REASON) == EXPECTED_OUTCOME_BY_REASON
    for reason, outcome in EXPECTED_OUTCOME_BY_REASON.items():
        assert _result(outcome=outcome, reason_code=reason).reason_code == reason
        with pytest.raises(ValidationError, match="outcome and reason_code are incompatible"):
            _result(outcome=PASSED, reason_code=reason)
    for outcome in ("DENY", "APPROVAL_REQUIRED", "WAIT_FOR_RESOURCE", "STALE_CONTEXT"):
        with pytest.raises(ValidationError, match="outcome and reason_code are incompatible"):
            _result(outcome=outcome, reason_code=None)


@pytest.mark.parametrize("outcome", ["ALLOW", "EXECUTE", "passed", ""])
def test_unknown_or_executable_outcomes_fail_closed(outcome: str) -> None:
    with pytest.raises(ValidationError):
        _result(outcome=outcome)


@pytest.mark.parametrize("reason", ["UNKNOWN", "ALLOW", "", "admission_not_admitted"])
def test_unknown_reason_codes_fail_closed(reason: str) -> None:
    with pytest.raises(ValidationError):
        _result(outcome="DENY", reason_code=reason)


def test_result_digest_has_stable_golden_vector_and_rejects_tampering() -> None:
    result = _result()
    assert (
        result.result_digest == "c0e7773c6ad97320129309b697f2d743b278974a1627a78a86eb2e6411539ae8"
    )
    denied = _result(outcome="DENY", reason_code="ADMISSION_NOT_ADMITTED")
    assert denied.result_digest != result.result_digest
    assert RuntimeGateResult.model_validate_json(result.model_dump_json()) == result

    payload = json.loads(result.model_dump_json())
    payload["result_digest"] = "9" * 64
    with pytest.raises(ValidationError, match="result_digest does not bind"):
        RuntimeGateResult.model_validate_json(json.dumps(payload))

    payload = json.loads(result.model_dump_json())
    payload["supply_chain_digest"] = "8" * 64
    with pytest.raises(ValidationError, match="result_digest does not bind"):
        RuntimeGateResult.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", "tenant-b"),
        ("engagement_id", uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")),
        ("proposal_id", uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")),
        ("proposal_digest", "a" * 64),
        ("agent_instance_id", uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")),
        ("admission_result_digest", "b" * 64),
        ("runtime_snapshot_digest", "c" * 64),
        ("registry_schema_version", 2),
        ("registry_digest", "d" * 64),
        ("capability_id", "report.evidence_build.v1"),
        ("supply_chain_digest", "e" * 64),
        ("approval_class", "LEASE"),
        ("network_path", "TARGET_EGRESS"),
        ("requested_target_requests", 1),
        ("requested_cost_microunits", 2_000_001),
        ("requested_deadline_seconds", 31),
        ("evaluated_at", datetime(2026, 9, 3, 12, 6, tzinfo=UTC)),
    ],
)
def test_result_digest_binds_every_authority_bearing_field(field: str, value: object) -> None:
    assert _result(**{field: value}).result_digest != _result().result_digest


def test_result_deserialization_requires_a_valid_digest() -> None:
    payload = json.loads(_result().model_dump_json())
    payload.pop("result_digest")
    with pytest.raises(ValidationError):
        RuntimeGateResult.model_validate_json(json.dumps(payload))
    with pytest.raises(ValidationError):
        RuntimeGateResult.build({})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "1"),
        ("registry_schema_version", True),
        ("requested_target_requests", -1),
        ("requested_cost_microunits", -1),
        ("requested_deadline_seconds", 0),
        ("evaluated_at", "2026-09-03T12:05:00Z"),
    ],
)
def test_result_rejects_coercion_and_invalid_bounds(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _result(**{field: value})
