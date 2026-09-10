"""Durable, tenant-isolated, immutable proposal and decision record mappings (M1.4c1).

These SQLAlchemy mappings describe the normalized ``action_proposals`` and ``decision_records``
tables created by migration ``0007_m1_policy_records``. They are structural mappings only: they
contain no policy evaluation, no outcome derivation, and no execution authority. A row is a durable
record whose integrity is enforced by database constraints; it is not an authenticated producer
statement and an ``ALLOW`` decision row grants no execution permission.

This module is imported explicitly by ``migrations/env.py`` and by tests. It is intentionally not
re-exported through ``blackbread.models`` because M1.4c1 has no production writer or consumer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from blackbread.models.base import Base

HEX64 = "^[0-9a-f]{64}$"
CAPABILITY_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*\.v[1-9][0-9]*$"
SCHEMA_REF_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*\.v[1-9][0-9]*$"
MAX_COST = 1_000_000.0
MAX_BUDGET_REQUESTS = 1_000_000
MAX_DEADLINE_SECONDS = 604_800
MAX_SCHEMA_VERSION = 2_147_483_647
MAX_LEDGER_EVENT_COUNT = 9_223_372_036_854_775_807


def _sql_in(values: tuple[str, ...]) -> str:
    """Render a closed-vocabulary tuple as a SQL ``IN`` list of quoted literals."""
    return ", ".join(f"'{value}'" for value in values)


# Closed vocabularies mirrored from the released ActionProposal v1 and PolicyDecisionV2 contracts.
AGENT_ROLES = ("Scout", "Strike", "Exploit", "Post-Exploit", "Report")
TARGET_KINDS = ("root_domain", "exact_host", "exact_address", "cloud_tenant")
IDENTITY_TIERS = ("T0", "T1", "T2", "T3")
FINAL_OUTCOMES = (
    "ALLOW",
    "DENY",
    "APPROVAL_REQUIRED",
    "WAIT_FOR_RESOURCE",
    "STALE_CONTEXT",
    "ENGAGEMENT_STOPPED",
    "OPSEC_HOLD",
)

# The released FINAL_OUTCOME_BY_REASON closed mapping, grouped by outcome. Tests cross-check this
# against blackbread.policy.decision_v2.FINAL_OUTCOME_BY_REASON so it cannot silently drift.
_DENY = (
    "RUNTIME_BINDING_MISMATCH",
    "ADMISSION_DENIED",
    "BUDGET_DEADLINE_EXCEEDED",
    "BUDGET_CAPACITY_EXCEEDED",
)
_APPROVAL = (
    "APPROVAL_MISSING",
    "APPROVAL_CLASS_MISMATCH",
    "APPROVAL_TARGET_MISMATCH",
    "APPROVAL_NOT_YET_VALID",
    "APPROVAL_EXPIRED",
    "APPROVAL_REVOKED",
)
_STALE = (
    "ENGAGEMENT_STATE_MISSING",
    "RUNTIME_CONTEXT_INCOHERENT",
    "RUNTIME_SNAPSHOT_NOT_YET_VALID",
    "RUNTIME_SNAPSHOT_EXPIRED",
    "OPSEC_STATE_EXPIRED",
    "BUDGET_STATE_MISSING",
    "BUDGET_WINDOW_EXPIRED",
    "LOCK_STATE_MISSING",
)
_OPSEC = ("OPSEC_STATE_MISSING", "OPSEC_BURNED", "OPSEC_HOT")
# The IS NOT NULL guard is load-bearing: without it a non-ALLOW outcome with a NULL reason makes the
# whole predicate evaluate to SQL NULL (unknown), which a CHECK constraint accepts. ALLOW must carry
# no reason; every other outcome must carry exactly one reason from its released set.
OUTCOME_REASON_COHERENCE = (
    "(outcome = 'ALLOW' AND reason_code IS NULL) OR (reason_code IS NOT NULL AND ("
    f"(outcome = 'DENY' AND reason_code IN ({_sql_in(_DENY)}))"
    f" OR (outcome = 'APPROVAL_REQUIRED' AND reason_code IN ({_sql_in(_APPROVAL)}))"
    " OR (outcome = 'WAIT_FOR_RESOURCE' AND reason_code = 'RESOURCE_LOCK_HELD')"
    f" OR (outcome = 'STALE_CONTEXT' AND reason_code IN ({_sql_in(_STALE)}))"
    " OR (outcome = 'ENGAGEMENT_STOPPED' AND reason_code = 'ENGAGEMENT_STOPPED')"
    f" OR (outcome = 'OPSEC_HOLD' AND reason_code IN ({_sql_in(_OPSEC)}))"
    "))"
)

# Ordered columns of the action_proposals composite candidate key referenced by a decision record.
PROPOSAL_LINEAGE_COLUMNS = (
    "tenant_id",
    "engagement_id",
    "proposal_id",
    "proposal_digest",
    "graph_state_root_version",
    "graph_projector_version",
    "graph_state_root",
    "graph_ledger_event_count",
    "graph_ledger_head_hash",
)


class ActionProposalRecord(Base):
    """Normalized durable record of an immutable ActionProposal v1 and its proposal digest."""

    __tablename__ = "action_proposals"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "engagement_id", "idempotency_key", name="uq_action_proposals_idempotency"
        ),
        UniqueConstraint(
            "tenant_id", "engagement_id", "proposal_digest", name="uq_action_proposals_digest"
        ),
        UniqueConstraint(*PROPOSAL_LINEAGE_COLUMNS, name="uq_action_proposals_lineage"),
        ForeignKeyConstraint(
            ["engagement_id", "tenant_id"],
            ["engagements.id", "engagements.tenant_id"],
            name="fk_action_proposals_engagement",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "schema_name = 'conductor.action_proposal'", name="ck_action_proposals_schema_name"
        ),
        CheckConstraint("schema_version = 1", name="ck_action_proposals_schema_version"),
        CheckConstraint("char_length(btrim(tenant_id)) > 0", name="ck_action_proposals_tenant"),
        CheckConstraint(
            f"agent_role IN ({_sql_in(AGENT_ROLES)})", name="ck_action_proposals_agent_role"
        ),
        CheckConstraint(
            f"capability_id ~ '{CAPABILITY_PATTERN}'", name="ck_action_proposals_capability_id"
        ),
        CheckConstraint(
            f"target_kind IN ({_sql_in(TARGET_KINDS)})", name="ck_action_proposals_target_kind"
        ),
        CheckConstraint(
            "char_length(btrim(target_value)) > 0", name="ck_action_proposals_target_value"
        ),
        CheckConstraint(
            f"input_schema_ref ~ '{SCHEMA_REF_PATTERN}'", name="ck_action_proposals_input_schema"
        ),
        CheckConstraint("jsonb_typeof(parameters) = 'object'", name="ck_action_proposals_params"),
        CheckConstraint(
            "jsonb_typeof(precondition_refs) = 'array'", name="ck_action_proposals_precond"
        ),
        CheckConstraint(
            f"target_identity_tier IN ({_sql_in(IDENTITY_TIERS)})",
            name="ck_action_proposals_identity_tier",
        ),
        CheckConstraint("risk >= 0.0 AND risk <= 1.0", name="ck_action_proposals_risk"),
        CheckConstraint(f"cost >= 0.0 AND cost <= {MAX_COST}", name="ck_action_proposals_cost"),
        CheckConstraint(
            "information_gain >= 0.0 AND information_gain <= 1.0",
            name="ck_action_proposals_infogain",
        ),
        CheckConstraint(
            "opsec_noise >= 0.0 AND opsec_noise <= 1.0", name="ck_action_proposals_opsec_noise"
        ),
        CheckConstraint(
            f"target_requests >= 0 AND target_requests <= {MAX_BUDGET_REQUESTS}",
            name="ck_action_proposals_target_requests",
        ),
        CheckConstraint(
            f"deadline_seconds >= 1 AND deadline_seconds <= {MAX_DEADLINE_SECONDS}",
            name="ck_action_proposals_deadline",
        ),
        CheckConstraint(
            f"graph_state_root_version >= 1 AND graph_state_root_version <= {MAX_SCHEMA_VERSION}",
            name="ck_action_proposals_state_root_version",
        ),
        CheckConstraint(
            f"graph_projector_version >= 1 AND graph_projector_version <= {MAX_SCHEMA_VERSION}",
            name="ck_action_proposals_projector_version",
        ),
        CheckConstraint(f"graph_state_root ~ '{HEX64}'", name="ck_action_proposals_state_root"),
        CheckConstraint(
            "graph_ledger_event_count >= 1 "
            f"AND graph_ledger_event_count <= {MAX_LEDGER_EVENT_COUNT}",
            name="ck_action_proposals_ledger_event_count",
        ),
        CheckConstraint(
            f"graph_ledger_head_hash ~ '{HEX64}'", name="ck_action_proposals_ledger_head_hash"
        ),
        CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0", name="ck_action_proposals_idempotency_key"
        ),
        CheckConstraint(f"proposal_digest ~ '{HEX64}'", name="ck_action_proposals_proposal_digest"),
        CheckConstraint("expires_at > created_at", name="ck_action_proposals_validity_window"),
    )

    schema_name: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    engagement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_role: Mapped[str] = mapped_column(String(16), nullable=False)
    capability_id: Mapped[str] = mapped_column(String(200), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    target_value: Mapped[str] = mapped_column(String(500), nullable=False)
    input_schema_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    intended_proof: Mapped[str] = mapped_column(String(500), nullable=False)
    precondition_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    oracle_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    risk: Mapped[float] = mapped_column(Double, nullable=False)
    cost: Mapped[float] = mapped_column(Double, nullable=False)
    information_gain: Mapped[float] = mapped_column(Double, nullable=False)
    opsec_noise: Mapped[float] = mapped_column(Double, nullable=False)
    target_requests: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deadline_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    target_identity_tier: Mapped[str] = mapped_column(String(2), nullable=False)
    graph_state_root_version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_projector_version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_state_root: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_ledger_event_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    graph_ledger_head_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    proposal_digest: Mapped[str] = mapped_column(String(64), nullable=False)


class DecisionRecord(Base):
    """Normalized durable record of a PolicyDecisionV2 bound to an exact stored proposal.

    ``outcome``/``reason_code`` follow the released FINAL_OUTCOME_BY_REASON closed mapping. The row
    proves structural lineage to one proposal; it does not authenticate the producer, and an
    ``ALLOW`` outcome is not execution permission.
    """

    __tablename__ = "decision_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "engagement_id", "decision_digest", name="uq_decision_records_digest"
        ),
        UniqueConstraint(
            "tenant_id", "engagement_id", "proposal_id", name="uq_decision_records_proposal"
        ),
        UniqueConstraint(
            "tenant_id", "engagement_id", "decision_id", name="uq_decision_records_decision_identity"
        ),
        ForeignKeyConstraint(
            ["engagement_id", "tenant_id"],
            ["engagements.id", "engagements.tenant_id"],
            name="fk_decision_records_engagement",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            list(PROPOSAL_LINEAGE_COLUMNS),
            [f"action_proposals.{column}" for column in PROPOSAL_LINEAGE_COLUMNS],
            name="fk_decision_records_proposal_lineage",
            ondelete="RESTRICT",
        ),
        CheckConstraint("schema_name = 'policy.decision'", name="ck_decision_records_schema_name"),
        CheckConstraint("schema_version = 2", name="ck_decision_records_schema_version"),
        CheckConstraint("char_length(btrim(tenant_id)) > 0", name="ck_decision_records_tenant"),
        CheckConstraint(
            "decision_authority = 'policy.kernel.v2'", name="ck_decision_records_authority"
        ),
        CheckConstraint(
            f"outcome IN ({_sql_in(FINAL_OUTCOMES)})", name="ck_decision_records_outcome"
        ),
        CheckConstraint(OUTCOME_REASON_COHERENCE, name="ck_decision_records_outcome_reason"),
        CheckConstraint(f"proposal_digest ~ '{HEX64}'", name="ck_decision_records_proposal_digest"),
        CheckConstraint(
            f"graph_state_root_version >= 1 AND graph_state_root_version <= {MAX_SCHEMA_VERSION}",
            name="ck_decision_records_state_root_version",
        ),
        CheckConstraint(
            f"graph_projector_version >= 1 AND graph_projector_version <= {MAX_SCHEMA_VERSION}",
            name="ck_decision_records_projector_version",
        ),
        CheckConstraint(f"graph_state_root ~ '{HEX64}'", name="ck_decision_records_state_root"),
        CheckConstraint(
            "graph_ledger_event_count >= 1 "
            f"AND graph_ledger_event_count <= {MAX_LEDGER_EVENT_COUNT}",
            name="ck_decision_records_ledger_event_count",
        ),
        CheckConstraint(
            f"graph_ledger_head_hash ~ '{HEX64}'", name="ck_decision_records_ledger_head_hash"
        ),
        CheckConstraint(
            f"runtime_gate_result_digest ~ '{HEX64}'", name="ck_decision_records_runtime_digest"
        ),
        CheckConstraint(f"decision_digest ~ '{HEX64}'", name="ck_decision_records_decision_digest"),
    )

    schema_name: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    engagement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    proposal_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_authority: Mapped[str] = mapped_column(String(50), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    graph_state_root_version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_projector_version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_state_root: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_ledger_event_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    graph_ledger_head_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_gate_result_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
