"""PolicyDecision v1: deny-only contract and unforgeable ALLOW prevention."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from blackbread.conductor.contracts import GraphVersionReference
from blackbread.policy.contracts import (
    DENY_ONLY_DECISION_AUTHORITY,
    POLICY_DECISION_SCHEMA,
    POLICY_DECISION_SCHEMA_VERSION,
    PolicyContractError,
    PolicyDecision,
)

DECIDED_AT = datetime(2026, 9, 3, 12, 5, 0, tzinfo=UTC)


def graph_version(**overrides: Any) -> GraphVersionReference:
    fields: dict[str, Any] = {
        "state_root_version": 2,
        "projector_version": 1,
        "state_root": "a" * 64,
        "ledger_event_count": 7,
        "ledger_head_hash": "b" * 64,
    }
    fields.update(overrides)
    return GraphVersionReference(**fields)


def decision_fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "schema_name": POLICY_DECISION_SCHEMA,
        "schema_version": POLICY_DECISION_SCHEMA_VERSION,
        "decision_id": uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
        "tenant_id": "tenant-a",
        "engagement_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "proposal_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "proposal_digest": "a" * 64,
        "decision_authority": DENY_ONLY_DECISION_AUTHORITY,
        "outcome": "DENY",
        "reason_code": "TRUST_SPINE_NOT_READY",
        "decided_at": DECIDED_AT,
        "graph_version": graph_version(),
    }
    fields.update(overrides)
    return fields


def make_decision(**overrides: Any) -> PolicyDecision:
    return PolicyDecision(**decision_fields(**overrides))


def test_valid_deny_decision_is_admitted_and_frozen() -> None:
    decision = make_decision()
    assert decision.outcome == "DENY"
    assert decision.decision_authority == DENY_ONLY_DECISION_AUTHORITY
    with pytest.raises(ValidationError):
        decision.outcome = "ALLOW"


@pytest.mark.parametrize(
    "outcome",
    ["ALLOW", "APPROVAL_REQUIRED", "WAIT_FOR_RESOURCE", "STALE_CONTEXT", "deny", "allow", ""],
)
def test_only_deny_outcome_is_representable(outcome: str) -> None:
    with pytest.raises(ValidationError):
        make_decision(outcome=outcome)


@pytest.mark.parametrize("reason", ["PROPOSAL_EXPIRED", "TRUST_SPINE_NOT_READY"])
def test_supported_reason_codes_admitted(reason: str) -> None:
    assert make_decision(reason_code=reason).reason_code == reason


@pytest.mark.parametrize(
    "reason", ["OPSEC_HOLD", "ENGAGEMENT_STOPPED", "OK", "", "trust_spine_not_ready"]
)
def test_unsupported_reason_codes_fail_closed(reason: str) -> None:
    with pytest.raises(ValidationError):
        make_decision(reason_code=reason)


def test_unknown_decision_authority_fails_closed() -> None:
    with pytest.raises(ValidationError):
        make_decision(decision_authority="policy.kernel.v1")


def test_decision_unknown_schema_version_fails_closed() -> None:
    with pytest.raises(ValidationError):
        make_decision(schema_version=2)


def test_decision_unknown_schema_name_fails_closed() -> None:
    with pytest.raises(ValidationError):
        make_decision(schema_name="policy.kernel_decision")


@pytest.mark.parametrize(
    "digest",
    ["a" * 63, "A" * 64, "z" * 64, "", 12345],
)
def test_invalid_proposal_digest_fails_closed(digest: Any) -> None:
    with pytest.raises(ValidationError):
        make_decision(proposal_digest=digest)


def test_decision_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        make_decision(**{"executable_token": "x"})


@pytest.mark.parametrize(
    "decided_at",
    [
        datetime(2026, 9, 3, 12, 5, 0),
        datetime(2026, 9, 3, 12, 5, 0, tzinfo=timezone(timedelta(hours=7))),
    ],
)
def test_decision_non_utc_decided_at_fails_closed(decided_at: datetime) -> None:
    with pytest.raises(ValidationError):
        make_decision(decided_at=decided_at)


def test_graph_version_is_preserved() -> None:
    reference = graph_version(ledger_event_count=42)
    decision = make_decision(graph_version=reference)
    assert decision.graph_version == reference


def test_policy_contract_error_is_value_error() -> None:
    assert issubclass(PolicyContractError, ValueError)


def test_no_allow_or_lease_field_exists_on_decision() -> None:
    fields = set(PolicyDecision.model_fields)
    forbidden = {"lease_id", "work_order", "executable_token", "approval_reference"}
    assert fields.isdisjoint(forbidden)


def test_invalid_unicode_surrogate_tenant_id_fails_closed() -> None:
    with pytest.raises(ValidationError):
        make_decision(tenant_id="tenant\ud800")


def test_decision_is_json_serializable() -> None:
    decision = make_decision()
    assert decision.model_dump(mode="json")["outcome"] == "DENY"
    assert '"outcome":"DENY"' in decision.model_dump_json().replace(" ", "")
