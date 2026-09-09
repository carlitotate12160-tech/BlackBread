from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from uuid import UUID

import pytest

from blackbread.policy import evaluation_facts
from blackbread.policy.decision_v2 import PolicyDecisionV2
from blackbread.policy.evaluation import PolicyEvaluationError, evaluate_policy
from blackbread.policy.evaluation_facts import (
    EvaluationBindingError,
    EvaluationPersistenceFacts,
    evaluate_persistence_facts,
)
from tests.conductor._builders import graph_version, make_proposal
from tests.policy._builders import capability_snapshot
from tests.policy._runtime_builders import runtime_case

DECISION_ID = UUID("44444444-4444-4444-4444-444444444444")
OTHER_ID = UUID("99999999-9999-9999-9999-999999999999")
DECIDED_AT = datetime(2026, 9, 3, 12, 5, 0, 123456, tzinfo=UTC)
PRODUCTION_ROOT = Path(__file__).parents[2] / "src" / "blackbread"


def evaluation_inputs(**overrides: Any) -> dict[str, Any]:
    at = overrides.pop("evaluated_at", DECIDED_AT)
    values = runtime_case(evaluated_at=at, **overrides)
    values["decided_at"] = values.pop("evaluated_at")
    return {**values, "decision_id": DECISION_ID}


@pytest.mark.parametrize("denied", [False, True])
def test_real_evaluation_and_exact_projection(denied: bool) -> None:
    capability = capability_snapshot(required_identity_tier="T1" if denied else "T0")
    inputs = evaluation_inputs(capability=capability)
    proposal = inputs["proposal"]
    expected = evaluate_policy(**inputs)
    result = evaluate_persistence_facts(**inputs)
    decision, draft = result.decision, result.draft
    assert result.proposal is proposal
    assert decision == expected
    assert (decision.outcome, decision.reason_code) == (
        ("DENY", "ADMISSION_DENIED") if denied else ("ALLOW", None)
    )
    assert draft.materialize_payload() == {
        "decision_schema_name": "policy.decision",
        "decision_schema_version": 2,
        "proposal_id": str(proposal.proposal_id),
        "proposal_digest": proposal.proposal_digest,
        "idempotency_key": proposal.idempotency_key,
        "decision_id": str(DECISION_ID),
        "decision_authority": "policy.kernel.v2",
        "outcome": expected.outcome,
        "reason_code": expected.reason_code,
        "decided_at": "2026-09-03T12:05:00.123456Z",
        "graph_version": graph_version().model_dump(mode="json"),
        "runtime_gate_result_digest": expected.runtime_gate_result_digest,
        "decision_digest": expected.decision_digest,
    }
    assert (draft.tenant_id, draft.engagement_id) == (proposal.tenant_id, proposal.engagement_id)
    assert (draft.schema_name, draft.schema_version) == ("policy.decision.recorded", 1)
    assert (draft.producer, draft.sensitivity) == ("policy-record-transaction.v1", "internal")
    assert (draft.correlation_id, draft.causation_id) == (proposal.proposal_id, DECISION_ID)
    assert draft.redaction_refs == ()
    assert inputs["decided_at"] == decision.decided_at == draft.occurred_at


def test_one_real_call_retains_exact_inputs_and_return(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = evaluation_inputs()
    computed = []

    def observe(*args: Any, **kwargs: Any) -> PolicyDecisionV2:
        decision = evaluate_policy(*args, **kwargs)
        computed.append(decision)
        return decision

    spy = Mock(side_effect=observe)
    monkeypatch.setattr(evaluation_facts, "evaluate_policy", spy)
    result = evaluate_persistence_facts(**inputs)
    assert spy.call_count == 1
    assert spy.call_args.args == (inputs["proposal"],)
    assert spy.call_args.args[0] is inputs["proposal"]
    for name, value in inputs.items():
        if name != "proposal":
            assert spy.call_args.kwargs[name] is value
    assert result.proposal is inputs["proposal"]
    assert result.decision is computed[0]


@pytest.mark.parametrize(
    "name",
    [
        "decision",
        "runtime_result",
        "admission_result",
        "event_payload",
        "digest",
        "producer",
        "envelope",
        "outcome",
        "reason",
        "decision_digest",
        "facts",
        "draft",
    ],
)
def test_no_intermediate_injection_seam(name: str) -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        evaluate_persistence_facts(**evaluation_inputs(), **{name: object()})


def test_signature_accepts_only_declared_facts_and_stamp() -> None:
    signature = inspect.signature(evaluate_persistence_facts)
    assert set(signature.parameters) == {
        "proposal",
        "policy",
        "identity",
        "capability",
        "manifest",
        "runtime",
        "decision_id",
        "decided_at",
    }
    forbidden = (
        "AdmissionResult",
        "RuntimeGateResult",
        "PolicyDecisionV2",
        "EvaluationPersistenceFacts",
        "EventPayload",
        "EventDraft",
        "EventEnvelope",
    )
    for parameter in signature.parameters.values():
        assert not any(name in str(parameter.annotation) for name in forbidden)
        assert parameter.kind not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)


@pytest.mark.parametrize(
    "name", ["proposal", "policy", "identity", "capability", "manifest", "runtime", "decision_id"]
)
def test_malformed_inputs_keep_evaluator_error(name: str) -> None:
    inputs = evaluation_inputs()
    inputs[name] = object()
    with pytest.raises(PolicyEvaluationError):
        evaluate_persistence_facts(**inputs)


@pytest.mark.parametrize(
    "at",
    [
        None,
        "2026-09-03T12:05:00Z",
        datetime(2026, 9, 3),
        datetime(2026, 9, 3, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_invalid_stamp_keeps_evaluator_error(at: object) -> None:
    inputs = evaluation_inputs()
    inputs["decided_at"] = at
    with pytest.raises(PolicyEvaluationError):
        evaluate_persistence_facts(**inputs)


@pytest.mark.parametrize("boundary", ["before", "expiry", "after"])
def test_denials_outside_proposal_validity_keep_exact_time(boundary: str) -> None:
    proposal = make_proposal()
    at = {
        "before": proposal.created_at - timedelta(microseconds=1),
        "expiry": proposal.expires_at,
        "after": proposal.expires_at + timedelta(microseconds=1),
    }[boundary]
    result = evaluate_persistence_facts(**evaluation_inputs(proposal=proposal, evaluated_at=at))
    assert (result.decision.outcome, result.decision.reason_code) == ("DENY", "ADMISSION_DENIED")
    assert result.decision.decided_at == result.draft.occurred_at == at
    assert result.draft.payload["decided_at"] == at.isoformat().replace("+00:00", "Z")


@pytest.mark.parametrize("override", [{"tenant_id": "tenant-b"}, {"engagement_id": OTHER_ID}])
def test_incoherent_runtime_is_a_real_recordable_denial(override: dict[str, Any]) -> None:
    inputs = evaluation_inputs(
        budget=None, lock=None, engagement=None, opsec=None, approval_grant=None, **override
    )
    result = evaluate_persistence_facts(**inputs)
    assert result.decision == evaluate_policy(**inputs)
    assert (result.decision.outcome, result.decision.reason_code) == (
        "DENY",
        "RUNTIME_BINDING_MISMATCH",
    )
    assert result.draft.tenant_id == inputs["proposal"].tenant_id
    assert result.draft.engagement_id == inputs["proposal"].engagement_id


@pytest.mark.parametrize(
    "override",
    [
        {"tenant_id": "tenant-b"},
        {"engagement_id": OTHER_ID},
        {"proposal_id": OTHER_ID},
        {"proposal_digest": "0" * 64},
        {"decision_id": OTHER_ID},
        {"decided_at": DECIDED_AT + timedelta(microseconds=1)},
        *(
            {"graph_version": graph_version(**{name: value})}
            for name, value in (
                ("state_root_version", 1),
                ("projector_version", 2),
                ("state_root", "c" * 64),
                ("ledger_event_count", 8),
                ("ledger_head_hash", "c" * 64),
            )
        ),
    ],
)
def test_valid_substituted_decisions_fail_binding(
    override: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = evaluation_inputs()
    original = evaluate_policy(**inputs)
    substitute = PolicyDecisionV2.build(
        {
            **original.model_dump(exclude={"decision_digest"}),
            **override,
        }
    )
    assert PolicyDecisionV2.model_validate_json(substitute.model_dump_json()) == substitute
    spy = Mock(return_value=substitute)
    monkeypatch.setattr(evaluation_facts, "evaluate_policy", spy)
    with pytest.raises(EvaluationBindingError):
        evaluate_persistence_facts(**inputs)
    assert spy.call_count == 1


@pytest.mark.parametrize(
    "override",
    [
        {"decision_authority": "other.producer"},
        {"schema_name": "other.decision"},
        {"schema_version": 1},
        {"decided_at": DECIDED_AT.astimezone(timezone(timedelta(hours=1)))},
    ],
)
def test_related_authority_or_timestamp_corruption_fails_binding(
    override: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = evaluation_inputs()
    substitute = evaluate_policy(**inputs).model_copy(update=override)
    monkeypatch.setattr(evaluation_facts, "evaluate_policy", Mock(return_value=substitute))
    with pytest.raises(EvaluationBindingError):
        evaluate_persistence_facts(**inputs)


def test_binding_and_draft_are_frozen_snapshots_not_authentication() -> None:
    result = evaluate_persistence_facts(**evaluation_inputs())
    assert {item.name for item in fields(result)} == {"proposal", "decision", "draft"}
    with pytest.raises(FrozenInstanceError):
        result.proposal = make_proposal()
    with pytest.raises(FrozenInstanceError):
        result.draft.occurred_at = DECIDED_AT + timedelta(seconds=1)
    with pytest.raises(TypeError):
        result.draft.payload["outcome"] = "DENY"
    payload = result.draft.materialize_payload()
    payload["graph_version"]["state_root"] = "0" * 64
    assert result.draft.materialize_payload()["graph_version"] == graph_version().model_dump()
    constructed = EvaluationPersistenceFacts(proposal=result.proposal, decision=result.decision)
    assert constructed.draft == result.draft


def test_intentional_non_wiring_until_m1_4c2b() -> None:
    module_path = Path(evaluation_facts.__file__).resolve()
    for path in PRODUCTION_ROOT.rglob("*.py"):
        if path.resolve() != module_path:
            assert "evaluation_facts" not in path.read_text(encoding="utf-8"), str(path)
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    allowed = {
        "__future__",
        "dataclasses",
        "datetime",
        "functools",
        "typing",
        "uuid",
        "pydantic",
        "blackbread.conductor.contracts",
        "blackbread.ledger.draft",
        "blackbread.ledger.errors",
        "blackbread.ledger.schema",
        "blackbread.policy.admission_contracts",
        "blackbread.policy.decision_v2",
        "blackbread.policy.evaluation",
        "blackbread.policy.runtime_contracts",
        "blackbread.policy.runtime_result",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module in allowed
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        if isinstance(node, ast.Call):
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", "")
            )
            assert name not in {
                "now",
                "utcnow",
                "time",
                "uuid4",
                "open",
                "eval",
                "exec",
                "__import__",
            }
