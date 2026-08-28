from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_m1_ledger"
down_revision: str | None = "0001_m0_bootstrap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HASH_PATTERN = "^[0-9a-f]{64}$"
SENSITIVITY_VALUES = "'public', 'internal', 'confidential', 'restricted'"


def _require_runtime_role() -> None:
    role = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT rolcanlogin, rolsuper, rolcreaterole, rolcreatedb
                FROM pg_roles
                WHERE rolname = 'blackbread_runtime'
                """
            )
        )
        .mappings()
        .one_or_none()
    )
    if role is None:
        raise RuntimeError("required NOLOGIN role blackbread_runtime does not exist")
    if role["rolcanlogin"] or role["rolsuper"] or role["rolcreaterole"] or role["rolcreatedb"]:
        raise RuntimeError("blackbread_runtime must be an unprivileged NOLOGIN role")


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name="ck_clients_name_not_blank"),
    )
    op.create_table(
        "engagements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default=sa.text("'created'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_engagements_id_tenant_id"),
        sa.CheckConstraint(
            "char_length(btrim(tenant_id)) > 0",
            name="ck_engagements_tenant_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(btrim(status)) > 0",
            name="ck_engagements_status_not_blank",
        ),
    )
    op.create_index("ix_engagements_client_id", "engagements", ["client_id"])
    op.create_index("ix_engagements_tenant_id", "engagements", ["tenant_id"])

    op.create_table(
        "agent_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("schema_name", sa.String(length=200), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("producer", sa.String(length=200), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("causation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("prev_event_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "hash_algorithm",
            sa.String(length=16),
            server_default=sa.text("'sha256'"),
            nullable=False,
        ),
        sa.Column(
            "hash_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "sensitivity",
            sa.String(length=50),
            server_default=sa.text("'internal'"),
            nullable=False,
        ),
        sa.Column(
            "redaction_refs",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "tenant_id"],
            ["engagements.id", "engagements.tenant_id"],
            name="fk_agent_events_engagement_tenant",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "engagement_id",
            "sequence",
            name="uq_agent_events_engagement_sequence",
        ),
        sa.UniqueConstraint("event_hash", name="uq_agent_events_event_hash"),
        sa.CheckConstraint("sequence >= 1", name="ck_agent_events_sequence_positive"),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_agent_events_schema_version_positive",
        ),
        sa.CheckConstraint(
            "char_length(btrim(schema_name)) > 0",
            name="ck_agent_events_schema_name_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(btrim(producer)) > 0",
            name="ck_agent_events_producer_not_blank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_agent_events_payload_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(redaction_refs) = 'array'",
            name="ck_agent_events_redaction_refs_array",
        ),
        sa.CheckConstraint(
            f"payload_hash ~ '{HASH_PATTERN}'",
            name="ck_agent_events_payload_hash_hex",
        ),
        sa.CheckConstraint(
            f"prev_event_hash ~ '{HASH_PATTERN}'",
            name="ck_agent_events_prev_hash_hex",
        ),
        sa.CheckConstraint(
            f"event_hash ~ '{HASH_PATTERN}'",
            name="ck_agent_events_event_hash_hex",
        ),
        sa.CheckConstraint(
            "hash_algorithm = 'sha256'",
            name="ck_agent_events_hash_algorithm",
        ),
        sa.CheckConstraint(
            "hash_version = 1",
            name="ck_agent_events_hash_version",
        ),
        sa.CheckConstraint(
            f"sensitivity IN ({SENSITIVITY_VALUES})",
            name="ck_agent_events_sensitivity",
        ),
    )
    op.create_index(
        "ix_agent_events_tenant_engagement_sequence",
        "agent_events",
        ["tenant_id", "engagement_id", "sequence"],
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION blackbread_reject_agent_event_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'agent_events is append-only'
                    USING ERRCODE = '55000';
                RETURN NULL;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER agent_events_reject_mutation
            BEFORE UPDATE OR DELETE ON agent_events
            FOR EACH ROW
            EXECUTE FUNCTION blackbread_reject_agent_event_mutation()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER agent_events_reject_truncate
            BEFORE TRUNCATE ON agent_events
            FOR EACH STATEMENT
            EXECUTE FUNCTION blackbread_reject_agent_event_mutation()
            """
        )
    )
    _require_runtime_role()
    op.execute(
        sa.text(
            """
            REVOKE ALL ON TABLE clients, engagements, agent_events FROM PUBLIC;
            REVOKE ALL ON TABLE alembic_version FROM PUBLIC;
            GRANT USAGE ON SCHEMA public TO blackbread_runtime;
            GRANT SELECT ON TABLE alembic_version TO blackbread_runtime;
            GRANT SELECT, INSERT ON TABLE clients, engagements TO blackbread_runtime;
            GRANT SELECT, INSERT ON TABLE agent_events TO blackbread_runtime;
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER agent_events_reject_truncate ON agent_events"))
    op.execute(sa.text("DROP TRIGGER agent_events_reject_mutation ON agent_events"))
    op.drop_table("agent_events")
    op.execute(sa.text("DROP FUNCTION blackbread_reject_agent_event_mutation()"))
    op.drop_table("engagements")
    op.drop_table("clients")
