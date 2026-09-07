"""Tests for PolicyDecisionV2 schema, coherence, and digest validation (M1.4b2c)."""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from blackbread.policy.decision_v2 import (
    FINAL_OUTCOME_BY_REASON,
    PolicyDecisionV2,
)
from blackbread.policy.runtime_result import RuntimeGateReason
from tests.conductor._builders import graph_version

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_F = "f" * 64
TENANT = "tenant-a"
ENGAGEMENT = uuid.UUID("22222222-2222-2222-2222-222222222222")
PROPOSAL = uuid.UUID("11111111-1111-1111-1111-111111111111")
DECISION = uuid.UUID("44444444-4444-4444-4444-444444444444")
DECIDED_AT = datetime(2026, 9, 3, 12, 5, tzinfo=UTC)

EXPECTED_DIGEST = "aa473c9af6b667e7f05c73bae59a6d2409f1f5e3caeb20c6cc76f7960cd5ee5f"


def decision_fields(**overrides: Any) -> dict[str, Any]:
    """Return coherent, valid fields for PolicyDecisionV2 construction."""
    fields: dict[str, Any] = {
        "schema_name": "policy.decision",
        "schema_version": 2,
        "decision_id": DECISION,
        "tenant_id": TENANT,
        "engagement_id": ENGAGEMENT,
        "proposal_id": PROPOSAL,
        "proposal_digest": HEX_F,
        "decision_authority": "policy.kernel.v2",
        "outcome": "ALLOW",
        "reason_code": None,
        "decided_at": DECIDED_AT,
        "graph_version": graph_version().model_dump(),
        "runtime_gate_result_digest": HEX_C,
    }
    fields.update(overrides)
    return fields


def test_independent_outcome_mapping_completeness() -> None:
    """Verify independent expected outcomes for all 23 RuntimeGateReasons."""
    expected_mapping: dict[RuntimeGateReason, str] = {
        "RUNTIME_BINDING_MISMATCH": "DENY",
        "ADMISSION_DENIED": "DENY",
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

    assert set(expected_mapping) == set(FINAL_OUTCOME_BY_REASON)
    for reason, expected_outcome in expected_mapping.items():
        assert FINAL_OUTCOME_BY_REASON[reason] == expected_outcome


def test_schema_literal_validation() -> None:
    """Verify exact literal and constrained-integer constraints."""
    valid = decision_fields()

    # Valid schema_version
    PolicyDecisionV2.build({**valid, "schema_version": 2})

    # Invalid schema_version types and values
    for invalid_version in (2.0, "2", True, 1, 3):
        with pytest.raises(ValidationError):
            PolicyDecisionV2.build({**valid, "schema_version": invalid_version})

    # Invalid schema_name
    with pytest.raises(ValidationError):
        PolicyDecisionV2.build({**valid, "schema_name": "policy.decision_v2"})

    # Invalid decision_authority
    with pytest.raises(ValidationError):
        PolicyDecisionV2.build({**valid, "decision_authority": "policy.kernel.v1"})


def test_outcome_reason_coherence() -> None:
    """Verify mismatched outcomes and reasons are rejected."""
    valid = decision_fields()

    # reason_code=None with non-ALLOW outcome
    with pytest.raises(ValueError, match="reason_code is None but outcome is not ALLOW"):
        PolicyDecisionV2.build({**valid, "outcome": "DENY", "reason_code": None})

    # reason_code present with ALLOW outcome
    with pytest.raises(ValueError, match="outcome and reason_code are incompatible"):
        PolicyDecisionV2.build({**valid, "outcome": "ALLOW", "reason_code": "ADMISSION_DENIED"})

    # Mismatched valid outcome/reason pairs
    with pytest.raises(ValueError, match="outcome and reason_code are incompatible"):
        PolicyDecisionV2.build(
            {**valid, "outcome": "WAIT_FOR_RESOURCE", "reason_code": "ADMISSION_DENIED"}
        )


def test_fixed_independent_preimage_digest() -> None:
    """Verify fixed schema identity and canonical hashing against a known answer."""
    decision = PolicyDecisionV2.build(decision_fields())
    assert decision.decision_digest == EXPECTED_DIGEST


@pytest.mark.parametrize(
    "mutations",
    [
        {"decision_id": uuid.uuid4()},
        {"tenant_id": "tenant-b"},
        {"engagement_id": uuid.uuid4()},
        {"proposal_id": uuid.uuid4()},
        {"proposal_digest": "0" * 64},
        {"outcome": "DENY", "reason_code": "ADMISSION_DENIED"},
        {"decided_at": datetime(2026, 9, 3, 12, 10, tzinfo=UTC)},
        {"runtime_gate_result_digest": "0" * 64},
        {"graph_version": graph_version(state_root_version=3).model_dump()},
        {"graph_version": graph_version(projector_version=2).model_dump()},
        {"graph_version": graph_version(state_root="0" * 64).model_dump()},
        {"graph_version": graph_version(ledger_event_count=8).model_dump()},
        {"graph_version": graph_version(ledger_head_hash="0" * 64).model_dump()},
    ],
    ids=lambda x: str(next(iter(x.keys()))),
)
def test_stale_digest_sensitivity(mutations: dict[str, Any]) -> None:
    """Verify typed mutations with an old digest are rejected."""
    # Build a valid dictionary containing the old (correct) digest
    fields = decision_fields()
    old_digest = PolicyDecisionV2.build(fields).decision_digest

    # Apply valid typed mutations
    mutated_fields = deepcopy(fields)
    mutated_fields.update(mutations)
    mutated_fields["decision_digest"] = old_digest

    with pytest.raises(ValueError, match="decision_digest does not bind the decision contents"):
        PolicyDecisionV2.model_validate(mutated_fields)


def test_serialization_round_trip() -> None:
    """Verify Python-mode and JSON serialization logic."""
    decision = PolicyDecisionV2.build(decision_fields())

    # JSON round-trip
    restored = PolicyDecisionV2.model_validate_json(decision.model_dump_json(), strict=True)
    assert restored == decision

    # Python-mode validation preserves types
    raw_dict = decision.model_dump()
    assert isinstance(raw_dict["decision_id"], uuid.UUID)
    assert isinstance(raw_dict["decided_at"], datetime)
    assert isinstance(raw_dict["schema_version"], int)
    restored_dict = PolicyDecisionV2.model_validate(raw_dict)
    assert restored_dict == decision


def test_extra_fields_are_rejected() -> None:
    """Verify extra fields are rejected by the strict model config."""
    fields = decision_fields()
    fields["lease_id"] = uuid.uuid4()
    with pytest.raises(ValidationError, match="extra"):
        PolicyDecisionV2.build(fields)

    # Also via model_validate with an extra field.
    valid = decision_fields()
    valid["executable_token"] = "test-token-value"  # noqa: S105
    with pytest.raises(ValidationError, match="extra"):
        PolicyDecisionV2.model_validate(valid)


def test_instances_are_frozen() -> None:
    """Verify PolicyDecisionV2 instances are immutable."""
    decision = PolicyDecisionV2.build(decision_fields())
    assert decision.model_config.get("frozen") is True

    with pytest.raises(ValidationError, match="frozen"):
        decision.outcome = "DENY"  # type: ignore[misc]

    with pytest.raises(ValidationError, match="frozen"):
        decision.reason_code = "ADMISSION_DENIED"  # type: ignore[misc]


def test_identical_inputs_produce_identical_decision_digests() -> None:
    """Verify deterministic digest: identical inputs produce identical digests."""
    decision_a = PolicyDecisionV2.build(decision_fields())
    decision_b = PolicyDecisionV2.build(decision_fields())
    assert decision_a.decision_digest == decision_b.decision_digest

    # A different input produces a different digest.
    different = PolicyDecisionV2.build(decision_fields(tenant_id="tenant-b"))
    assert different.decision_digest != decision_a.decision_digest
