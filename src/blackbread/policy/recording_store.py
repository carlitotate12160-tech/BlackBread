"""Strict row projection and routine invocation for the M1.4c2b1 evaluate-and-record substrate.

Owns the database-facing half of the policy-record transaction: the engagement lock, the three
idempotency/conflict lookups, the durable-completion read used to reconcile a retry, and the single
call into the recorder-owned ``public.blackbread_record_policy_decision`` routine. Every write goes
through that ``SECURITY DEFINER`` routine (migration 0010) as the reserved recorder identity; this
module never inserts into ``action_proposals``/``decision_records`` directly and holds no policy
logic. Composite parameters are projected column-by-column with explicit PostgreSQL type casts, so a
shape drift fails loudly at the cast rather than silently through a permissive JSON object.

M1.4c2b1a ships this store dormant: no production module imports it and ``blackbread_runtime``
holds no EXECUTE privilege on the routine. Decision input is a flat storage spec
(``PolicyDecisionRecord``), deliberately not the policy-domain ``PolicyDecisionV2`` contract — the
conductor boundary tests pin ``decision_v2``'s importer set to the evaluator layer, so the dormant
store keeps the policy domain out of the persistence layer. The durable-completion read returns the
raw committed row; the activating M1.4c2b1b boundary owns domain reconstruction and digest
re-verification.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from blackbread.conductor.contracts import ActionProposal
from blackbread.ledger.event import AgentEvent

ROUTINE = "blackbread_record_policy_decision"
POLICY_EVENT_SCHEMA = "policy.decision.recorded"


@dataclass(frozen=True, slots=True)
class PolicyDecisionRecord:
    """The exact ``decision_records`` column set the recorder routine persists.

    Storage-level specification: flat columns in table order, including the expanded
    ``graph_version`` components and both digests. This is the write/read shape of the durable
    decision row, not an authoritative Policy outcome.
    """

    schema_name: str
    schema_version: int
    decision_id: uuid.UUID
    tenant_id: str
    engagement_id: uuid.UUID
    proposal_id: uuid.UUID
    proposal_digest: str
    decision_authority: str
    outcome: str
    reason_code: str | None
    decided_at: datetime
    graph_state_root_version: int
    graph_projector_version: int
    graph_state_root: str
    graph_ledger_event_count: int
    graph_ledger_head_hash: str
    runtime_gate_result_digest: str
    decision_digest: str


# ``column:pgtype`` tokens in the exact physical order of each table, so ``ROW(...)::table`` casts
# bind positionally. Any future column added to a table breaks the cast loudly, which is intended.
# ``float8`` (not ``double precision``) keeps every type token whitespace-free for the parser.
def _columns(spec: str) -> tuple[tuple[str, str], ...]:
    return tuple((name, pgtype) for name, pgtype in (token.split(":", 1) for token in spec.split()))


_PROPOSAL_COLUMNS = _columns(
    "schema_name:varchar schema_version:integer proposal_id:uuid tenant_id:varchar "
    "engagement_id:uuid agent_instance_id:uuid agent_role:varchar capability_id:varchar "
    "target_kind:varchar target_value:varchar input_schema_ref:varchar parameters:jsonb "
    "intended_proof:varchar precondition_refs:jsonb oracle_ref:varchar risk:float8 cost:float8 "
    "information_gain:float8 opsec_noise:float8 target_requests:bigint deadline_seconds:integer "
    "target_identity_tier:varchar graph_state_root_version:integer graph_projector_version:integer "
    "graph_state_root:varchar graph_ledger_event_count:bigint graph_ledger_head_hash:varchar "
    "idempotency_key:varchar created_at:timestamptz expires_at:timestamptz proposal_digest:varchar"
)
_DECISION_COLUMNS = _columns(
    "schema_name:varchar schema_version:integer decision_id:uuid tenant_id:varchar "
    "engagement_id:uuid proposal_id:uuid proposal_digest:varchar decision_authority:varchar "
    "outcome:varchar reason_code:varchar decided_at:timestamptz graph_state_root_version:integer "
    "graph_projector_version:integer graph_state_root:varchar graph_ledger_event_count:bigint "
    "graph_ledger_head_hash:varchar runtime_gate_result_digest:varchar decision_digest:varchar"
)
_EVENT_COLUMNS = _columns(
    "id:uuid engagement_id:uuid tenant_id:varchar sequence:bigint schema_name:varchar "
    "schema_version:integer producer:varchar correlation_id:uuid causation_id:uuid "
    "occurred_at:timestamptz recorded_at:timestamptz payload:jsonb payload_hash:varchar "
    "prev_event_hash:varchar event_hash:varchar hash_algorithm:varchar hash_version:integer "
    "sensitivity:varchar redaction_refs:jsonb policy_decision_id:uuid"
)


def _row_expression(prefix: str, columns: tuple[tuple[str, str], ...], composite: str) -> str:
    fields = ", ".join(f"CAST(:{prefix}_{name} AS {pgtype})" for name, pgtype in columns)
    return f"ROW({fields})::public.{composite}"


_ROUTINE_SQL = text(
    f"SELECT public.{ROUTINE}("
    f"{_row_expression('p', _PROPOSAL_COLUMNS, 'action_proposals')}, "
    f"{_row_expression('d', _DECISION_COLUMNS, 'decision_records')}, "
    f"{_row_expression('e', _EVENT_COLUMNS, 'agent_events')})"
)


@dataclass(frozen=True, slots=True)
class StoredProposal:
    """The identity columns of an already-committed proposal used for conflict resolution."""

    proposal_id: uuid.UUID
    idempotency_key: str
    proposal_digest: str
    tenant_id: str
    engagement_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ProposalMatches:
    """The (at most one) stored proposal found by each of the three proposal identities."""

    by_id: StoredProposal | None
    by_key: StoredProposal | None
    by_digest: StoredProposal | None


@dataclass(frozen=True, slots=True)
class DurableCompletion:
    """The committed decision row plus event identity for a proposal, with exact multiplicities.

    ``decision`` is the raw durable ``decision_records`` row, not a domain decision: the policy
    layer owns ``PolicyDecisionV2`` reconstruction and digest re-verification (M1.4c2b1b).
    """

    decision: Mapping[str, Any] | None
    decision_count: int
    event_count: int
    event_id: uuid.UUID | None
    event_sequence: int | None
    event_hash: str | None


async def lock_engagement(session: AsyncSession, tenant_id: str, engagement_id: uuid.UUID) -> bool:
    """Take the engagement row lock before replay resolution and evaluation; report its presence."""
    locked = await session.scalar(
        text("SELECT id FROM engagements WHERE id = :e AND tenant_id = :t FOR UPDATE"),
        {"e": engagement_id, "t": tenant_id},
    )
    return locked is not None


_PROPOSAL_IDENTITY_SQL = (
    "SELECT proposal_id, idempotency_key, proposal_digest, tenant_id, engagement_id "
    "FROM action_proposals WHERE tenant_id = :t AND engagement_id = :e AND {predicate}"
)


async def _stored_proposal(
    session: AsyncSession, predicate: str, params: dict[str, Any]
) -> StoredProposal | None:
    row = (
        (await session.execute(text(_PROPOSAL_IDENTITY_SQL.format(predicate=predicate)), params))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return StoredProposal(
        proposal_id=row["proposal_id"],
        idempotency_key=row["idempotency_key"],
        proposal_digest=row["proposal_digest"],
        tenant_id=row["tenant_id"],
        engagement_id=row["engagement_id"],
    )


async def find_proposal_matches(session: AsyncSession, proposal: ActionProposal) -> ProposalMatches:
    """Resolve the proposal by id, by idempotency key, and by digest under its tenant/engagement."""
    base = {"t": proposal.tenant_id, "e": proposal.engagement_id}
    return ProposalMatches(
        by_id=await _stored_proposal(
            session, "proposal_id = :v", {**base, "v": proposal.proposal_id}
        ),
        by_key=await _stored_proposal(
            session, "idempotency_key = :v", {**base, "v": proposal.idempotency_key}
        ),
        by_digest=await _stored_proposal(
            session, "proposal_digest = :v", {**base, "v": proposal.proposal_digest}
        ),
    )


async def load_durable_completion(
    session: AsyncSession, tenant_id: str, engagement_id: uuid.UUID, proposal_id: uuid.UUID
) -> DurableCompletion:
    """Read the committed decision and its policy event for a proposal, with exact counts."""
    decision_rows = (
        (
            await session.execute(
                text(
                    "SELECT * FROM decision_records "
                    "WHERE tenant_id = :t AND engagement_id = :e AND proposal_id = :p"
                ),
                {"t": tenant_id, "e": engagement_id, "p": proposal_id},
            )
        )
        .mappings()
        .all()
    )
    decision = dict(decision_rows[0]) if len(decision_rows) == 1 else None
    if decision is None:
        return DurableCompletion(None, len(decision_rows), 0, None, None, None)
    return await _attach_event(session, decision, len(decision_rows))


async def _attach_event(
    session: AsyncSession, decision: Mapping[str, Any], decision_count: int
) -> DurableCompletion:
    events = (
        (
            await session.execute(
                text(
                    "SELECT id, sequence, event_hash FROM agent_events "
                    "WHERE tenant_id = :t AND engagement_id = :e "
                    "AND schema_name = :s AND causation_id = :c"
                ),
                {
                    "t": decision["tenant_id"],
                    "e": decision["engagement_id"],
                    "s": POLICY_EVENT_SCHEMA,
                    "c": decision["decision_id"],
                },
            )
        )
        .mappings()
        .all()
    )
    if len(events) != 1:
        return DurableCompletion(decision, decision_count, len(events), None, None, None)
    row = events[0]
    return DurableCompletion(
        decision, decision_count, 1, row["id"], row["sequence"], row["event_hash"]
    )


def _proposal_values(proposal: ActionProposal) -> dict[str, Any]:
    graph = proposal.graph_version
    return {
        "schema_name": proposal.schema_name,
        "schema_version": proposal.schema_version,
        "proposal_id": proposal.proposal_id,
        "tenant_id": proposal.tenant_id,
        "engagement_id": proposal.engagement_id,
        "agent_instance_id": proposal.agent_instance_id,
        "agent_role": proposal.agent_role,
        "capability_id": proposal.capability_id,
        "target_kind": proposal.target.target_kind,
        "target_value": proposal.target.canonical_value,
        "input_schema_ref": proposal.parameter_envelope.input_schema_ref,
        "parameters": proposal.parameter_envelope.canonical_parameters,
        "intended_proof": proposal.intended_proof,
        "precondition_refs": json.dumps(list(proposal.precondition_refs)),
        "oracle_ref": proposal.oracle_ref,
        "risk": proposal.estimates.risk,
        "cost": proposal.estimates.cost,
        "information_gain": proposal.estimates.information_gain,
        "opsec_noise": proposal.estimates.opsec_noise,
        "target_requests": proposal.requested_budget.target_requests,
        "deadline_seconds": proposal.requested_budget.deadline_seconds,
        "target_identity_tier": proposal.target_identity_tier,
        "graph_state_root_version": graph.state_root_version,
        "graph_projector_version": graph.projector_version,
        "graph_state_root": graph.state_root,
        "graph_ledger_event_count": graph.ledger_event_count,
        "graph_ledger_head_hash": graph.ledger_head_hash,
        "idempotency_key": proposal.idempotency_key,
        "created_at": proposal.created_at,
        "expires_at": proposal.expires_at,
        "proposal_digest": proposal.proposal_digest,
    }


def _decision_values(decision: PolicyDecisionRecord) -> dict[str, Any]:
    return {
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
        "graph_state_root_version": decision.graph_state_root_version,
        "graph_projector_version": decision.graph_projector_version,
        "graph_state_root": decision.graph_state_root,
        "graph_ledger_event_count": decision.graph_ledger_event_count,
        "graph_ledger_head_hash": decision.graph_ledger_head_hash,
        "runtime_gate_result_digest": decision.runtime_gate_result_digest,
        "decision_digest": decision.decision_digest,
    }


def _event_values(event: AgentEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "engagement_id": event.engagement_id,
        "tenant_id": event.tenant_id,
        "sequence": event.sequence,
        "schema_name": event.schema_name,
        "schema_version": event.schema_version,
        "producer": event.producer,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "occurred_at": event.occurred_at,
        "recorded_at": event.recorded_at,
        "payload": json.dumps(event.payload),
        "payload_hash": event.payload_hash,
        "prev_event_hash": event.prev_event_hash,
        "event_hash": event.event_hash,
        "hash_algorithm": event.hash_algorithm,
        "hash_version": event.hash_version,
        "sensitivity": event.sensitivity,
        "redaction_refs": json.dumps(list(event.redaction_refs)),
        "policy_decision_id": None,
    }


def _prefixed(prefix: str, values: dict[str, Any]) -> dict[str, Any]:
    return {f"{prefix}_{name}": value for name, value in values.items()}


async def latest_event_chain(
    session: AsyncSession, tenant_id: str, engagement_id: uuid.UUID
) -> tuple[int, str | None]:
    """Return (next sequence, previous event hash) for the engagement's ledger head."""
    row = (
        (
            await session.execute(
                text(
                    "SELECT sequence, event_hash FROM agent_events "
                    "WHERE tenant_id = :t AND engagement_id = :e "
                    "ORDER BY sequence DESC LIMIT 1"
                ),
                {"t": tenant_id, "e": engagement_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return 1, None
    return int(row["sequence"]) + 1, str(row["event_hash"])


async def invoke_record_routine(
    session: AsyncSession,
    proposal: ActionProposal,
    decision: PolicyDecisionRecord,
    event: AgentEvent,
) -> uuid.UUID:
    """Insert the proposal, decision, and event atomically via the recorder-owned routine."""
    params = {
        **_prefixed("p", _proposal_values(proposal)),
        **_prefixed("d", _decision_values(decision)),
        **_prefixed("e", _event_values(event)),
    }
    event_id = await session.scalar(_ROUTINE_SQL, params)
    if not isinstance(event_id, uuid.UUID):
        raise RuntimeError("policy record routine did not return an event id")
    return event_id
