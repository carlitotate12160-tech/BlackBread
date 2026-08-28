from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_m1_ledger"
down_revision: str | None = "0001_m0_bootstrap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HASH_PATTERN = "^[0-9a-f]{64}$"
GENESIS_HASH = "0" * 64
SENSITIVITY_VALUES = "'public', 'internal', 'confidential', 'restricted'"


def _require_runtime_role() -> None:
    connection = op.get_bind()
    role = (
        connection.execute(
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

    parent_role = connection.scalar(
        sa.text(
            """
            SELECT parent.rolname
            FROM pg_auth_members AS membership
            JOIN pg_roles AS runtime ON runtime.oid = membership.member
            JOIN pg_roles AS parent ON parent.oid = membership.roleid
            WHERE runtime.rolname = 'blackbread_runtime'
            LIMIT 1
            """
        )
    )
    if parent_role is not None:
        raise RuntimeError("blackbread_runtime must not inherit or assume another role")


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
            "ledger_lock_token",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Immutable sentinel used only to authorize engagement row locks.",
        ),
        sa.Column(
            "ledger_event_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "ledger_head_hash",
            sa.String(length=64),
            server_default=sa.text(f"'{GENESIS_HASH}'"),
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
        sa.CheckConstraint(
            "ledger_lock_token = 0",
            name="ck_engagements_ledger_lock_token",
        ),
        sa.CheckConstraint(
            "ledger_event_count >= 0",
            name="ck_engagements_ledger_event_count",
        ),
        sa.CheckConstraint(
            f"ledger_head_hash ~ '{HASH_PATTERN}'",
            name="ck_engagements_ledger_head_hash",
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
            CREATE FUNCTION blackbread_advance_ledger_head()
            RETURNS trigger
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
            DECLARE
                current_count bigint;
                current_hash text;
            BEGIN
                SELECT ledger_event_count, ledger_head_hash
                INTO current_count, current_hash
                FROM public.engagements
                WHERE id = NEW.engagement_id
                  AND tenant_id = NEW.tenant_id
                FOR UPDATE;

                IF NOT FOUND THEN
                    RAISE EXCEPTION 'ledger engagement anchor is missing'
                        USING ERRCODE = '23503';
                END IF;
                IF NEW.sequence <> current_count + 1
                   OR NEW.prev_event_hash <> current_hash THEN
                    RAISE EXCEPTION 'event does not advance the anchored ledger head'
                        USING ERRCODE = '23514';
                END IF;

                UPDATE public.engagements
                SET ledger_event_count = NEW.sequence,
                    ledger_head_hash = NEW.event_hash
                WHERE id = NEW.engagement_id
                  AND tenant_id = NEW.tenant_id;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER agent_events_advance_head
            AFTER INSERT ON agent_events
            FOR EACH ROW
            EXECUTE FUNCTION blackbread_advance_ledger_head()
            """
        )
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
    privilege_statements = (
        "REVOKE ALL ON TABLE clients, engagements, agent_events FROM PUBLIC",
        "REVOKE ALL ON TABLE alembic_version FROM PUBLIC",
        "REVOKE ALL ON FUNCTION blackbread_advance_ledger_head() FROM PUBLIC",
        "GRANT USAGE ON SCHEMA public TO blackbread_runtime",
        "GRANT SELECT ON TABLE alembic_version TO blackbread_runtime",
        "GRANT SELECT, INSERT ON TABLE clients, engagements TO blackbread_runtime",
        "GRANT UPDATE (ledger_lock_token, ledger_event_count, ledger_head_hash) ON TABLE engagements TO blackbread_runtime",
        "GRANT SELECT, INSERT ON TABLE agent_events TO blackbread_runtime",
    )
    for statement in privilege_statements:
        op.execute(sa.text(statement))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER agent_events_advance_head ON agent_events"))
    op.execute(sa.text("DROP TRIGGER agent_events_reject_truncate ON agent_events"))
    op.execute(sa.text("DROP TRIGGER agent_events_reject_mutation ON agent_events"))
    op.drop_table("agent_events")
    op.execute(sa.text("DROP FUNCTION blackbread_advance_ledger_head()"))
    op.execute(sa.text("DROP FUNCTION blackbread_reject_agent_event_mutation()"))
    op.drop_table("engagements")
    op.drop_table("clients")
