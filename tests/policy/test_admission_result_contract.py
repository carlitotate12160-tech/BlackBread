"""Strict, immutable, non-executable policy-admission result contract."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from blackbread.policy.admission_contracts import (
    ADMISSION_RESULT_SCHEMA,
    ADMISSION_RESULT_SCHEMA_VERSION,
    AdmissionResult,
)
from tests.conductor._builders import graph_version, make_proposal
from tests.policy._builders import (
    CAPABILITY,
    EXTRACTOR,
    HEX_ATTEST,
    HEX_EVIDENCE,
    HEX_EXTRACTOR,
    HEX_P,
    HEX_REGISTRY,
    HEX_SUPPLY,
)


def _result(**overrides: object) -> AdmissionResult:
    proposal = make_proposal()
    fields: dict[str, object] = {
        "schema_name": "policy.admission.result",
        "schema_version": 1,
        "tenant_id": proposal.tenant_id,
        "engagement_id": proposal.engagement_id,
        "proposal_id": proposal.proposal_id,
        "proposal_digest": proposal.proposal_digest,
        "policy_schema_ref": "EngagementPolicy.v1",
        "policy_digest": HEX_P,
        "attestation_digest": HEX_ATTEST,
        "identity_verifier_ref": "identity-verifier-observation",
        "identity_evidence_digest": HEX_EVIDENCE,
        "registry_schema_version": 1,
        "registry_digest": HEX_REGISTRY,
        "capability_id": CAPABILITY,
        "supply_chain_digest": HEX_SUPPLY,
        "extractor_identity": EXTRACTOR,
        "extractor_digest": HEX_EXTRACTOR,
        "parameter_digest": "7" * 64,
        "graph_version": graph_version(),
        "evaluated_at": datetime(2026, 9, 3, 12, 5, tzinfo=UTC),
        "outcome": "ADMITTED_FOR_RUNTIME_GATES",
        "reason_code": None,
    }
    fields.update(overrides)
    return AdmissionResult(**fields)


def test_result_schema_is_versioned_and_strict() -> None:
    assert ADMISSION_RESULT_SCHEMA == "policy.admission.result"
    assert ADMISSION_RESULT_SCHEMA_VERSION == 1
    with pytest.raises(ValidationError):
        _result(unexpected="authority")


def test_admitted_result_requires_no_reason() -> None:
    result = _result()
    assert result.outcome == "ADMITTED_FOR_RUNTIME_GATES"
    assert result.reason_code is None
    assert "ALLOW" not in result.model_dump_json()


def test_denied_result_requires_one_supported_reason() -> None:
    result = _result(outcome="DENY", reason_code="PROPOSAL_EXPIRED")
    assert result.reason_code == "PROPOSAL_EXPIRED"
    with pytest.raises(ValidationError):
        _result(outcome="DENY", reason_code=None)


def test_outcome_reason_combinations_fail_closed() -> None:
    with pytest.raises(ValidationError):
        _result(reason_code="PROPOSAL_EXPIRED")
    with pytest.raises(ValidationError):
        _result(outcome="ALLOW")
    with pytest.raises(ValidationError):
        _result(outcome="DENY", reason_code="SECRET_VALUE")


def test_result_is_immutable_and_has_no_execution_authority_fields() -> None:
    result = _result()
    with pytest.raises(ValidationError):
        result.outcome = "DENY"  # type: ignore[misc]
    forbidden = {"approval", "lease_id", "work_order_id", "executable_token"}
    assert forbidden.isdisjoint(AdmissionResult.model_fields)


def test_result_digest_is_stable_and_sensitive() -> None:
    left = _result()
    right = _result()
    assert left.model_dump_json() == right.model_dump_json()
    assert left.result_digest == right.result_digest
    assert left.result_digest != _result(policy_digest="8" * 64).result_digest
    changed_time = _result(evaluated_at=datetime(2026, 9, 3, 12, 6, tzinfo=UTC))
    assert left.result_digest != changed_time.result_digest


def test_result_digest_golden_vector() -> None:
    assert _result().result_digest == (
        "f487fd101b921c079d693b449c952d3fc9cd63710cfb1d22ec81cb0b2f286911"
    )
