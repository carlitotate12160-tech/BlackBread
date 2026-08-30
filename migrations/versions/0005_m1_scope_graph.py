from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from blackbread.tenancy.roles import require_isolatable_runtime_role

revision: str = "0005_m1_scope_graph"
down_revision: str | None = "0004_m1_clients_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HASH_PATTERN = "^[0-9a-f]{64}$"
TENANT_PREDICATE = "tenant_id = current_setting('blackbread.tenant_id', true)"
PROJECTION_TABLES = ("graph_projection_snapshots", "graph_nodes")


def _install_tenant_policy(table: str) -> None:
    op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"FOR ALL USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )
    )


def upgrade() -> None:
    require_isolatable_runtime_role(op.get_bind())
    op.create_unique_constraint(
        "uq_agent_events_projection_source",
        "agent_events",
        [
            "tenant_id",
            "engagement_id",
            "sequence",
            "event_hash",
            "schema_name",
            "schema_version",
        ],
    )
    op.create_table(
        "graph_projection_snapshots",
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verified_event_count", sa.BigInteger(), nullable=False),
        sa.Column("verified_head_hash", sa.String(length=64), nullable=False),
        sa.Column("ledger_hash_algorithm", sa.String(length=16), nullable=False),
        sa.Column("ledger_hash_version", sa.Integer(), nullable=False),
        sa.Column("projector_version", sa.Integer(), nullable=False),
        sa.Column("state_root_version", sa.Integer(), nullable=False),
        sa.Column("state_root", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "engagement_id", name="pk_graph_projection_snapshots"),
        sa.UniqueConstraint(
            "tenant_id",
            "engagement_id",
            "verified_event_count",
            name="uq_graph_projection_snapshot_version",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "tenant_id"],
            ["engagements.id", "engagements.tenant_id"],
            name="fk_graph_projection_snapshot_engagement",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "char_length(btrim(tenant_id)) > 0",
            name="ck_graph_projection_snapshots_tenant_not_blank",
        ),
        sa.CheckConstraint(
            "verified_event_count >= 0",
            name="ck_graph_projection_snapshots_event_count",
        ),
        sa.CheckConstraint(
            f"verified_head_hash ~ '{HASH_PATTERN}'",
            name="ck_graph_projection_snapshots_head_hash",
        ),
        sa.CheckConstraint(
            "ledger_hash_algorithm = 'sha256' AND ledger_hash_version = 1",
            name="ck_graph_projection_snapshots_hash_scheme",
        ),
        sa.CheckConstraint(
            "projector_version = 1",
            name="ck_graph_projection_snapshots_projector_version",
        ),
        sa.CheckConstraint(
            "state_root_version = 1",
            name="ck_graph_projection_snapshots_state_root_version",
        ),
        sa.CheckConstraint(
            f"state_root ~ '{HASH_PATTERN}'",
            name="ck_graph_projection_snapshots_state_root",
        ),
    )
    op.create_table(
        "graph_nodes",
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_version", sa.BigInteger(), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("node_family", sa.String(length=50), nullable=False),
        sa.Column("scope_kind", sa.String(length=50), nullable=False),
        sa.Column("canonical_value", sa.String(length=500), nullable=False),
        sa.Column("authority", sa.String(length=50), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_sequence", sa.BigInteger(), nullable=False),
        sa.Column("source_event_hash", sa.String(length=64), nullable=False),
        sa.Column("source_schema_name", sa.String(length=200), nullable=False),
        sa.Column("source_schema_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "engagement_id", "node_id", name="pk_graph_nodes"),
        sa.UniqueConstraint(
            "tenant_id",
            "engagement_id",
            "node_family",
            "scope_kind",
            "canonical_value",
            name="uq_graph_nodes_scope_identity",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "engagement_id", "graph_version"],
            [
                "graph_projection_snapshots.tenant_id",
                "graph_projection_snapshots.engagement_id",
                "graph_projection_snapshots.verified_event_count",
            ],
            name="fk_graph_nodes_projection_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "engagement_id",
                "source_sequence",
                "source_event_hash",
                "source_schema_name",
                "source_schema_version",
            ],
            [
                "agent_events.tenant_id",
                "agent_events.engagement_id",
                "agent_events.sequence",
                "agent_events.event_hash",
                "agent_events.schema_name",
                "agent_events.schema_version",
            ],
            name="fk_graph_nodes_source_event",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("graph_version >= 0", name="ck_graph_nodes_graph_version"),
        sa.CheckConstraint(f"node_id ~ '{HASH_PATTERN}'", name="ck_graph_nodes_node_id"),
        sa.CheckConstraint("node_family = 'ScopeRoot'", name="ck_graph_nodes_family"),
        sa.CheckConstraint(
            "scope_kind IN ('root_domain', 'exact_host', 'exact_address', 'cloud_tenant')",
            name="ck_graph_nodes_scope_kind",
        ),
        sa.CheckConstraint(
            "canonical_value = btrim(canonical_value) AND char_length(canonical_value) > 0 "
            "AND CASE WHEN scope_kind IN ('root_domain', 'exact_host') THEN "
            "char_length(canonical_value) <= 253 AND canonical_value = lower(canonical_value) "
            "AND canonical_value ~ '^[a-z0-9.-]+$' AND canonical_value ~ '[.]' "
            "AND canonical_value !~ '[.][.]' AND canonical_value !~ '(^|[.])-' "
            "AND canonical_value !~ '-([.]|$)' AND canonical_value !~ '^[0-9.]+$' "
            "ELSE true END AND CASE WHEN scope_kind = 'exact_address' THEN "
            "host(canonical_value::inet) = canonical_value ELSE true END",
            name="ck_graph_nodes_canonical_value",
        ),
        sa.CheckConstraint("authority = 'attested_scope'", name="ck_graph_nodes_authority"),
        sa.CheckConstraint(
            f"manifest_hash ~ '{HASH_PATTERN}'", name="ck_graph_nodes_manifest_hash"
        ),
        sa.CheckConstraint("valid_until > valid_from", name="ck_graph_nodes_validity"),
        sa.CheckConstraint(
            "source_sequence >= 1 AND source_sequence <= graph_version",
            name="ck_graph_nodes_source_sequence",
        ),
        sa.CheckConstraint(
            f"source_event_hash ~ '{HASH_PATTERN}'", name="ck_graph_nodes_source_event_hash"
        ),
        sa.CheckConstraint(
            "source_schema_name = 'engagement.attested' AND source_schema_version = 1",
            name="ck_graph_nodes_source_schema",
        ),
    )
    op.create_index(
        "ix_graph_nodes_tenant_engagement_version",
        "graph_nodes",
        ["tenant_id", "engagement_id", "graph_version"],
    )
    for table in PROJECTION_TABLES:
        _install_tenant_policy(table)
    privilege_statements = (
        "REVOKE ALL ON TABLE graph_projection_snapshots, graph_nodes FROM PUBLIC",
        "GRANT SELECT, INSERT ON TABLE graph_projection_snapshots TO blackbread_runtime",
        "GRANT UPDATE (verified_event_count, verified_head_hash, ledger_hash_algorithm, "
        "ledger_hash_version, projector_version, state_root_version, state_root) "
        "ON TABLE graph_projection_snapshots TO blackbread_runtime",
        "GRANT SELECT, INSERT, DELETE ON TABLE graph_nodes TO blackbread_runtime",
    )
    for statement in privilege_statements:
        op.execute(sa.text(statement))


def downgrade() -> None:
    op.drop_table("graph_nodes")
    op.drop_table("graph_projection_snapshots")
    op.drop_constraint("uq_agent_events_projection_source", "agent_events", type_="unique")
