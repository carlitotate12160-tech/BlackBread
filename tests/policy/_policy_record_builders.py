"""Coherent normalized policy-record row builders and insert helpers for M1.4c1 tests.

Rows are derived from the real released ``ActionProposal`` v1 and ``PolicyDecisionV2`` contracts so
a valid row is genuinely coherent. Negative tests override a single column on a valid row and assert
the specific PostgreSQL constraint rejects it. Inserts go through parameterized raw SQL (not the
ORM) so malformed rows reach the database instead of being stopped by Pydantic.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from blackbread.conductor.contracts import ActionProposal
from blackbread.ledger.hashing import compute_payload_hash
from blackbread.policy.decision_v2 import PolicyDecisionV2
from tests.conductor._builders import make_proposal

_JSONB_COLUMNS = frozenset({"parameters", "precondition_refs"})
GENESIS_HASH = "0" * 64

PROPOSAL_COLUMNS = (
    "schema_name",
    "schema_version",
    "proposal_id",
    "tenant_id",
    "engagement_id",
    "agent_instance_id",
    "agent_role",
    "capability_id",
    "target_kind",
    "target_value",
    "input_schema_ref",
    "parameters",
    "intended_proof",
    "precondition_refs",
    "oracle_ref",
    "risk",
    "cost",
    "information_gain",
    "opsec_noise",
    "target_requests",
    "deadline_seconds",
    "target_identity_tier",
    "graph_state_root_version",
    "graph_projector_version",
    "graph_state_root",
    "graph_ledger_event_count",
    "graph_ledger_head_hash",
    "idempotency_key",
    "created_at",
    "expires_at",
    "proposal_digest",
)
DECISION_COLUMNS = (
    "schema_name",
    "schema_version",
    "decision_id",
    "tenant_id",
    "engagement_id",
    "proposal_id",
    "proposal_digest",
    "decision_authority",
    "outcome",
    "reason_code",
    "decided_at",
    "graph_state_root_version",
    "graph_projector_version",
    "graph_state_root",
    "graph_ledger_event_count",
    "graph_ledger_head_hash",
    "runtime_gate_result_digest",
    "decision_digest",
)


def proposal_row(proposal: ActionProposal | None = None, **overrides: Any) -> dict[str, Any]:
    """Return a coherent action_proposals row derived from a real ActionProposal v1."""
    p = proposal or make_proposal(**_proposal_field_overrides(overrides))
    graph = p.graph_version
    row: dict[str, Any] = {
        "schema_name": p.schema_name,
        "schema_version": p.schema_version,
        "proposal_id": p.proposal_id,
        "tenant_id": p.tenant_id,
        "engagement_id": p.engagement_id,
        "agent_instance_id": p.agent_instance_id,
        "agent_role": p.agent_role,
        "capability_id": p.capability_id,
        "target_kind": p.target.target_kind,
        "target_value": p.target.canonical_value,
        "input_schema_ref": p.parameter_envelope.input_schema_ref,
        "parameters": json.loads(p.parameter_envelope.canonical_parameters),
        "intended_proof": p.intended_proof,
        "precondition_refs": list(p.precondition_refs),
        "oracle_ref": p.oracle_ref,
        "risk": p.estimates.risk,
        "cost": p.estimates.cost,
        "information_gain": p.estimates.information_gain,
        "opsec_noise": p.estimates.opsec_noise,
        "target_requests": p.requested_budget.target_requests,
        "deadline_seconds": p.requested_budget.deadline_seconds,
        "target_identity_tier": p.target_identity_tier,
        "graph_state_root_version": graph.state_root_version,
        "graph_projector_version": graph.projector_version,
        "graph_state_root": graph.state_root,
        "graph_ledger_event_count": graph.ledger_event_count,
        "graph_ledger_head_hash": graph.ledger_head_hash,
        "idempotency_key": p.idempotency_key,
        "created_at": p.created_at,
        "expires_at": p.expires_at,
        "proposal_digest": p.proposal_digest,
    }
    row.update(overrides)
    return row


def decision_row(
    source: dict[str, Any],
    *,
    build_outcome: str = "ALLOW",
    build_reason: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Return a decision_records row whose lineage matches ``source`` (a proposal row).

    ``build_outcome``/``build_reason`` select the coherent pair built through the real
    ``PolicyDecisionV2`` contract; ``overrides`` then replace individual columns for negative tests
    (including deliberately incoherent outcome/reason rows the contract itself would reject).
    """
    fields: dict[str, Any] = {
        "schema_name": "policy.decision",
        "schema_version": 2,
        "decision_id": uuid.uuid4(),
        "tenant_id": source["tenant_id"],
        "engagement_id": source["engagement_id"],
        "proposal_id": source["proposal_id"],
        "proposal_digest": source["proposal_digest"],
        "decision_authority": "policy.kernel.v2",
        "outcome": build_outcome,
        "reason_code": build_reason,
        "decided_at": datetime(2026, 9, 3, 12, 30, tzinfo=UTC),
        "graph_version": {
            "state_root_version": source["graph_state_root_version"],
            "projector_version": source["graph_projector_version"],
            "state_root": source["graph_state_root"],
            "ledger_event_count": source["graph_ledger_event_count"],
            "ledger_head_hash": source["graph_ledger_head_hash"],
        },
        "runtime_gate_result_digest": "c" * 64,
    }
    decision = PolicyDecisionV2.build(fields)
    row = {
        "schema_name": decision.schema_name,
        "schema_version": decision.schema_version,
        "decision_id": decision.decision_id,
        "tenant_id": decision.tenant_id,
        "engagement_id": decision.engagement_id,
        "proposal_id": decision.proposal_id,
        "proposal_digest": decision.proposal_digest,
        "decision_authority": decision.decision_authority,
        "outcome": decision.outcome,
        "reason_code": decision.reason_code,
        "decided_at": decision.decided_at,
        "graph_state_root_version": decision.graph_version.state_root_version,
        "graph_projector_version": decision.graph_version.projector_version,
        "graph_state_root": decision.graph_version.state_root,
        "graph_ledger_event_count": decision.graph_version.ledger_event_count,
        "graph_ledger_head_hash": decision.graph_version.ledger_head_hash,
        "runtime_gate_result_digest": decision.runtime_gate_result_digest,
        "decision_digest": decision.decision_digest,
    }
    row.update(overrides)
    return row


def _proposal_field_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    """Pop proposal-construction overrides (ids/tenant) so ``make_proposal`` sees them."""
    passthrough = {}
    for key in ("proposal_id", "tenant_id", "engagement_id", "idempotency_key"):
        if key in overrides:
            passthrough[key] = overrides.pop(key)
    return passthrough


def _insert(table: str, columns: tuple[str, ...]) -> str:
    # table and columns are controlled module constants, never external input.
    placeholders = ", ".join(
        f"CAST(:{c} AS jsonb)" if c in _JSONB_COLUMNS else f":{c}" for c in columns
    )
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"  # noqa: S608


def _params(columns: tuple[str, ...], row: dict[str, Any]) -> dict[str, Any]:
    return {c: json.dumps(row[c]) if c in _JSONB_COLUMNS else row[c] for c in columns}


async def insert_proposal(conn: AsyncConnection, row: dict[str, Any]) -> None:
    """Insert an action_proposals row via parameterized raw SQL."""
    statement = text(_insert("action_proposals", PROPOSAL_COLUMNS))
    await conn.execute(statement, _params(PROPOSAL_COLUMNS, row))


async def insert_decision(conn: AsyncConnection, row: dict[str, Any]) -> None:
    """Insert a decision_records row via parameterized raw SQL."""
    statement = text(_insert("decision_records", DECISION_COLUMNS))
    await conn.execute(statement, _params(DECISION_COLUMNS, row))


# --- policy.decision.recorded v1 event fixtures (M1.4c2b0b) -----------------------------------

_EVENT_JSONB = frozenset({"payload", "redaction_refs"})


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def decision_event_payload(proposal: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Return the exact policy.decision.recorded v1 payload for a proposal/decision row pair."""
    return {
        "decision_schema_name": decision["schema_name"],
        "decision_schema_version": decision["schema_version"],
        "proposal_id": str(proposal["proposal_id"]),
        "proposal_digest": proposal["proposal_digest"],
        "idempotency_key": proposal["idempotency_key"],
        "decision_id": str(decision["decision_id"]),
        "decision_authority": decision["decision_authority"],
        "outcome": decision["outcome"],
        "reason_code": decision["reason_code"],
        "decided_at": _iso(decision["decided_at"]),
        "graph_version": {
            "state_root_version": decision["graph_state_root_version"],
            "projector_version": decision["graph_projector_version"],
            "state_root": decision["graph_state_root"],
            "ledger_event_count": decision["graph_ledger_event_count"],
            "ledger_head_hash": decision["graph_ledger_head_hash"],
        },
        "runtime_gate_result_digest": decision["runtime_gate_result_digest"],
        "decision_digest": decision["decision_digest"],
    }


def decision_event_row(
    proposal: dict[str, Any],
    decision: dict[str, Any],
    *,
    sequence: int = 1,
    prev_event_hash: str = GENESIS_HASH,
    **overrides: Any,
) -> dict[str, Any]:
    """Return a coherent agent_events row for a policy.decision.recorded v1 event.

    ``policy_decision_id`` is intentionally omitted: the 0009 trigger derives it from causation.
    """
    payload = overrides.pop("payload", None)
    if payload is None:
        payload = decision_event_payload(proposal, decision)
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "engagement_id": decision["engagement_id"],
        "tenant_id": decision["tenant_id"],
        "sequence": sequence,
        "schema_name": "policy.decision.recorded",
        "schema_version": 1,
        "producer": "policy-record-transaction.v1",
        "correlation_id": proposal["proposal_id"],
        "causation_id": decision["decision_id"],
        "occurred_at": decision["decided_at"],
        "recorded_at": decision["decided_at"],
        "payload": payload,
        "payload_hash": compute_payload_hash(payload),
        "prev_event_hash": prev_event_hash,
        "event_hash": uuid.uuid4().hex + uuid.uuid4().hex,
        "sensitivity": "internal",
        "redaction_refs": [],
    }
    row.update(overrides)
    return row


async def insert_agent_event(conn: AsyncConnection, row: dict[str, Any]) -> None:
    """Insert an agent_events row via parameterized raw SQL (honouring extra override columns)."""
    columns = tuple(row.keys())
    placeholders = ", ".join(
        f"CAST(:{c} AS jsonb)" if c in _EVENT_JSONB else f":{c}" for c in columns
    )
    statement = text(
        f"INSERT INTO agent_events ({', '.join(columns)}) VALUES ({placeholders})"  # noqa: S608
    )
    params = {c: json.dumps(row[c]) if c in _EVENT_JSONB else row[c] for c in columns}
    await conn.execute(statement, params)
