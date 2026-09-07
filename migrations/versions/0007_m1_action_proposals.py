from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from blackbread.tenancy.roles import require_isolatable_runtime_role

revision: str = "0007_m1_action_proposals"
down_revision: str | None = "0006_m1_temporal_scope_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "tenant_id = current_setting('blackbread.tenant_id', true)"
HASH_PATTERN = "^[0-9a-f]{64}$"


def upgrade() -> None:
    require_isolatable_runtime_role(op.get_bind())

    op.create_table(
        "action_proposals",
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_digest", sa.String(length=64), nullable=False),
        sa.Column("schema_name", sa.String(length=200), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("agent_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_role", sa.String(length=50), nullable=False),
        sa.Column("capability_id", sa.String(length=200), nullable=False),
        sa.Column("target_kind", sa.String(length=50), nullable=False),
        sa.Column("target_canonical_value", sa.String(length=500), nullable=False),
        sa.Column("input_schema_ref", sa.String(length=200), nullable=False),
        sa.Column("canonical_parameters", sa.Text(), nullable=False),
        sa.Column("intended_proof", sa.String(length=500), nullable=False),
        sa.Column("precondition_refs", postgresql.ARRAY(sa.String(length=500)), nullable=False),
        sa.Column("oracle_ref", sa.String(length=500), nullable=False),
        sa.Column("estimates_risk", sa.Float(), nullable=False),
        sa.Column("estimates_cost", sa.Float(), nullable=False),
        sa.Column("estimates_information_gain", sa.Float(), nullable=False),
        sa.Column("estimates_opsec_noise", sa.Float(), nullable=False),
        sa.Column("budget_target_requests", sa.Integer(), nullable=False),
        sa.Column("budget_deadline_seconds", sa.Integer(), nullable=False),
        sa.Column("target_identity_tier", sa.String(length=10), nullable=False),
        sa.Column("graph_state_root_version", sa.Integer(), nullable=False),
        sa.Column("graph_projector_version", sa.Integer(), nullable=False),
        sa.Column("graph_state_root", sa.String(length=64), nullable=False),
        sa.Column("graph_ledger_event_count", sa.BigInteger(), nullable=False),
        sa.Column("graph_ledger_head_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "engagement_id",
            "proposal_id",
            name="pk_action_proposals",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "engagement_id",
            "proposal_digest",
            name="uq_action_proposals_digest",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "tenant_id"],
            ["engagements.id", "engagements.tenant_id"],
            name="fk_action_proposals_engagement",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "char_length(btrim(tenant_id)) > 0",
            name="ck_action_proposals_tenant_not_blank",
        ),
        sa.CheckConstraint(
            f"proposal_digest ~ '{HASH_PATTERN}'",
            name="ck_action_proposals_digest_format",
        ),
    )

    # RLS
    op.execute(sa.text("ALTER TABLE action_proposals ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE action_proposals FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            f"CREATE POLICY tenant_isolation ON action_proposals "
            f"FOR ALL USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )
    )

    # Append-only trigger
    op.execute(
        sa.text(
            """
            CREATE FUNCTION blackbread_action_proposals_append_only()
            RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = pg_catalog, public
            AS $$
            BEGIN
                RAISE EXCEPTION 'action_proposals is append-only'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_action_proposals_append_only';
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER action_proposals_append_only_trigger
            BEFORE UPDATE OR DELETE ON action_proposals
            FOR EACH ROW
            EXECUTE FUNCTION blackbread_action_proposals_append_only()
            """
        )
    )

    # Privileges
    op.execute(sa.text("REVOKE ALL ON TABLE action_proposals FROM PUBLIC"))
    op.execute(
        sa.text("REVOKE ALL ON FUNCTION blackbread_action_proposals_append_only() FROM PUBLIC")
    )
    op.execute(
        sa.text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE action_proposals TO blackbread_runtime"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DROP TRIGGER IF EXISTS action_proposals_append_only_trigger ON action_proposals")
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS blackbread_action_proposals_append_only()"))
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON action_proposals"))
    op.execute(sa.text("ALTER TABLE action_proposals NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE action_proposals DISABLE ROW LEVEL SECURITY"))
    op.drop_table("action_proposals")
