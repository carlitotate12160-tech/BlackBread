"""Composed evaluate-and-record transaction boundary (M1.4c2b1b).

:func:`record_policy_decision` owns one session and transaction and wires
``evaluation_facts -> recording -> recording_store``: bind the explicit tenant, lock the engagement,
resolve the proposal's durable identity, evaluate a new proposal exactly once, materialize the exact
ledger event, project the decision into the flat storage record, and drive the recorder-owned
``SECURITY DEFINER`` routine so the proposal, decision, and ``policy.decision.recorded`` event
commit atomically or not at all. It is the only production importer of both ``evaluation_facts`` and
``recording_store``, and grants no execution authority: the :class:`PolicyRecordReceipt` is a
durable read-back, never a lease/work order/token, and an ALLOW row stays a Policy outcome.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from blackbread.conductor.contracts import ActionProposal
from blackbread.ledger.append import materialize_event
from blackbread.ledger.draft import EventDraft
from blackbread.ledger.errors import LedgerValidationError
from blackbread.ledger.event import AgentEvent
from blackbread.ledger.hashing import (
    GENESIS_PREV_HASH,
    HASH_ALGORITHM,
    HASH_VERSION,
    compute_event_hash,
    compute_payload_hash,
)
from blackbread.policy.admission_contracts import (
    CapabilityAdmissionSnapshot,
    DestinationManifest,
    EngagementPolicySnapshot,
    TargetIdentitySnapshot,
)
from blackbread.policy.decision_v2 import PolicyDecisionV2
from blackbread.policy.evaluation_facts import (
    EvaluationPersistenceFacts,
    evaluate_persistence_facts,
)
from blackbread.policy.recording_store import (
    DurableCompletion,
    PolicyDecisionRecord,
    ProposalMatches,
    find_proposal_matches,
    invoke_record_routine,
    latest_event_chain,
    load_durable_completion,
    lock_engagement,
)
from blackbread.policy.runtime_contracts import RuntimeGateSnapshot
from blackbread.tenancy import TenantContext, bind_tenant_context

# The caller supplies a factory that opens a fresh recorder-scoped session; the boundary owns the
# resulting session's single transaction. It never accepts a live session, so no partial or foreign
# transaction can leak in.
type RecorderSessionFactory = Callable[[], AsyncSession]


def _names(spec: str) -> tuple[str, ...]:
    """Split a space-delimited field spec into a name tuple, as ``recording_store`` does."""
    return tuple(spec.split())


class PolicyRecordingConflictError(Exception):
    """A submission collides with a stored proposal identity and is not an exact retry."""


class PolicyRecordingIntegrityError(Exception):
    """Durable multiplicity, lineage, digest, or event identity is incomplete or inconsistent."""


class PolicyRecordingUnavailableError(Exception):
    """The engagement cannot be locked for the bound tenant, so no decision may be recorded."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyRecordReceipt:
    """A validated durable receipt for one recorded policy decision.

    It reflects committed rows; it is not a lease, work order, token, or execution permission.
    ``replayed`` marks an exact retry reconstructed from durable columns without reevaluation.
    """

    decision: PolicyDecisionV2
    event_id: UUID
    event_sequence: int
    event_hash: str
    replayed: bool


def _utcnow() -> datetime:
    """Transaction-owned wall clock for the decision stamp; generated internally, never supplied."""
    return datetime.now(UTC)


async def record_policy_decision(  # noqa: PLR0913
    recorder_session_factory: RecorderSessionFactory,
    proposal: ActionProposal,
    *,
    tenant: TenantContext,
    policy: EngagementPolicySnapshot,
    identity: TargetIdentitySnapshot,
    capability: CapabilityAdmissionSnapshot,
    manifest: DestinationManifest,
    runtime: RuntimeGateSnapshot,
) -> PolicyRecordReceipt:
    """Evaluate and record one proposal atomically, or reconstruct its durable receipt on retry."""
    if tenant.tenant_id != proposal.tenant_id:
        raise PolicyRecordingIntegrityError("tenant context does not match the proposal tenant")
    # The boundary owns the session lifecycle: any exception (including cancellation) exits the
    # context manager without commit, rolling back the whole transaction and every partial row.
    async with recorder_session_factory() as session:
        # Bind the tenant transaction-locally before any lookup or write, then lock the engagement
        # before the replay lookup, stamp generation, evaluation, or ledger-head selection.
        await bind_tenant_context(session, tenant)
        if not await lock_engagement(session, proposal.tenant_id, proposal.engagement_id):
            raise PolicyRecordingUnavailableError("engagement is unavailable for the tenant")
        matches = await find_proposal_matches(session, proposal)
        if _is_new(matches):
            receipt = await _record_new(
                session,
                proposal,
                policy=policy,
                identity=identity,
                capability=capability,
                manifest=manifest,
                runtime=runtime,
            )
        else:
            _require_exact_retry(matches, proposal)
            receipt = await _replay(session, proposal)
        await session.commit()
        return receipt


def _is_new(matches: ProposalMatches) -> bool:
    return matches.by_id is None and matches.by_key is None and matches.by_digest is None


def _require_exact_retry(matches: ProposalMatches, proposal: ActionProposal) -> None:
    """Fail closed unless all three identities resolve to one stored proposal equal to ``proposal``.

    A partial match, a divergent match, or any stored identity differing from the submission is a
    conflict, never a replay.
    """
    by_id, by_key, by_digest = matches.by_id, matches.by_key, matches.by_digest
    if by_id is None or by_key is None or by_digest is None:
        raise PolicyRecordingConflictError("partial proposal-identity match")
    if not (by_id == by_key == by_digest):
        raise PolicyRecordingConflictError("divergent proposal-identity match")
    if (
        by_id.proposal_id != proposal.proposal_id
        or by_id.idempotency_key != proposal.idempotency_key
        or by_id.proposal_digest != proposal.proposal_digest
        or by_id.tenant_id != proposal.tenant_id
        or by_id.engagement_id != proposal.engagement_id
    ):
        raise PolicyRecordingConflictError("stored proposal identity diverges from the submission")


async def _record_new(  # noqa: PLR0913
    session: AsyncSession,
    proposal: ActionProposal,
    *,
    policy: EngagementPolicySnapshot,
    identity: TargetIdentitySnapshot,
    capability: CapabilityAdmissionSnapshot,
    manifest: DestinationManifest,
    runtime: RuntimeGateSnapshot,
) -> PolicyRecordReceipt:
    """Generate the stamp under the lock, evaluate once, and commit the exact triple."""
    # decision_id and decided_at are generated here, after the lock, and never accepted externally.
    facts = evaluate_persistence_facts(
        proposal,
        policy=policy,
        identity=identity,
        capability=capability,
        manifest=manifest,
        runtime=runtime,
        decision_id=uuid4(),
        decided_at=_utcnow(),
    )
    sequence, previous = await latest_event_chain(
        session, proposal.tenant_id, proposal.engagement_id
    )
    event = materialize_event(
        facts.draft, sequence, previous if previous is not None else GENESIS_PREV_HASH
    )
    record = _project_record(facts.decision)
    event_id = await invoke_record_routine(session, proposal, record, event)
    return PolicyRecordReceipt(
        decision=facts.decision,
        event_id=event_id,
        event_sequence=event.sequence,
        event_hash=event.event_hash,
        replayed=False,
    )


async def _replay(session: AsyncSession, proposal: ActionProposal) -> PolicyRecordReceipt:
    """Reconstruct the decision and fully re-verify the durable event before returning a receipt.

    Append-time triggers do not re-run on replay, so the whole durable event is re-verified
    event-locally (semantics, payload, hashes, direct predecessor) — never with the engagement-wide
    chain verifier, so unrelated later corruption cannot reject an otherwise-valid policy receipt.
    """
    completion = await load_durable_completion(
        session, proposal.tenant_id, proposal.engagement_id, proposal.proposal_id
    )
    decision = _require_reconstructed_decision(completion, proposal)
    if completion.event_count != 1 or completion.event is None:
        raise PolicyRecordingIntegrityError("durable policy event multiplicity is not exactly one")
    event = completion.event
    draft = EvaluationPersistenceFacts(proposal=proposal, decision=decision).draft
    _verify_event_semantics(event, draft, decision)
    _verify_event_integrity(event, completion.predecessor_hash)
    return PolicyRecordReceipt(
        decision=decision,
        event_id=event.id,
        event_sequence=event.sequence,
        event_hash=event.event_hash,
        replayed=True,
    )


def _require_reconstructed_decision(
    completion: DurableCompletion, proposal: ActionProposal
) -> PolicyDecisionV2:
    """Fail closed unless exactly one decision is durable and it reconstructs to the retry."""
    if completion.decision is None or completion.decision_count != 1:
        raise PolicyRecordingIntegrityError("durable decision multiplicity is not exactly one")
    decision = _reconstruct_decision(completion.decision)
    _require_decision_matches(decision, proposal)
    return decision


# Envelope fields shared by name between the durable AgentEvent and the re-projected EventDraft; a
# durable event must reproduce every one before a replay receipt is trusted.
_EVENT_ENVELOPE_FIELDS = _names(
    "tenant_id engagement_id schema_name schema_version producer "
    "correlation_id causation_id occurred_at sensitivity"
)


def _verify_event_semantics(
    event: AgentEvent, draft: EventDraft, decision: PolicyDecisionV2
) -> None:
    """Fail closed unless the durable event's envelope, payload, and lineage match the decision.

    ``draft`` is the deterministic projection of the already-validated (proposal, decision) — a pure
    re-projection, never a re-evaluation.
    """
    envelope_ok = all(getattr(event, f) == getattr(draft, f) for f in _EVENT_ENVELOPE_FIELDS)
    if not envelope_ok or tuple(event.redaction_refs) != tuple(draft.redaction_refs):
        raise PolicyRecordingIntegrityError("durable policy event envelope does not match")
    if event.payload != draft.materialize_payload():
        raise PolicyRecordingIntegrityError("durable policy event payload does not match")
    if event.policy_decision_id != decision.decision_id:
        raise PolicyRecordingIntegrityError("durable policy event lineage does not match")


def _verify_event_integrity(event: AgentEvent, predecessor_hash: str | None) -> None:
    """Fail closed unless the payload/event hashes and predecessor link recompute locally."""
    if event.hash_algorithm != HASH_ALGORITHM or event.hash_version != HASH_VERSION:
        raise PolicyRecordingIntegrityError("durable policy event uses an unsupported hash scheme")
    try:
        payload_ok = compute_payload_hash(event.payload) == event.payload_hash
        event_ok = compute_event_hash(event) == event.event_hash
    except LedgerValidationError as exc:
        raise PolicyRecordingIntegrityError("durable policy event is not canonical") from exc
    if not payload_ok:
        raise PolicyRecordingIntegrityError("durable policy event payload hash is inconsistent")
    if not event_ok:
        raise PolicyRecordingIntegrityError("durable policy event hash is inconsistent")
    _verify_predecessor(event, predecessor_hash)


def _verify_predecessor(event: AgentEvent, predecessor_hash: str | None) -> None:
    """Fail closed unless the direct predecessor link is consistent (genesis at sequence 1)."""
    if event.sequence == 1:
        if event.prev_event_hash != GENESIS_PREV_HASH or predecessor_hash is not None:
            raise PolicyRecordingIntegrityError(
                "durable genesis policy event predecessor is invalid"
            )
        return
    if predecessor_hash is None or predecessor_hash != event.prev_event_hash:
        raise PolicyRecordingIntegrityError("durable policy event predecessor link is broken")


def _require_decision_matches(decision: PolicyDecisionV2, proposal: ActionProposal) -> None:
    if (
        decision.proposal_id != proposal.proposal_id
        or decision.proposal_digest != proposal.proposal_digest
        or decision.tenant_id != proposal.tenant_id
        or decision.engagement_id != proposal.engagement_id
    ):
        raise PolicyRecordingIntegrityError("durable decision does not match the retried proposal")


# Single source for the flat decision column set shared by reconstruction and projection: the scalar
# ``PolicyDecisionV2`` fields plus the ``graph_version`` subfields the store persists as
# ``graph_<subfield>``, so the two directions can never silently disagree on the column set.
_DECISION_SCALAR_FIELDS = _names(
    "schema_name schema_version decision_id tenant_id engagement_id proposal_id proposal_digest "
    "decision_authority outcome reason_code decided_at runtime_gate_result_digest decision_digest"
)
_GRAPH_SUBFIELDS = _names(
    "state_root_version projector_version state_root ledger_event_count ledger_head_hash"
)


def _reconstruct_decision(row: Mapping[str, Any]) -> PolicyDecisionV2:
    """Rebuild ``PolicyDecisionV2`` from durable columns; the stored digest must bind the contents.

    ``model_validate`` recomputes the digest and rejects the row when the durable digest does not
    bind the reconstructed fields, so a tampered or truncated decision fails closed here.
    """
    fields: dict[str, Any] = {name: row[name] for name in _DECISION_SCALAR_FIELDS}
    fields["graph_version"] = {sub: row[f"graph_{sub}"] for sub in _GRAPH_SUBFIELDS}
    try:
        return PolicyDecisionV2.model_validate(fields)
    except ValidationError as exc:
        raise PolicyRecordingIntegrityError("durable decision failed reconstruction") from exc


def _project_record(decision: PolicyDecisionV2) -> PolicyDecisionRecord:
    """Project the domain decision into the store's flat decision-record storage specification."""
    graph = decision.graph_version
    scalars = {name: getattr(decision, name) for name in _DECISION_SCALAR_FIELDS}
    columns = {f"graph_{sub}": getattr(graph, sub) for sub in _GRAPH_SUBFIELDS}
    return PolicyDecisionRecord(**scalars, **columns)
