"""ActionProposal digest: canonical stability and per-field sensitivity."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

import pytest

from blackbread.conductor.contracts import (
    ActionProposal,
    BudgetRequest,
    ParameterEnvelope,
    ResourceEstimates,
    TargetReference,
)
from blackbread.ledger.hashing import HASH_HEX_LENGTH

from ._builders import graph_version, make_proposal, proposal_fields, raw_proposal


def test_digest_is_lowercase_sha256_hex() -> None:
    digest = make_proposal().proposal_digest
    assert len(digest) == HASH_HEX_LENGTH
    assert digest == digest.lower()
    int(digest, 16)


def test_digest_is_stable_for_identical_canonical_input() -> None:
    left = make_proposal()
    right = make_proposal()
    assert left.proposal_digest == right.proposal_digest


def test_digest_matches_between_typed_and_untrusted_paths() -> None:
    typed = make_proposal()
    parsed = ActionProposal.from_untrusted(raw_proposal())
    assert typed.proposal_digest == parsed.proposal_digest


def _distinct_field_variants() -> list[dict[str, Any]]:
    base = proposal_fields()
    created = base["created_at"]
    return [
        {"proposal_id": uuid.UUID("99999999-9999-9999-9999-999999999999")},
        {"tenant_id": "tenant-z"},
        {"engagement_id": uuid.UUID("88888888-8888-8888-8888-888888888888")},
        {"agent_instance_id": uuid.UUID("77777777-7777-7777-7777-777777777777")},
        {"agent_role": "Strike"},
        {"capability_id": "strike.credential_intelligence_offline.v1"},
        {"target": TargetReference(target_kind="exact_host", canonical_value="example.com")},
        {"target": TargetReference(target_kind="root_domain", canonical_value="other.com")},
        {
            "parameter_envelope": ParameterEnvelope(
                input_schema_ref="PassiveAssetIntelligenceInput.v1",
                parameters={"depth": 2, "sources": ["ct", "dns"]},
            )
        },
        {
            "parameter_envelope": ParameterEnvelope(
                input_schema_ref="OtherInput.v1",
                parameters={"depth": 1, "sources": ["ct", "dns"]},
            )
        },
        {"intended_proof": "different-proof"},
        {"precondition_refs": ("scope-attested", "extra-precondition")},
        {"oracle_ref": "different-oracle"},
        {"estimates": ResourceEstimates(risk=0.9, cost=2.0, information_gain=0.4, opsec_noise=0.2)},
        {"estimates": ResourceEstimates(risk=0.1, cost=9.0, information_gain=0.4, opsec_noise=0.2)},
        {"estimates": ResourceEstimates(risk=0.1, cost=2.0, information_gain=0.9, opsec_noise=0.2)},
        {"estimates": ResourceEstimates(risk=0.1, cost=2.0, information_gain=0.4, opsec_noise=0.9)},
        {"requested_budget": BudgetRequest(target_requests=5, deadline_seconds=30)},
        {"requested_budget": BudgetRequest(target_requests=0, deadline_seconds=45)},
        {"target_identity_tier": "T1"},
        {"graph_version": graph_version(state_root="d" * 64)},
        {"graph_version": graph_version(ledger_event_count=8)},
        {"graph_version": graph_version(ledger_head_hash="e" * 64)},
        {"graph_version": graph_version(state_root_version=3)},
        {"graph_version": graph_version(projector_version=2)},
        {"idempotency_key": "idem-0002"},
        {"created_at": created + timedelta(seconds=1)},
        {"expires_at": created + timedelta(minutes=30)},
    ]


@pytest.mark.parametrize("override", _distinct_field_variants())
def test_digest_is_sensitive_to_every_security_field(override: dict[str, Any]) -> None:
    baseline = make_proposal().proposal_digest
    varied = make_proposal(**override).proposal_digest
    assert varied != baseline


def test_digest_is_stable_across_repeated_reads() -> None:
    proposal = make_proposal()
    assert proposal.proposal_digest == proposal.proposal_digest


def test_parameter_envelope_is_json_serializable() -> None:
    envelope = ParameterEnvelope(
        input_schema_ref="Sample.v1",
        parameters={"sources": ["ct", "dns"], "nested": {"depth": 1}},
    )
    dumped = envelope.model_dump(mode="json")
    parameters = dumped["parameters"]
    assert isinstance(parameters, dict)
    assert isinstance(parameters["sources"], list)
    assert isinstance(parameters["nested"], dict)
    assert isinstance(json.loads(envelope.model_dump_json())["parameters"], dict)


def test_action_proposal_is_json_serializable() -> None:
    proposal = make_proposal()
    dumped = proposal.model_dump(mode="json")
    assert dumped["parameter_envelope"]["parameters"] == {"depth": 1, "sources": ["ct", "dns"]}
    assert isinstance(json.loads(proposal.model_dump_json()), dict)


def test_serialized_parameters_are_detached_from_contract() -> None:
    proposal = make_proposal()
    digest_before = proposal.proposal_digest
    dumped = proposal.model_dump(mode="json")
    dumped["parameter_envelope"]["parameters"]["sources"].append("http")
    dumped["parameter_envelope"]["parameters"]["depth"] = 99
    assert proposal.proposal_digest == digest_before
    assert proposal.parameter_envelope.canonical_parameters == (
        make_proposal().parameter_envelope.canonical_parameters
    )


def test_round_trip_through_from_untrusted_preserves_digest() -> None:
    proposal = make_proposal()
    serialized = proposal.model_dump(mode="json")
    reconstructed = ActionProposal.from_untrusted(serialized)
    assert reconstructed.proposal_digest == proposal.proposal_digest
    assert reconstructed.parameter_envelope.canonical_parameters == (
        proposal.parameter_envelope.canonical_parameters
    )
