from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from blackbread.tenancy.roles import require_isolatable_runtime_role

revision: str = "0006_m1_temporal_scope_graph"
down_revision: str | None = "0005_m1_scope_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HASH_PATTERN = "^[0-9a-f]{64}$"
TENANT_PREDICATE = "tenant_id = current_setting('blackbread.tenant_id', true)"
TEMPORAL_TABLES = (
    "graph_temporal_head_nodes",
    "graph_temporal_scope_revisions",
    "graph_temporal_scope_roots",
    "graph_temporal_projection_snapshots",
)


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

    # -- 1. graph_temporal_projection_snapshots --
    op.create_table(
        "graph_temporal_projection_snapshots",
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verified_event_count", sa.BigInteger(), nullable=False),
        sa.Column("verified_head_hash", sa.String(length=64), nullable=False),
        sa.Column("ledger_hash_algorithm", sa.String(length=16), nullable=False),
        sa.Column("ledger_hash_version", sa.Integer(), nullable=False),
        sa.Column("temporal_projector_version", sa.Integer(), nullable=False),
        sa.Column("state_root_version", sa.Integer(), nullable=False),
        sa.Column("scope_canonicalization_version", sa.Integer(), nullable=False),
        sa.Column("state_root", sa.String(length=64), nullable=False),
        sa.Column("lineage_head_hash", sa.String(length=64), nullable=False),
        sa.Column("lineage_head_sequence", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "engagement_id",
            name="pk_graph_temporal_projection_snapshots",
        ),
        sa.UniqueConstraint(
            "tenant_id", "engagement_id", "verified_event_count",
            name="uq_graph_temporal_snapshot_version",
        ),
        sa.UniqueConstraint(
            "tenant_id", "engagement_id", "lineage_head_hash",
            name="uq_graph_temporal_snapshot_lineage_head",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "tenant_id"],
            ["engagements.id", "engagements.tenant_id"],
            name="fk_graph_temporal_snapshot_engagement",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "engagement_id", "verified_event_count", "verified_head_hash"],
            [
                "agent_events.tenant_id",
                "agent_events.engagement_id",
                "agent_events.sequence",
                "agent_events.event_hash",
            ],
            name="fk_graph_temporal_snapshot_anchor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "engagement_id", "lineage_head_sequence", "lineage_head_hash"],
            [
                "agent_events.tenant_id",
                "agent_events.engagement_id",
                "agent_events.sequence",
                "agent_events.event_hash",
            ],
            name="fk_graph_temporal_snapshot_lineage_head",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "char_length(btrim(tenant_id)) > 0",
            name="ck_graph_temporal_snapshots_tenant_not_blank",
        ),
        sa.CheckConstraint(
            "verified_event_count >= 1",
            name="ck_graph_temporal_snapshots_event_count",
        ),
        sa.CheckConstraint(
            f"verified_head_hash ~ '{HASH_PATTERN}'",
            name="ck_graph_temporal_snapshots_head_hash",
        ),
        sa.CheckConstraint(
            "ledger_hash_algorithm = 'sha256' AND ledger_hash_version = 1",
            name="ck_graph_temporal_snapshots_hash_scheme",
        ),
        sa.CheckConstraint(
            "temporal_projector_version = 2",
            name="ck_graph_temporal_snapshots_projector_version",
        ),
        sa.CheckConstraint(
            "state_root_version = 2",
            name="ck_graph_temporal_snapshots_state_root_version",
        ),
        sa.CheckConstraint(
            "scope_canonicalization_version = 1",
            name="ck_graph_temporal_snapshots_scope_version",
        ),
        sa.CheckConstraint(
            f"state_root ~ '{HASH_PATTERN}'",
            name="ck_graph_temporal_snapshots_state_root",
        ),
        sa.CheckConstraint(
            f"lineage_head_hash ~ '{HASH_PATTERN}'",
            name="ck_graph_temporal_snapshots_lineage_head_hash",
        ),
        sa.CheckConstraint(
            "lineage_head_sequence >= 1",
            name="ck_graph_temporal_snapshots_lineage_head_seq_min",
        ),
        sa.CheckConstraint(
            "lineage_head_sequence <= verified_event_count",
            name="ck_graph_temporal_snapshots_lineage_head_seq_max",
        ),
    )

    # -- 2. graph_temporal_scope_roots --
    op.create_table(
        "graph_temporal_scope_roots",
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("node_family", sa.String(length=50), nullable=False),
        sa.Column("scope_kind", sa.String(length=50), nullable=False),
        sa.Column("canonical_value", sa.String(length=500), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "engagement_id", "node_id",
            name="pk_graph_temporal_scope_roots",
        ),
        sa.UniqueConstraint(
            "tenant_id", "engagement_id", "scope_kind", "canonical_value",
            name="uq_graph_temporal_scope_roots_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id", "engagement_id", "node_id", "scope_kind", "canonical_value",
            name="uq_graph_temporal_scope_roots_composite",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "tenant_id"],
            ["engagements.id", "engagements.tenant_id"],
            name="fk_graph_temporal_scope_roots_engagement",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "char_length(btrim(tenant_id)) > 0",
            name="ck_graph_temporal_scope_roots_tenant_not_blank",
        ),
        sa.CheckConstraint(
            f"node_id ~ '{HASH_PATTERN}'",
            name="ck_graph_temporal_scope_roots_node_id",
        ),
        sa.CheckConstraint(
            "node_family = 'ScopeRoot'",
            name="ck_graph_temporal_scope_roots_family",
        ),
        sa.CheckConstraint(
            "scope_kind IN ('root_domain', 'exact_host', 'exact_address', 'cloud_tenant')",
            name="ck_graph_temporal_scope_roots_scope_kind",
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
            name="ck_graph_temporal_scope_roots_canonical_value",
        ),
    )

    # -- 3. graph_temporal_scope_revisions --
    op.create_table(
        "graph_temporal_scope_revisions",
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("scope_kind", sa.String(length=50), nullable=False),
        sa.Column("canonical_value", sa.String(length=500), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_sequence", sa.BigInteger(), nullable=False),
        sa.Column("source_event_hash", sa.String(length=64), nullable=False),
        sa.Column("source_schema_name", sa.String(length=200), nullable=False),
        sa.Column("source_schema_version", sa.Integer(), nullable=False),
        sa.Column("predecessor_attestation_event_hash", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint(
            "tenant_id", "engagement_id", "revision_id",
            name="pk_graph_temporal_scope_revisions",
        ),
        sa.UniqueConstraint(
            "tenant_id", "engagement_id", "revision_id", "node_id", "source_event_hash",
            name="uq_graph_temporal_revision_node_key",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "engagement_id", "node_id", "scope_kind", "canonical_value"],
            [
                "graph_temporal_scope_roots.tenant_id",
                "graph_temporal_scope_roots.engagement_id",
                "graph_temporal_scope_roots.node_id",
                "graph_temporal_scope_roots.scope_kind",
                "graph_temporal_scope_roots.canonical_value",
            ],
            name="fk_graph_temporal_revisions_stable_root",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "tenant_id", "engagement_id", "source_sequence",
                "source_event_hash", "source_schema_name", "source_schema_version",
            ],
            [
                "agent_events.tenant_id",
                "agent_events.engagement_id",
                "agent_events.sequence",
                "agent_events.event_hash",
                "agent_events.schema_name",
                "agent_events.schema_version",
            ],
            name="fk_graph_temporal_revisions_source_event",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "char_length(btrim(tenant_id)) > 0",
            name="ck_graph_temporal_revisions_tenant_not_blank",
        ),
        sa.CheckConstraint(
            f"revision_id ~ '{HASH_PATTERN}'",
            name="ck_graph_temporal_revisions_revision_id",
        ),
        sa.CheckConstraint(
            f"node_id ~ '{HASH_PATTERN}'",
            name="ck_graph_temporal_revisions_node_id",
        ),
        sa.CheckConstraint(
            f"manifest_hash ~ '{HASH_PATTERN}'",
            name="ck_graph_temporal_revisions_manifest_hash",
        ),
        sa.CheckConstraint(
            f"source_event_hash ~ '{HASH_PATTERN}'",
            name="ck_graph_temporal_revisions_source_event_hash",
        ),
        sa.CheckConstraint(
            "valid_until > valid_from",
            name="ck_graph_temporal_revisions_validity",
        ),
        sa.CheckConstraint(
            "source_sequence >= 1",
            name="ck_graph_temporal_revisions_source_sequence",
        ),
        sa.CheckConstraint(
            "source_schema_name = 'engagement.attested'",
            name="ck_graph_temporal_revisions_schema_name",
        ),
        sa.CheckConstraint(
            "source_schema_version IN (1, 2)",
            name="ck_graph_temporal_revisions_schema_version",
        ),
        sa.CheckConstraint(
            "(source_schema_version = 1 AND predecessor_attestation_event_hash IS NULL) "
            "OR (source_schema_version = 2 AND predecessor_attestation_event_hash IS NOT NULL)",
            name="ck_graph_temporal_revisions_predecessor",
        ),
        sa.CheckConstraint(
            "predecessor_attestation_event_hash IS NULL "
            f"OR predecessor_attestation_event_hash ~ '{HASH_PATTERN}'",
            name="ck_graph_temporal_revisions_predecessor_hash",
        ),
    )

    # -- provenance enforcement trigger --
    op.execute(
        sa.text(
            """
            CREATE FUNCTION blackbread_require_attested_temporal_revision()
            RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = pg_catalog, public
            AS $$
            DECLARE
                attestation jsonb;
                scope_field text;
                attested_values jsonb;
                expected_predecessor text;
            BEGIN
                SELECT payload INTO attestation
                FROM public.agent_events
                WHERE tenant_id = NEW.tenant_id
                  AND engagement_id = NEW.engagement_id
                  AND sequence = NEW.source_sequence
                  AND event_hash = NEW.source_event_hash
                  AND schema_name = NEW.source_schema_name
                  AND schema_version = NEW.source_schema_version;

                IF attestation IS NULL THEN
                    RAISE EXCEPTION 'temporal revision source event not found'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_graph_temporal_revisions_provenance';
                END IF;

                scope_field := CASE NEW.scope_kind
                    WHEN 'root_domain' THEN 'root_domains'
                    WHEN 'exact_host' THEN 'exact_hosts'
                    WHEN 'exact_address' THEN 'exact_addresses'
                    WHEN 'cloud_tenant' THEN 'cloud_tenants'
                END;
                attested_values := attestation -> 'scope' -> scope_field;

                IF attestation ->>'manifest_hash' IS DISTINCT FROM NEW.manifest_hash
                   OR (attestation ->>'valid_from')::timestamptz
                      IS DISTINCT FROM NEW.valid_from
                   OR (attestation ->>'expires_at')::timestamptz
                      IS DISTINCT FROM NEW.valid_until
                   OR jsonb_typeof(attested_values) IS DISTINCT FROM 'array'
                   OR NOT COALESCE(attested_values ? NEW.canonical_value, false) THEN
                    RAISE EXCEPTION 'temporal revision does not match attestation payload'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_graph_temporal_revisions_provenance';
                END IF;

                IF NEW.source_schema_version = 1 THEN
                    IF NEW.predecessor_attestation_event_hash IS NOT NULL THEN
                        RAISE EXCEPTION 'v1 revision must have null predecessor'
                            USING ERRCODE = '23514',
                                  CONSTRAINT = 'ck_graph_temporal_revisions_provenance';
                    END IF;
                ELSIF NEW.source_schema_version = 2 THEN
                    expected_predecessor := attestation ->>'supersedes_event_hash';
                    IF NEW.predecessor_attestation_event_hash IS DISTINCT FROM
                       expected_predecessor THEN
                        RAISE EXCEPTION 'v2 revision predecessor mismatch'
                            USING ERRCODE = '23514',
                                  CONSTRAINT = 'ck_graph_temporal_revisions_provenance';
                    END IF;
                END IF;

                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER graph_temporal_revisions_attested_provenance
            AFTER INSERT ON graph_temporal_scope_revisions
            DEFERRABLE INITIALLY IMMEDIATE
            FOR EACH ROW
            EXECUTE FUNCTION blackbread_require_attested_temporal_revision()
            """
        )
    )

    # -- 4. graph_temporal_head_nodes --
    op.create_table(
        "graph_temporal_head_nodes",
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("revision_id", sa.String(length=64), nullable=False),
        sa.Column("source_event_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "engagement_id", "node_id",
            name="pk_graph_temporal_head_nodes",
        ),
        sa.ForeignKeyConstraint(
            [
                "tenant_id", "engagement_id", "revision_id",
                "node_id", "source_event_hash",
            ],
            [
                "graph_temporal_scope_revisions.tenant_id",
                "graph_temporal_scope_revisions.engagement_id",
                "graph_temporal_scope_revisions.revision_id",
                "graph_temporal_scope_revisions.node_id",
                "graph_temporal_scope_revisions.source_event_hash",
            ],
            name="fk_graph_temporal_head_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "engagement_id", "source_event_hash"],
            [
                "graph_temporal_projection_snapshots.tenant_id",
                "graph_temporal_projection_snapshots.engagement_id",
                "graph_temporal_projection_snapshots.lineage_head_hash",
            ],
            name="fk_graph_temporal_head_lineage",
            ondelete="RESTRICT",
            initially="deferred",
            deferrable=True,
        ),
        sa.CheckConstraint(
            "char_length(btrim(tenant_id)) > 0",
            name="ck_graph_temporal_head_nodes_tenant_not_blank",
        ),
        sa.CheckConstraint(
            f"node_id ~ '{HASH_PATTERN}'",
            name="ck_graph_temporal_head_nodes_node_id",
        ),
        sa.CheckConstraint(
            f"revision_id ~ '{HASH_PATTERN}'",
            name="ck_graph_temporal_head_nodes_revision_id",
        ),
        sa.CheckConstraint(
            f"source_event_hash ~ '{HASH_PATTERN}'",
            name="ck_graph_temporal_head_nodes_source_event_hash",
        ),
    )

    # -- indexes --
    op.create_index(
        "ix_graph_temporal_revisions_engagement_sequence",
        "graph_temporal_scope_revisions",
        ["tenant_id", "engagement_id", "source_sequence"],
    )

    # -- RLS --
    for table in TEMPORAL_TABLES:
        _install_tenant_policy(table)

    # -- privileges --
    privilege_statements = (
        "REVOKE ALL ON TABLE graph_temporal_projection_snapshots, "
        "graph_temporal_scope_roots, graph_temporal_scope_revisions, "
        "graph_temporal_head_nodes FROM PUBLIC",
        "REVOKE ALL ON FUNCTION blackbread_require_attested_temporal_revision() FROM PUBLIC",
        "GRANT SELECT, INSERT ON TABLE graph_temporal_projection_snapshots "
        "TO blackbread_runtime",
        "GRANT UPDATE (verified_event_count, verified_head_hash, "
        "ledger_hash_algorithm, ledger_hash_version, temporal_projector_version, "
        "state_root_version, scope_canonicalization_version, state_root, "
        "lineage_head_hash, lineage_head_sequence) "
        "ON TABLE graph_temporal_projection_snapshots TO blackbread_runtime",
        "GRANT SELECT, INSERT ON TABLE graph_temporal_scope_roots TO blackbread_runtime",
        "GRANT SELECT, INSERT ON TABLE graph_temporal_scope_revisions TO blackbread_runtime",
        "GRANT SELECT, INSERT, DELETE ON TABLE graph_temporal_head_nodes TO blackbread_runtime",
    )
    for statement in privilege_statements:
        op.execute(sa.text(statement))


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP TRIGGER graph_temporal_revisions_attested_provenance "
            "ON graph_temporal_scope_revisions"
        )
    )
    op.drop_table("graph_temporal_head_nodes")
    op.drop_table("graph_temporal_scope_revisions")
    op.execute(sa.text("DROP FUNCTION blackbread_require_attested_temporal_revision()"))
    op.drop_table("graph_temporal_scope_roots")
    op.drop_table("graph_temporal_projection_snapshots")
