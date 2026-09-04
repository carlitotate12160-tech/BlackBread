"""Shared valid-proposal builder for conductor and policy contract tests."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from blackbread.conductor.contracts import (
    ActionProposal,
    BudgetRequest,
    GraphVersionReference,
    ParameterEnvelope,
    ResourceEstimates,
    TargetReference,
)

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64


def graph_version(**overrides: Any) -> GraphVersionReference:
    fields: dict[str, Any] = {
        "state_root_version": 2,
        "projector_version": 1,
        "state_root": HEX_A,
        "ledger_event_count": 7,
        "ledger_head_hash": HEX_B,
    }
    fields.update(overrides)
    return GraphVersionReference(**fields)


def proposal_fields(**overrides: Any) -> dict[str, Any]:
    created = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    fields: dict[str, Any] = {
        "schema_name": "conductor.action_proposal",
        "schema_version": 1,
        "proposal_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "tenant_id": "tenant-a",
        "engagement_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "agent_instance_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "agent_role": "Scout",
        "capability_id": "scout.passive_asset_intelligence.v1",
        "target": TargetReference(target_kind="root_domain", canonical_value="example.com"),
        "parameter_envelope": ParameterEnvelope(
            input_schema_ref="PassiveAssetIntelligenceInput.v1",
            parameters={"depth": 1, "sources": ["ct", "dns"]},
        ),
        "intended_proof": "asset-ownership-observation",
        "precondition_refs": ("scope-attested",),
        "oracle_ref": "source-provenanced-observation",
        "estimates": ResourceEstimates(risk=0.1, cost=2.0, information_gain=0.4, opsec_noise=0.2),
        "requested_budget": BudgetRequest(target_requests=0, deadline_seconds=30),
        "target_identity_tier": "T0",
        "graph_version": graph_version(),
        "idempotency_key": "idem-0001",
        "created_at": created,
        "expires_at": created + timedelta(minutes=15),
    }
    fields.update(overrides)
    return fields


def make_proposal(**overrides: Any) -> ActionProposal:
    return ActionProposal(**proposal_fields(**overrides))


def _jsonify(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _jsonify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def raw_proposal(**overrides: Any) -> dict[str, Any]:
    fields = proposal_fields(**overrides)
    fields["target"] = {
        "target_kind": fields["target"].target_kind,
        "canonical_value": fields["target"].canonical_value,
    }
    envelope = fields["parameter_envelope"]
    fields["parameter_envelope"] = {
        "input_schema_ref": envelope.input_schema_ref,
        "parameters": dict(envelope.parameters),
    }
    estimates = fields["estimates"]
    fields["estimates"] = {
        "risk": estimates.risk,
        "cost": estimates.cost,
        "information_gain": estimates.information_gain,
        "opsec_noise": estimates.opsec_noise,
    }
    budget = fields["requested_budget"]
    fields["requested_budget"] = {
        "target_requests": budget.target_requests,
        "deadline_seconds": budget.deadline_seconds,
    }
    graph = fields["graph_version"]
    fields["graph_version"] = {
        "state_root_version": graph.state_root_version,
        "projector_version": graph.projector_version,
        "state_root": graph.state_root,
        "ledger_event_count": graph.ledger_event_count,
        "ledger_head_hash": graph.ledger_head_hash,
    }
    return {key: _jsonify(value) for key, value in fields.items()}
