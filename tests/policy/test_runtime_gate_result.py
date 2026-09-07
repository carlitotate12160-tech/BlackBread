"""RuntimeGateResult schema strictness, reason/outcome coherence, digest sensitivity, and tamper.

The result is tamper-evident, not authenticated: any change to a semantic or provenance field while
retaining the old digest must fail validation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import get_args
from uuid import UUID

import pytest
from pydantic import ValidationError

from blackbread.policy.runtime_gate import evaluate_runtime_gates
from blackbread.policy.runtime_result import (
    OUTCOME_BY_REASON,
    RUNTIME_GATE_RESULT_SCHEMA,
    RUNTIME_GATE_RESULT_SCHEMA_VERSION,
    RuntimeGateReason,
    RuntimeGateResult,
)
from tests.policy._builders import capability_snapshot
from tests.policy._runtime_builders import runtime_case

_MUTATIONS: dict[str, object] = {
    "tenant_id": "tenant-z",
    "engagement_id": UUID("99999999-9999-9999-9999-999999999999"),
    "proposal_id": UUID("99999999-9999-9999-9999-999999999999"),
    "proposal_digest": "0" * 64,
    "agent_instance_id": UUID("99999999-9999-9999-9999-999999999999"),
    "admission_result_digest": "0" * 64,
    "runtime_snapshot_digest": "0" * 64,
    "registry_schema_version": 2,
    "registry_digest": "0" * 64,
    "capability_id": "scout.other_thing.v1",
    "supply_chain_digest": "0" * 64,
    "approval_class": "LEASE",
    "network_path": "TARGET_EGRESS",
    "requested_target_requests": 5,
    "requested_cost_microunits": 999,
    "requested_deadline_seconds": 99,
    "evaluated_at": datetime(2026, 9, 3, 12, 9, tzinfo=UTC),
}


def _passed() -> RuntimeGateResult:
    case = runtime_case()
    return evaluate_runtime_gates(case.pop("proposal"), **case)


def _denied() -> RuntimeGateResult:
    case = runtime_case(capability=capability_snapshot(lifecycle="RETIRED"))
    return evaluate_runtime_gates(case.pop("proposal"), **case)


def test_schema_identity_and_version() -> None:
    result = _passed()
    assert result.schema_name == RUNTIME_GATE_RESULT_SCHEMA == "policy.runtime.gate.result"
    assert result.schema_version == RUNTIME_GATE_RESULT_SCHEMA_VERSION == 1


def test_result_is_strict_and_frozen() -> None:
    data = _passed().model_dump()
    data["surprise_field"] = 1
    with pytest.raises(ValidationError):
        RuntimeGateResult.model_validate(data)
    with pytest.raises(ValidationError):
        _passed().schema_version = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    "field, value", [("schema_name", "policy.runtime.other"), ("schema_version", 2)]
)
def test_unknown_schema_identity_rejected(field: str, value: object) -> None:
    data = _passed().model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        RuntimeGateResult.model_validate(data)


def test_every_reason_maps_to_exactly_one_non_passing_outcome() -> None:
    for reason in get_args(RuntimeGateReason):
        outcome = OUTCOME_BY_REASON[reason]
        assert outcome != "PASSED_FOR_FINAL_DECISION"
        assert isinstance(outcome, str)


def test_passed_requires_no_reason() -> None:
    data = _passed().model_dump()
    data["reason_code"] = "ENGAGEMENT_STOPPED"
    with pytest.raises(ValidationError):
        RuntimeGateResult.build({k: v for k, v in data.items() if k != "result_digest"})


def test_reason_requires_its_compatible_outcome() -> None:
    data = _denied().model_dump()
    data["reason_code"] = "APPROVAL_MISSING"  # would require APPROVAL_REQUIRED, not DENY
    with pytest.raises(ValidationError):
        RuntimeGateResult.build({k: v for k, v in data.items() if k != "result_digest"})


def test_denied_result_carries_deny_outcome() -> None:
    result = _denied()
    assert result.outcome == "DENY"
    assert result.reason_code == "ADMISSION_DENIED"


@pytest.mark.parametrize("field", list(_MUTATIONS))
def test_tampering_any_field_with_stale_digest_is_rejected(field: str) -> None:
    data = _passed().model_dump()
    data[field] = _MUTATIONS[field]
    # result_digest is left at its stale value.
    with pytest.raises(ValidationError):
        RuntimeGateResult.model_validate(data)


def test_digest_is_deterministic_for_identical_results() -> None:
    assert _passed().result_digest == _passed().result_digest


def test_roundtrip_serialization_is_stable() -> None:
    result = _passed()
    assert RuntimeGateResult.model_validate(result.model_dump()) == result


def test_build_binds_the_digest() -> None:
    result = _passed()
    fields = result.model_dump(exclude={"result_digest"})
    assert RuntimeGateResult.build(fields).result_digest == result.result_digest
    # A hand-supplied wrong digest is rejected.
    data = result.model_dump()
    data["result_digest"] = "0" * 64
    with pytest.raises(ValidationError):
        RuntimeGateResult.model_validate(data)


def test_result_grants_no_execution_authority() -> None:
    fields = set(RuntimeGateResult.model_fields)
    forbidden = {
        "allow",
        "decision_id",
        "policy_decision_id",
        "lease_id",
        "work_order_id",
        "executable_token",
        "target_effect",
        "capability_activation",
    }
    assert forbidden.isdisjoint(fields)
    assert "PASSED_FOR_FINAL_DECISION" not in {
        OUTCOME_BY_REASON[r] for r in get_args(RuntimeGateReason)
    }
