"""Deny-only proposal intake behavior and pure-boundary guarantees."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from blackbread.conductor.contracts import ConductorContractError
from blackbread.conductor.intake import evaluate_proposal, intake_proposal
from blackbread.policy.contracts import (
    DENY_ONLY_DECISION_AUTHORITY,
    POLICY_DECISION_SCHEMA,
    PolicyDecision,
)

from ._builders import make_proposal, raw_proposal

DECISION_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
BEFORE_EXPIRY = datetime(2026, 9, 3, 12, 5, 0, tzinfo=UTC)
AFTER_EXPIRY = datetime(2026, 9, 3, 13, 0, 0, tzinfo=UTC)


def test_fresh_valid_proposal_is_denied_trust_spine_not_ready() -> None:
    proposal = make_proposal()
    decision = evaluate_proposal(proposal, decision_id=DECISION_ID, decided_at=BEFORE_EXPIRY)
    assert isinstance(decision, PolicyDecision)
    assert decision.outcome == "DENY"
    assert decision.reason_code == "TRUST_SPINE_NOT_READY"
    assert decision.decision_authority == DENY_ONLY_DECISION_AUTHORITY
    assert decision.schema_name == POLICY_DECISION_SCHEMA


def test_expired_proposal_is_denied_proposal_expired() -> None:
    proposal = make_proposal()
    decision = evaluate_proposal(proposal, decision_id=DECISION_ID, decided_at=AFTER_EXPIRY)
    assert decision.outcome == "DENY"
    assert decision.reason_code == "PROPOSAL_EXPIRED"


def test_expiry_boundary_at_exact_expiry_is_expired() -> None:
    proposal = make_proposal()
    decision = evaluate_proposal(proposal, decision_id=DECISION_ID, decided_at=proposal.expires_at)
    assert decision.reason_code == "PROPOSAL_EXPIRED"


def test_decision_binds_proposal_identity_exactly() -> None:
    proposal = make_proposal()
    decision = evaluate_proposal(proposal, decision_id=DECISION_ID, decided_at=BEFORE_EXPIRY)
    assert decision.decision_id == DECISION_ID
    assert decision.tenant_id == proposal.tenant_id
    assert decision.engagement_id == proposal.engagement_id
    assert decision.proposal_id == proposal.proposal_id
    assert decision.proposal_digest == proposal.proposal_digest
    assert decision.graph_version == proposal.graph_version
    assert decision.decided_at == BEFORE_EXPIRY


def test_intake_uses_caller_supplied_decision_id_and_timestamp() -> None:
    proposal = make_proposal()
    other_id = uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    decision = evaluate_proposal(proposal, decision_id=other_id, decided_at=BEFORE_EXPIRY)
    assert decision.decision_id == other_id
    assert decision.decided_at == BEFORE_EXPIRY


def test_intake_is_deterministic_for_identical_inputs() -> None:
    proposal = make_proposal()
    first = evaluate_proposal(proposal, decision_id=DECISION_ID, decided_at=BEFORE_EXPIRY)
    second = evaluate_proposal(proposal, decision_id=DECISION_ID, decided_at=BEFORE_EXPIRY)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


@pytest.mark.parametrize(
    "capability_id",
    [
        "scout.passive_asset_intelligence.v1",
        "exploit.controlled_proof.v1",
        "conductor.unknown_capability.v9",
        "post_exploit.objective_read.v1",
    ],
)
def test_no_capability_receives_execution_authority(capability_id: str) -> None:
    proposal = make_proposal(capability_id=capability_id)
    decision = evaluate_proposal(proposal, decision_id=DECISION_ID, decided_at=BEFORE_EXPIRY)
    assert decision.outcome == "DENY"


def test_intake_from_raw_denies_valid_mapping() -> None:
    decision = intake_proposal(raw_proposal(), decision_id=DECISION_ID, decided_at=BEFORE_EXPIRY)
    assert decision.outcome == "DENY"
    assert decision.reason_code == "TRUST_SPINE_NOT_READY"


@pytest.mark.parametrize(
    "mutation",
    [
        {"tenant_id": " tenant-a"},
        {"schema_version": 2},
        {"agent_role": "Planner"},
        {"capability_id": "bad-id"},
    ],
)
def test_malformed_raw_proposal_fails_closed(mutation: dict[str, Any]) -> None:
    with pytest.raises(ConductorContractError):
        intake_proposal(raw_proposal(**mutation), decision_id=DECISION_ID, decided_at=BEFORE_EXPIRY)


def test_malformed_raw_proposal_is_rejected_before_identity_inferred() -> None:
    corrupt = raw_proposal()
    corrupt["tenant_id"] = " tenant-a"
    corrupt["engagement_id"] = "not-a-uuid"
    with pytest.raises(ConductorContractError):
        intake_proposal(corrupt, decision_id=DECISION_ID, decided_at=BEFORE_EXPIRY)


@pytest.mark.parametrize(
    "decided_at",
    [
        datetime(2026, 9, 3, 12, 5, 0),
        datetime(2026, 9, 3, 12, 5, 0, tzinfo=timezone(timedelta(hours=7))),
    ],
)
def test_non_utc_decided_at_fails_closed(decided_at: datetime) -> None:
    proposal = make_proposal()
    with pytest.raises(ConductorContractError):
        evaluate_proposal(proposal, decision_id=DECISION_ID, decided_at=decided_at)


def test_non_uuid_decision_id_fails_closed() -> None:
    proposal = make_proposal()
    with pytest.raises(ConductorContractError):
        evaluate_proposal(
            proposal,
            decision_id="dddddddd-dddd-dddd-dddd-dddddddddddd",  # type: ignore[arg-type]
            decided_at=BEFORE_EXPIRY,
        )


def test_intake_returns_only_deny_outcomes() -> None:
    proposal = make_proposal()
    fresh = evaluate_proposal(proposal, decision_id=DECISION_ID, decided_at=BEFORE_EXPIRY)
    expired = evaluate_proposal(proposal, decision_id=DECISION_ID, decided_at=AFTER_EXPIRY)
    assert {fresh.outcome, expired.outcome} == {"DENY"}
