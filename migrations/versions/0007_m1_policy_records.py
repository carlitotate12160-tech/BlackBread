"""M1.4c1 durable, tenant-isolated, immutable policy record storage substrate.

Creates the normalized ``action_proposals`` and ``decision_records`` tables with structural
constraints, exact composite decision-to-proposal lineage, FORCE row-level security, an append-only
immutable-record trigger, and runtime SELECT-only privileges. This slice grants the ordinary runtime
role no INSERT/UPDATE/DELETE/TRUNCATE authority and introduces no production writer; the migration
administrator and tests may insert rows only to prove the substrate.

The closed outcome/reason vocabulary and composite-lineage columns are imported from the ORM mapping
module so the database CHECK is byte-identical to the mapping; tests prove that mapping equals the
live ``blackbread.policy.decision_v2.FINAL_OUTCOME_BY_REASON``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from blackbread.models.policy_records import (
    AGENT_ROLES,
    CAPABILITY_PATTERN,
    FINAL_OUTCOMES,
    HEX64,
    IDENTITY_TIERS,
    MAX_BUDGET_REQUESTS,
    MAX_COST,
    MAX_DEADLINE_SECONDS,
    MAX_LEDGER_EVENT_COUNT,
    MAX_SCHEMA_VERSION,
    OUTCOME_REASON_COHERENCE,
    PROPOSAL_LINEAGE_COLUMNS,
    SCHEMA_REF_PATTERN,
    TARGET_KINDS,
    _sql_in,
)
from blackbread.tenancy.roles import require_isolatable_runtime_role

revision: str = "0007_m1_policy_records"
down_revision: str | None = "0006_m1_temporal_scope_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = ("action_proposals", "decision_records")
TENANT_PREDICATE = "tenant_id = current_setting('blackbread.tenant_id', true)"
MUTATION_FUNCTION = "blackbread_reject_policy_record_mutation"


def _create_action_proposals() -> None:
    op.create_table(
        "action_proposals",
        sa.Column("schema_name", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_role", sa.String(length=16), nullable=False),
        sa.Column("capability_id", sa.String(length=200), nullable=False),
        sa.Column("target_kind", sa.String(length=50), nullable=False),
        sa.Column("target_value", sa.String(length=500), nullable=False),
        sa.Column("input_schema_ref", sa.String(length=200), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("intended_proof", sa.String(length=500), nullable=False),
        sa.Column("precondition_refs", postgresql.JSONB(), nullable=False),
        sa.Column("oracle_ref", sa.String(length=500), nullable=False),
        sa.Column("risk", sa.Double(), nullable=False),
        sa.Column("cost", sa.Double(), nullable=False),
        sa.Column("information_gain", sa.Double(), nullable=False),
        sa.Column("opsec_noise", sa.Double(), nullable=False),
        sa.Column("target_requests", sa.BigInteger(), nullable=False),
        sa.Column("deadline_seconds", sa.Integer(), nullable=False),
        sa.Column("target_identity_tier", sa.String(length=2), nullable=False),
        sa.Column("graph_state_root_version", sa.Integer(), nullable=False),
        sa.Column("graph_projector_version", sa.Integer(), nullable=False),
        sa.Column("graph_state_root", sa.String(length=64), nullable=False),
        sa.Column("graph_ledger_event_count", sa.BigInteger(), nullable=False),
        sa.Column("graph_ledger_head_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposal_digest", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "engagement_id", "idempotency_key", name="uq_action_proposals_idempotency"
        ),
        sa.UniqueConstraint(
            "tenant_id", "engagement_id", "proposal_digest", name="uq_action_proposals_digest"
        ),
        sa.UniqueConstraint(*PROPOSAL_LINEAGE_COLUMNS, name="uq_action_proposals_lineage"),
        sa.ForeignKeyConstraint(
            ["engagement_id", "tenant_id"],
            ["engagements.id", "engagements.tenant_id"],
            name="fk_action_proposals_engagement",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "schema_name = 'conductor.action_proposal'", name="ck_action_proposals_schema_name"
        ),
        sa.CheckConstraint("schema_version = 1", name="ck_action_proposals_schema_version"),
        sa.CheckConstraint("char_length(btrim(tenant_id)) > 0", name="ck_action_proposals_tenant"),
        sa.CheckConstraint(
            f"agent_role IN ({_sql_in(AGENT_ROLES)})", name="ck_action_proposals_agent_role"
        ),
        sa.CheckConstraint(
            f"capability_id ~ '{CAPABILITY_PATTERN}'", name="ck_action_proposals_capability_id"
        ),
        sa.CheckConstraint(
            f"target_kind IN ({_sql_in(TARGET_KINDS)})", name="ck_action_proposals_target_kind"
        ),
        sa.CheckConstraint(
            "char_length(btrim(target_value)) > 0", name="ck_action_proposals_target_value"
        ),
        sa.CheckConstraint(
            f"input_schema_ref ~ '{SCHEMA_REF_PATTERN}'", name="ck_action_proposals_input_schema"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(parameters) = 'object'", name="ck_action_proposals_params"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(precondition_refs) = 'array'", name="ck_action_proposals_precond"
        ),
        sa.CheckConstraint(
            f"target_identity_tier IN ({_sql_in(IDENTITY_TIERS)})",
            name="ck_action_proposals_identity_tier",
        ),
        sa.CheckConstraint("risk >= 0.0 AND risk <= 1.0", name="ck_action_proposals_risk"),
        sa.CheckConstraint(f"cost >= 0.0 AND cost <= {MAX_COST}", name="ck_action_proposals_cost"),
        sa.CheckConstraint(
            "information_gain >= 0.0 AND information_gain <= 1.0",
            name="ck_action_proposals_infogain",
        ),
        sa.CheckConstraint(
            "opsec_noise >= 0.0 AND opsec_noise <= 1.0", name="ck_action_proposals_opsec_noise"
        ),
        sa.CheckConstraint(
            f"target_requests >= 0 AND target_requests <= {MAX_BUDGET_REQUESTS}",
            name="ck_action_proposals_target_requests",
        ),
        sa.CheckConstraint(
            f"deadline_seconds >= 1 AND deadline_seconds <= {MAX_DEADLINE_SECONDS}",
            name="ck_action_proposals_deadline",
        ),
        sa.CheckConstraint(
            f"graph_state_root_version >= 1 AND graph_state_root_version <= {MAX_SCHEMA_VERSION}",
            name="ck_action_proposals_state_root_version",
        ),
        sa.CheckConstraint(
            f"graph_projector_version >= 1 AND graph_projector_version <= {MAX_SCHEMA_VERSION}",
            name="ck_action_proposals_projector_version",
        ),
        sa.CheckConstraint(f"graph_state_root ~ '{HEX64}'", name="ck_action_proposals_state_root"),
        sa.CheckConstraint(
            f"graph_ledger_event_count >= 1 AND graph_ledger_event_count <= {MAX_LEDGER_EVENT_COUNT}",
            name="ck_action_proposals_ledger_event_count",
        ),
        sa.CheckConstraint(
            f"graph_ledger_head_hash ~ '{HEX64}'", name="ck_action_proposals_ledger_head_hash"
        ),
        sa.CheckConstraint(
            "char_length(btrim(idempotency_key)) > 0", name="ck_action_proposals_idempotency_key"
        ),
        sa.CheckConstraint(
            f"proposal_digest ~ '{HEX64}'", name="ck_action_proposals_proposal_digest"
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_action_proposals_validity_window"),
    )
    op.create_index(
        "ix_action_proposals_engagement", "action_proposals", ["engagement_id", "tenant_id"]
    )


def _create_decision_records() -> None:
    op.create_table(
        "decision_records",
        sa.Column("schema_name", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_digest", sa.String(length=64), nullable=False),
        sa.Column("decision_authority", sa.String(length=50), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("graph_state_root_version", sa.Integer(), nullable=False),
        sa.Column("graph_projector_version", sa.Integer(), nullable=False),
        sa.Column("graph_state_root", sa.String(length=64), nullable=False),
        sa.Column("graph_ledger_event_count", sa.BigInteger(), nullable=False),
        sa.Column("graph_ledger_head_hash", sa.String(length=64), nullable=False),
        sa.Column("runtime_gate_result_digest", sa.String(length=64), nullable=False),
        sa.Column("decision_digest", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "engagement_id", "decision_digest", name="uq_decision_records_digest"
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "tenant_id"],
            ["engagements.id", "engagements.tenant_id"],
            name="fk_decision_records_engagement",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            list(PROPOSAL_LINEAGE_COLUMNS),
            [f"action_proposals.{column}" for column in PROPOSAL_LINEAGE_COLUMNS],
            name="fk_decision_records_proposal_lineage",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "schema_name = 'policy.decision'", name="ck_decision_records_schema_name"
        ),
        sa.CheckConstraint("schema_version = 2", name="ck_decision_records_schema_version"),
        sa.CheckConstraint("char_length(btrim(tenant_id)) > 0", name="ck_decision_records_tenant"),
        sa.CheckConstraint(
            "decision_authority = 'policy.kernel.v2'", name="ck_decision_records_authority"
        ),
        sa.CheckConstraint(
            f"outcome IN ({_sql_in(FINAL_OUTCOMES)})", name="ck_decision_records_outcome"
        ),
        sa.CheckConstraint(OUTCOME_REASON_COHERENCE, name="ck_decision_records_outcome_reason"),
        sa.CheckConstraint(
            f"proposal_digest ~ '{HEX64}'", name="ck_decision_records_proposal_digest"
        ),
        sa.CheckConstraint(
            f"graph_state_root_version >= 1 AND graph_state_root_version <= {MAX_SCHEMA_VERSION}",
            name="ck_decision_records_state_root_version",
        ),
        sa.CheckConstraint(
            f"graph_projector_version >= 1 AND graph_projector_version <= {MAX_SCHEMA_VERSION}",
            name="ck_decision_records_projector_version",
        ),
        sa.CheckConstraint(f"graph_state_root ~ '{HEX64}'", name="ck_decision_records_state_root"),
        sa.CheckConstraint(
            f"graph_ledger_event_count >= 1 AND graph_ledger_event_count <= {MAX_LEDGER_EVENT_COUNT}",
            name="ck_decision_records_ledger_event_count",
        ),
        sa.CheckConstraint(
            f"graph_ledger_head_hash ~ '{HEX64}'", name="ck_decision_records_ledger_head_hash"
        ),
        sa.CheckConstraint(
            f"runtime_gate_result_digest ~ '{HEX64}'", name="ck_decision_records_runtime_digest"
        ),
        sa.CheckConstraint(
            f"decision_digest ~ '{HEX64}'", name="ck_decision_records_decision_digest"
        ),
    )
    op.create_index(
        "ix_decision_records_engagement", "decision_records", ["engagement_id", "tenant_id"]
    )
    op.create_index(
        "ix_decision_records_proposal",
        "decision_records",
        ["tenant_id", "engagement_id", "proposal_id"],
    )


def _install_tenant_rls() -> None:
    for table in NEW_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                f"CREATE POLICY tenant_isolation ON {table} "
                f"FOR ALL USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
            )
        )


def _install_immutable_trigger() -> None:
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {MUTATION_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'policy record tables are append-only'
                    USING ERRCODE = '55000';
                RETURN NULL;
            END;
            $$
            """
        )
    )
    for table in NEW_TABLES:
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_reject_mutation "
                f"BEFORE UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION {MUTATION_FUNCTION}()"
            )
        )
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_reject_truncate "
                f"BEFORE TRUNCATE ON {table} "
                f"FOR EACH STATEMENT EXECUTE FUNCTION {MUTATION_FUNCTION}()"
            )
        )


def _grant_runtime_privileges() -> None:
    require_isolatable_runtime_role(op.get_bind())
    statements = (
        "REVOKE ALL ON TABLE action_proposals, decision_records FROM PUBLIC",
        # Defence in depth: strip any direct/default-privilege grants to the runtime role before
        # granting SELECT, so the SELECT-only guarantee holds even if a future ALTER DEFAULT
        # PRIVILEGES grants DML to blackbread_runtime. Revoking from PUBLIC does not remove
        # role-direct grants, and require_isolatable_runtime_role checks role attributes, not ACLs.
        "REVOKE ALL ON TABLE action_proposals, decision_records FROM blackbread_runtime",
        f"REVOKE ALL ON FUNCTION {MUTATION_FUNCTION}() FROM PUBLIC",
        "GRANT SELECT ON TABLE action_proposals, decision_records TO blackbread_runtime",
    )
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade() -> None:
    _create_action_proposals()
    _create_decision_records()
    _install_tenant_rls()
    _install_immutable_trigger()
    _grant_runtime_privileges()


def downgrade() -> None:
    for table in NEW_TABLES:
        op.execute(sa.text(f"DROP TRIGGER {table}_reject_truncate ON {table}"))
        op.execute(sa.text(f"DROP TRIGGER {table}_reject_mutation ON {table}"))
    op.drop_table("decision_records")
    op.drop_table("action_proposals")
    op.execute(sa.text(f"DROP FUNCTION {MUTATION_FUNCTION}()"))
