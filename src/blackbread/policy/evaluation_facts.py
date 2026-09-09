"""Internal computation/projection continuity only; no persistence or execution authority.

M1.4c2b owns positive wiring and must call evaluate_persistence_facts inside its authenticated
transaction, sourcing the stamp itself. It must not accept this binding or its stamp externally.
Constructors, digests, frozen snapshots and deserialization do not authenticate producers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import ValidationError, model_validator

from blackbread.conductor.contracts import (
    ActionProposal,
    GraphVersionReference,
    HexDigest,
    KeyText,
    UtcTimestamp,
)
from blackbread.ledger.draft import EventDraft
from blackbread.ledger.errors import LedgerValidationError
from blackbread.ledger.schema import EventEnvelope, EventPayload, EventRegistry, to_draft
from blackbread.policy.admission_contracts import (
    CapabilityAdmissionSnapshot,
    DestinationManifest,
    EngagementPolicySnapshot,
    TargetIdentitySnapshot,
)
from blackbread.policy.decision_v2 import (
    FINAL_OUTCOME_BY_REASON,
    POLICY_DECISION_V2_SCHEMA_VERSION,
    FinalDecisionOutcome,
    PolicyDecisionV2,
    SchemaVersionTwo,
)
from blackbread.policy.evaluation import evaluate_policy
from blackbread.policy.runtime_contracts import RuntimeGateSnapshot
from blackbread.policy.runtime_result import RuntimeGateReason


class EvaluationBindingError(ValueError):
    """Fail-closed mismatch between this invocation and the evaluator's returned lineage."""


class PolicyDecisionRecorded(EventPayload):
    SCHEMA_NAME: ClassVar[str] = "policy.decision.recorded"
    SCHEMA_VERSION: ClassVar[int] = 1

    decision_schema_name: Literal["policy.decision"]
    decision_schema_version: SchemaVersionTwo
    proposal_id: UUID
    proposal_digest: HexDigest
    idempotency_key: KeyText
    decision_id: UUID
    decision_authority: Literal["policy.kernel.v2"]
    outcome: FinalDecisionOutcome
    reason_code: RuntimeGateReason | None
    decided_at: UtcTimestamp
    graph_version: GraphVersionReference
    runtime_gate_result_digest: HexDigest
    decision_digest: HexDigest

    @model_validator(mode="after")
    def _check_outcome_reason(self) -> Self:
        expected = (
            "ALLOW" if self.reason_code is None else FINAL_OUTCOME_BY_REASON[self.reason_code]
        )
        if self.outcome != expected:
            raise ValueError("outcome and reason_code are incompatible")
        return self


@lru_cache(maxsize=1)
def policy_decision_registry() -> EventRegistry:
    registry = EventRegistry()
    registry.register(PolicyDecisionRecorded)
    return registry.freeze()


@dataclass(frozen=True, kw_only=True, slots=True)
class EvaluationPersistenceFacts:
    """Constructible, non-authoritative artifacts; only the composed call proves continuity."""

    proposal: ActionProposal
    decision: PolicyDecisionV2
    draft: EventDraft = field(init=False)

    def __post_init__(self) -> None:
        lineage = ("tenant_id", "engagement_id", "proposal_id", "proposal_digest", "graph_version")
        if any(getattr(self.decision, key) != getattr(self.proposal, key) for key in lineage):
            raise EvaluationBindingError("decision does not match the evaluated proposal lineage")
        if (
            self.decision.schema_name != "policy.decision"
            or self.decision.schema_version != POLICY_DECISION_V2_SCHEMA_VERSION
            or self.decision.decision_authority != "policy.kernel.v2"
        ):
            raise EvaluationBindingError(
                "decision schema or authority does not match the evaluator"
            )
        object.__setattr__(self, "draft", self._project_event())

    def _project_payload(self) -> PolicyDecisionRecorded:
        decision = self.decision
        return PolicyDecisionRecorded(
            decision_schema_name=decision.schema_name,
            decision_schema_version=decision.schema_version,
            proposal_id=self.proposal.proposal_id,
            proposal_digest=self.proposal.proposal_digest,
            idempotency_key=self.proposal.idempotency_key,
            decision_id=decision.decision_id,
            decision_authority=decision.decision_authority,
            outcome=decision.outcome,
            reason_code=decision.reason_code,
            decided_at=decision.decided_at,
            graph_version=decision.graph_version,
            runtime_gate_result_digest=decision.runtime_gate_result_digest,
            decision_digest=decision.decision_digest,
        )

    def _project_event(self) -> EventDraft:
        envelope = EventEnvelope(
            tenant_id=self.proposal.tenant_id,
            engagement_id=self.proposal.engagement_id,
            producer="policy-record-transaction.v1",
            occurred_at=self.decision.decided_at,
            sensitivity="internal",
            correlation_id=self.proposal.proposal_id,
            causation_id=self.decision.decision_id,
            redaction_refs=(),
        )
        try:
            return to_draft(self._project_payload(), envelope, registry=policy_decision_registry())
        except ValidationError as exc:
            raise LedgerValidationError(
                "policy decision event projection failed validation"
            ) from exc


def evaluate_persistence_facts(  # noqa: PLR0913
    proposal: ActionProposal,
    *,
    policy: EngagementPolicySnapshot,
    identity: TargetIdentitySnapshot,
    capability: CapabilityAdmissionSnapshot,
    manifest: DestinationManifest,
    runtime: RuntimeGateSnapshot,
    decision_id: UUID,
    decided_at: datetime,
) -> EvaluationPersistenceFacts:
    decision = evaluate_policy(
        proposal,
        policy=policy,
        identity=identity,
        capability=capability,
        manifest=manifest,
        runtime=runtime,
        decision_id=decision_id,
        decided_at=decided_at,
    )
    if not isinstance(decision, PolicyDecisionV2):
        raise EvaluationBindingError("evaluator did not return a policy decision")
    if (
        decision.decision_id != decision_id
        or decision.decided_at != decided_at
        or decision.decided_at.utcoffset() != decided_at.utcoffset()
    ):
        raise EvaluationBindingError("decision does not match this invocation's transaction stamp")
    return EvaluationPersistenceFacts(proposal=proposal, decision=decision)
