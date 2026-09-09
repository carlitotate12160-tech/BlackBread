from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock
from uuid import UUID

import pytest
from pydantic import ConfigDict, ValidationError

from blackbread.ledger.catalog import default_registry
from blackbread.ledger.errors import LedgerValidationError
from blackbread.ledger.hashing import canonical_json, compute_payload_hash
from blackbread.ledger.schema import EventEnvelope, EventRegistry, UnknownEventSchemaError, to_draft
from blackbread.policy import evaluation_facts
from blackbread.policy.decision_v2 import FINAL_OUTCOME_BY_REASON
from blackbread.policy.evaluation import evaluate_policy
from blackbread.policy.evaluation_facts import (
    EvaluationBindingError,
    PolicyDecisionRecorded,
    evaluate_persistence_facts,
    policy_decision_registry,
)
from tests.policy.test_evaluation_facts import evaluation_inputs

GOLDEN_JSON = (
    '{"decided_at":"2026-09-03T12:05:00Z","decision_authority":"policy.kernel.v2",'
    '"decision_digest":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",'
    '"decision_id":"44444444-4444-4444-4444-444444444444",'
    '"decision_schema_name":"policy.decision","decision_schema_version":2,'
    '"graph_version":{"ledger_event_count":7,'
    '"ledger_head_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
    '"projector_version":1,'
    '"state_root":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
    '"state_root_version":2},"idempotency_key":"idem-0001","outcome":"ALLOW",'
    '"proposal_digest":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",'
    '"proposal_id":"11111111-1111-1111-1111-111111111111","reason_code":null,'
    '"runtime_gate_result_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"}'
)
GOLDEN_HASH = "24340c3fb5fc3e944b2b3160613d7d56689833d5ed5507c81877e78343f1f5fa"
SCHEMA_KEY = ("policy.decision.recorded", 1)


def parse_payload(**overrides: Any) -> PolicyDecisionRecorded:
    payload = json.loads(GOLDEN_JSON)
    payload.update(overrides)
    result = policy_decision_registry().parse(*SCHEMA_KEY, payload)
    assert isinstance(result, PolicyDecisionRecorded)
    return result


def envelope() -> EventEnvelope:
    return EventEnvelope(
        tenant_id="tenant-a",
        engagement_id=UUID("22222222-2222-2222-2222-222222222222"),
        producer="policy-record-transaction.v1",
        occurred_at=datetime(2026, 9, 3, 12, 5, tzinfo=UTC),
        correlation_id=UUID("11111111-1111-1111-1111-111111111111"),
        causation_id=UUID("44444444-4444-4444-4444-444444444444"),
    )


def test_dedicated_cached_frozen_registry_and_unchanged_default() -> None:
    registry = policy_decision_registry()
    assert registry is policy_decision_registry()
    assert registry.registered_keys == frozenset({SCHEMA_KEY})
    assert registry.resolve(*SCHEMA_KEY) is PolicyDecisionRecorded
    assert SCHEMA_KEY not in default_registry().registered_keys
    with pytest.raises(LedgerValidationError, match="frozen"):
        registry.register(PolicyDecisionRecorded)
    with pytest.raises(UnknownEventSchemaError):
        registry.parse(SCHEMA_KEY[0], 2, json.loads(GOLDEN_JSON))
    with pytest.raises(UnknownEventSchemaError):
        registry.parse("other.decision", 1, json.loads(GOLDEN_JSON))


def test_exact_canonical_payload_and_independent_golden_sha256() -> None:
    payload = parse_payload()
    assert set(PolicyDecisionRecorded.model_fields) == set(json.loads(GOLDEN_JSON))
    draft = to_draft(payload, envelope(), registry=policy_decision_registry())
    assert draft.materialize_payload() == json.loads(GOLDEN_JSON)
    assert canonical_json(draft.materialize_payload()) == GOLDEN_JSON
    assert compute_payload_hash(draft.materialize_payload()) == GOLDEN_HASH
    assert canonical_json(payload.to_ledger_payload()) == GOLDEN_JSON
    assert payload.decided_at == draft.occurred_at


@pytest.mark.parametrize("field", list(json.loads(GOLDEN_JSON)))
def test_every_bound_field_is_required_and_hash_sensitive(field: str) -> None:
    changed = json.loads(GOLDEN_JSON)
    changed[field] = "different"
    assert compute_payload_hash(changed) != GOLDEN_HASH
    omitted = json.loads(GOLDEN_JSON)
    del omitted[field]
    assert compute_payload_hash(omitted) != GOLDEN_HASH
    with pytest.raises(LedgerValidationError):
        policy_decision_registry().parse(*SCHEMA_KEY, omitted)


@pytest.mark.parametrize("field", list(json.loads(GOLDEN_JSON)["graph_version"]))
def test_every_graph_anchor_component_is_hash_bound(field: str) -> None:
    changed = json.loads(GOLDEN_JSON)
    changed["graph_version"][field] = "different"
    assert compute_payload_hash(changed) != GOLDEN_HASH
    del changed["graph_version"][field]
    assert compute_payload_hash(changed) != GOLDEN_HASH
    with pytest.raises(LedgerValidationError):
        policy_decision_registry().parse(*SCHEMA_KEY, changed)


@pytest.mark.parametrize("field", [key for key in json.loads(GOLDEN_JSON) if key != "reason_code"])
def test_null_required_fields_fail(field: str) -> None:
    with pytest.raises(LedgerValidationError):
        parse_payload(**{field: None})


@pytest.mark.parametrize(
    "override",
    [
        {"extra": "not-allowed"},
        {"decision_schema_name": "policy.decision.v2"},
        {"decision_schema_version": "2"},
        {"decision_schema_version": True},
        {"decision_schema_version": 2.0},
        {"decision_schema_version": 1},
        {"decision_authority": "other.producer"},
        {"proposal_id": "not-a-uuid"},
        {"idempotency_key": " "},
        {"idempotency_key": 123},
        {"proposal_digest": "C" * 64},
        {"decision_digest": "e" * 63},
        {"runtime_gate_result_digest": "g" * 64},
        {"decided_at": "2026-09-03T12:05:00"},
        {"decided_at": "2026-09-03T13:05:00+01:00"},
        {"decided_at": 1788437100},
        {"outcome": "PASSED_FOR_FINAL_DECISION"},
        {"outcome": "DENY", "reason_code": None},
        {"reason_code": "ADMISSION_DENIED"},
        {"reason_code": "not-a-reason"},
        {"graph_version": {"state_root": "a" * 64}},
    ],
)
def test_malformed_or_coercing_payloads_fail(override: dict[str, Any]) -> None:
    with pytest.raises(LedgerValidationError):
        parse_payload(**override)


@pytest.mark.parametrize("reason,outcome", list(FINAL_OUTCOME_BY_REASON.items()))
def test_all_released_outcome_reason_pairs_and_incoherence(reason: str, outcome: str) -> None:
    payload = parse_payload(reason_code=reason, outcome=outcome)
    assert payload.outcome == outcome
    with pytest.raises(LedgerValidationError):
        parse_payload(reason_code=reason, outcome="ALLOW")


@pytest.mark.parametrize(
    "setting,value", [("strict", False), ("frozen", False), ("extra", "ignore")]
)
def test_weakened_event_models_are_not_admissible(setting: str, value: object) -> None:
    class Weakened(PolicyDecisionRecorded):
        model_config = ConfigDict(**{**PolicyDecisionRecorded.model_config, setting: value})

    with pytest.raises(LedgerValidationError, match="strict frozen config"):
        EventRegistry().register(Weakened)


def test_frozen_snapshot_and_exact_class_cannot_be_bypassed() -> None:
    payload = parse_payload()
    with pytest.raises(ValidationError):
        payload.decision_digest = "0" * 64
    with pytest.raises(ValidationError):
        payload.graph_version.state_root = "0" * 64
    copy = payload.to_ledger_payload()
    copy["graph_version"]["state_root"] = "0" * 64
    assert canonical_json(payload.to_ledger_payload()) == GOLDEN_JSON
    corrupted = payload.model_copy(update={"decision_digest": "0" * 64})
    with pytest.raises(LedgerValidationError, match="mutated"):
        to_draft(corrupted, envelope(), registry=policy_decision_registry())

    class Alternate(PolicyDecisionRecorded):
        pass

    alternate = Alternate.model_validate_json(GOLDEN_JSON)
    with pytest.raises(LedgerValidationError, match="payload class"):
        to_draft(alternate, envelope(), registry=policy_decision_registry())


@pytest.mark.parametrize(
    "override", [None, {"runtime_gate_result_digest": "bad"}, {"outcome": "DENY"}]
)
def test_invalid_evaluator_return_or_event_projection_fails_closed(
    override: dict[str, Any] | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = evaluation_inputs()
    decision = evaluate_policy(**inputs)
    returned = object() if override is None else decision.model_copy(update=override)
    monkeypatch.setattr(evaluation_facts, "evaluate_policy", Mock(return_value=returned))
    expected_error = EvaluationBindingError if override is None else LedgerValidationError
    with pytest.raises(expected_error):
        evaluate_persistence_facts(**inputs)
