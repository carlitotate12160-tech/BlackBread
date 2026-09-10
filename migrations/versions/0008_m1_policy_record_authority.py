"""Policy-record authority substrate: inert recorder role, constraints, lineage FK, and event trigger.

Migration 0008 creates the inert ``blackbread_policy_recorder`` database role (if absent), validates
its exact shape, adds the ``evaluation_request_digest`` column and decision-uniqueness constraints
to ``decision_records``, adds the ``policy_decision_id`` lineage column and coherence CHECK to
``agent_events``, installs a SECURITY INVOKER trigger that enforces exact decision-event lineage,
and grants narrowly bounded recorder privileges.

This slice is intentionally unwired: no production code assumes the recorder, and no production
transaction calls this substrate.  M1.4c2b1 exclusively owns evaluate-and-record transaction
ownership.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from blackbread.tenancy.roles import require_isolatable_runtime_role

revision: str = "0008_m1_policy_record_authority"
down_revision: str | None = "0007_m1_policy_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECORDER_ROLE = "blackbread_policy_recorder"

# Tables the recorder MUST NOT have privileges on.
_DENIED_TABLES = (
    "clients",
    "platform_metadata",
    "graph_projection_snapshots",
    "graph_nodes",
    "graph_temporal_projection_snapshots",
    "graph_temporal_scope_roots",
    "graph_temporal_scope_revisions",
    "graph_temporal_head_nodes",
    "alembic_version",
)


def _ensure_recorder_role(conn: sa.engine.Connection) -> None:
    """Create or validate the inert recorder role, fail-closed."""
    exists = conn.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :r)"),
        {"r": RECORDER_ROLE},
    )
    if not exists:
        conn.execute(
            sa.text(
                f"CREATE ROLE {RECORDER_ROLE} "  # noqa: S608
                "NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS "
                "NOCREATEDB NOCREATEROLE NOREPLICATION"
            )
        )
        return

    # Validate the existing role fail-closed.
    flags = conn.execute(
        sa.text(
            "SELECT rolcanlogin, rolsuper, rolbypassrls, rolinherit, "
            "rolcreatedb, rolcreaterole, rolreplication "
            "FROM pg_roles WHERE rolname = :r"
        ),
        {"r": RECORDER_ROLE},
    ).one()
    expected = (False, False, False, False, False, False, False)
    if flags != expected:
        raise RuntimeError(
            f"Pre-existing {RECORDER_ROLE} has incompatible flags: {flags} (expected {expected})"
        )

    has_password = conn.scalar(
        sa.text("SELECT rolpassword IS NOT NULL FROM pg_authid WHERE rolname = :r"),
        {"r": RECORDER_ROLE},
    )
    if has_password:
        raise RuntimeError(f"Pre-existing {RECORDER_ROLE} has a password")

    oid = conn.scalar(
        sa.text("SELECT oid FROM pg_roles WHERE rolname = :r"), {"r": RECORDER_ROLE}
    )
    parent_count = conn.scalar(
        sa.text("SELECT count(*) FROM pg_auth_members WHERE member = :o"), {"o": oid}
    )
    if parent_count != 0:
        raise RuntimeError(f"Pre-existing {RECORDER_ROLE} has {parent_count} parent role(s)")

    member_count = conn.scalar(
        sa.text("SELECT count(*) FROM pg_auth_members WHERE roleid = :o"), {"o": oid}
    )
    if member_count != 0:
        raise RuntimeError(f"Pre-existing {RECORDER_ROLE} has {member_count} member role(s)")

    # Validate no CREATE on public schema.
    has_create = conn.scalar(
        sa.text(f"SELECT has_schema_privilege('{RECORDER_ROLE}', 'public', 'CREATE')")
    )
    if has_create:
        raise RuntimeError(f"Pre-existing {RECORDER_ROLE} has CREATE on schema public")

    # Validate no effective privilege on denied application tables.
    for table in _DENIED_TABLES:
        table_exists = conn.scalar(sa.text("SELECT to_regclass(:t)"), {"t": f"public.{table}"})
        if table_exists is None:
            continue
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            has_priv = conn.scalar(
                sa.text(f"SELECT has_table_privilege('{RECORDER_ROLE}', '{table}', '{priv}')")
            )
            if has_priv:
                raise RuntimeError(
                    f"Pre-existing {RECORDER_ROLE} has {priv} on {table}"
                )


def _check_empty_tables(conn: sa.engine.Connection) -> None:
    """Abort if any proposal, decision, or reserved event exists."""
    for table, where in (
        ("action_proposals", "1=1"),
        ("decision_records", "1=1"),
        ("agent_events", "schema_name = 'policy.decision.recorded'"),
    ):
        count = conn.scalar(sa.text(f"SELECT count(*) FROM {table} WHERE {where}"))  # noqa: S608
        if count and count > 0:
            raise RuntimeError(
                f"Cannot upgrade: {table} contains {count} row(s) that must not exist"
            )


def upgrade() -> None:
    require_isolatable_runtime_role(op.get_bind())

    conn = op.get_bind()
    _ensure_recorder_role(conn)
    _check_empty_tables(conn)

    # ── Schema changes ──

    # evaluation_request_digest on decision_records
    op.add_column(
        "decision_records",
        sa.Column("evaluation_request_digest", sa.String(64), nullable=False),
    )
    op.create_check_constraint(
        "ck_decision_records_eval_request_digest",
        "decision_records",
        "evaluation_request_digest ~ '^[0-9a-f]{64}$'",
    )

    # One decision per proposal
    op.create_unique_constraint(
        "uq_decision_records_proposal",
        "decision_records",
        ["tenant_id", "engagement_id", "proposal_id"],
    )

    # Composite candidate key for event lineage
    op.create_unique_constraint(
        "uq_decision_records_decision_identity",
        "decision_records",
        ["tenant_id", "engagement_id", "decision_id"],
    )

    # policy_decision_id on agent_events
    op.add_column(
        "agent_events",
        sa.Column("policy_decision_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Composite FK to decision_records
    op.create_foreign_key(
        "fk_agent_events_policy_decision",
        "agent_events",
        "decision_records",
        ["tenant_id", "engagement_id", "policy_decision_id"],
        ["tenant_id", "engagement_id", "decision_id"],
        ondelete="RESTRICT",
    )

    # Coherence CHECK
    op.create_check_constraint(
        "ck_agent_events_policy_decision_coherence",
        "agent_events",
        "(schema_name = 'policy.decision.recorded' AND schema_version = 1 "
        "AND policy_decision_id IS NOT NULL) "
        "OR (schema_name <> 'policy.decision.recorded' AND policy_decision_id IS NULL)",
    )

    # Partial unique index: at most one event per decision
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX ix_agent_events_policy_decision_unique "
            "ON agent_events (policy_decision_id) "
            "WHERE policy_decision_id IS NOT NULL"
        )
    )

    # ── SECURITY INVOKER trigger ──
    conn.exec_driver_sql(
            """
CREATE FUNCTION public.blackbread_validate_policy_event()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
DECLARE
    _decision RECORD;
    _proposal RECORD;
    _payload jsonb;
    _graph   jsonb;
    _top_keys text[];
    _graph_keys text[];
    _expected_top_keys text[] := ARRAY[
        'decided_at','decision_authority','decision_digest','decision_id',
        'decision_schema_name','decision_schema_version','graph_version',
        'idempotency_key','outcome','proposal_digest','proposal_id',
        'reason_code','runtime_gate_result_digest'
    ];
    _expected_graph_keys text[] := ARRAY[
        'ledger_event_count','ledger_head_hash','projector_version',
        'state_root','state_root_version'
    ];
    _decided_at_text text;
    _tenant_guc text;
BEGIN
    -- Rule 1/2: identity restriction
    IF NEW.schema_name = 'policy.decision.recorded' THEN
        IF current_user <> 'blackbread_policy_recorder' THEN
            RAISE EXCEPTION 'policy.decision.recorded is reserved for blackbread_policy_recorder'
                USING ERRCODE = '42501';
        END IF;
    ELSE
        IF current_user = 'blackbread_policy_recorder' THEN
            RAISE EXCEPTION 'blackbread_policy_recorder may only insert policy.decision.recorded'
                USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END IF;

    -- Rule 3: structural validation
    IF NEW.schema_version <> 1 THEN
        RAISE EXCEPTION 'policy.decision.recorded requires schema_version = 1'
            USING ERRCODE = '23514';
    END IF;

    -- Rule: empty redactions
    IF NEW.redaction_refs <> '[]'::jsonb THEN
        RAISE EXCEPTION 'redaction_refs must be empty'
            USING ERRCODE = '23514';
    END IF;

    -- Derive policy_decision_id from causation_id when NULL
    IF NEW.policy_decision_id IS NULL THEN
        IF NEW.causation_id IS NULL THEN
            RAISE EXCEPTION 'policy event requires non-null causation_id'
                USING ERRCODE = '23502';
        END IF;
        NEW.policy_decision_id := NEW.causation_id;
    ELSE
        IF NEW.policy_decision_id <> NEW.causation_id THEN
            RAISE EXCEPTION 'policy_decision_id must equal causation_id'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    -- Tenant GUC check
    _tenant_guc := current_setting('blackbread.tenant_id', true);
    IF _tenant_guc IS NULL OR _tenant_guc = '' THEN
        RAISE EXCEPTION 'blackbread.tenant_id GUC is not set'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.tenant_id <> _tenant_guc THEN
        RAISE EXCEPTION 'event tenant_id does not match the session GUC'
            USING ERRCODE = '23514';
    END IF;

    -- Look up decision
    SELECT * INTO _decision FROM public.decision_records
    WHERE decision_id = NEW.policy_decision_id
      AND tenant_id = NEW.tenant_id
      AND engagement_id = NEW.engagement_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'referenced decision not found'
            USING ERRCODE = '23503';
    END IF;

    -- Look up proposal
    SELECT * INTO _proposal FROM public.action_proposals
    WHERE proposal_id = _decision.proposal_id
      AND tenant_id = NEW.tenant_id
      AND engagement_id = NEW.engagement_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'referenced proposal not found'
            USING ERRCODE = '23503';
    END IF;

    -- Rule 4: exact envelope comparison
    IF NEW.producer <> 'policy-record-transaction.v1' THEN
        RAISE EXCEPTION 'producer must be policy-record-transaction.v1'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.correlation_id <> _proposal.proposal_id::text THEN
        RAISE EXCEPTION 'correlation_id must equal proposal_id'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.causation_id <> _decision.decision_id THEN
        RAISE EXCEPTION 'causation_id must equal decision_id'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.occurred_at <> _decision.decided_at THEN
        RAISE EXCEPTION 'occurred_at must equal decided_at'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.sensitivity <> 'internal' THEN
        RAISE EXCEPTION 'sensitivity must be internal'
            USING ERRCODE = '23514';
    END IF;

    -- Rule 5: exact payload validation
    _payload := NEW.payload;

    -- Key set validation (sorted)
    SELECT array_agg(k ORDER BY k) INTO _top_keys
    FROM jsonb_object_keys(_payload) AS k;
    IF _top_keys <> _expected_top_keys THEN
        RAISE EXCEPTION 'payload key set mismatch'
            USING ERRCODE = '23514';
    END IF;

    -- graph_version must be object
    IF jsonb_typeof(_payload->'graph_version') <> 'object' THEN
        RAISE EXCEPTION 'graph_version must be a JSON object'
            USING ERRCODE = '23514';
    END IF;
    _graph := _payload->'graph_version';

    SELECT array_agg(k ORDER BY k) INTO _graph_keys
    FROM jsonb_object_keys(_graph) AS k;
    IF _graph_keys <> _expected_graph_keys THEN
        RAISE EXCEPTION 'graph_version key set mismatch'
            USING ERRCODE = '23514';
    END IF;

    -- JSON type validation for integer fields
    IF jsonb_typeof(_payload->'decision_schema_version') <> 'number'
       OR (_payload->>'decision_schema_version') <> _decision.schema_version::text THEN
        RAISE EXCEPTION 'decision_schema_version type or value mismatch'
            USING ERRCODE = '23514';
    END IF;
    -- Reject non-integer representations (2.0, 2e0)
    IF (_payload->>'decision_schema_version') ~ '\\.' OR
       (_payload->>'decision_schema_version') ~ '[eE]' THEN
        RAISE EXCEPTION 'decision_schema_version must be canonical integer'
            USING ERRCODE = '23514';
    END IF;

    IF jsonb_typeof(_graph->'state_root_version') <> 'number'
       OR (_graph->>'state_root_version') <> _decision.graph_state_root_version::text THEN
        RAISE EXCEPTION 'state_root_version type or value mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF (_graph->>'state_root_version') ~ '\\.' OR (_graph->>'state_root_version') ~ '[eE]' THEN
        RAISE EXCEPTION 'state_root_version must be canonical integer'
            USING ERRCODE = '23514';
    END IF;

    IF jsonb_typeof(_graph->'projector_version') <> 'number'
       OR (_graph->>'projector_version') <> _decision.graph_projector_version::text THEN
        RAISE EXCEPTION 'projector_version type or value mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF (_graph->>'projector_version') ~ '\\.' OR (_graph->>'projector_version') ~ '[eE]' THEN
        RAISE EXCEPTION 'projector_version must be canonical integer'
            USING ERRCODE = '23514';
    END IF;

    IF jsonb_typeof(_graph->'ledger_event_count') <> 'number'
       OR (_graph->>'ledger_event_count') <> _decision.graph_ledger_event_count::text THEN
        RAISE EXCEPTION 'ledger_event_count type or value mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF (_graph->>'ledger_event_count') ~ '\\.' OR (_graph->>'ledger_event_count') ~ '[eE]' THEN
        RAISE EXCEPTION 'ledger_event_count must be canonical integer'
            USING ERRCODE = '23514';
    END IF;

    -- String field type+value validation
    IF jsonb_typeof(_payload->'decision_schema_name') <> 'string'
       OR _payload->>'decision_schema_name' <> _decision.schema_name THEN
        RAISE EXCEPTION 'decision_schema_name mismatch' USING ERRCODE = '23514';
    END IF;
    IF jsonb_typeof(_payload->'proposal_id') <> 'string'
       OR _payload->>'proposal_id' <> _proposal.proposal_id::text THEN
        RAISE EXCEPTION 'proposal_id mismatch' USING ERRCODE = '23514';
    END IF;
    IF jsonb_typeof(_payload->'proposal_digest') <> 'string'
       OR _payload->>'proposal_digest' <> _proposal.proposal_digest THEN
        RAISE EXCEPTION 'proposal_digest mismatch' USING ERRCODE = '23514';
    END IF;
    IF jsonb_typeof(_payload->'idempotency_key') <> 'string'
       OR _payload->>'idempotency_key' <> _proposal.idempotency_key THEN
        RAISE EXCEPTION 'idempotency_key mismatch' USING ERRCODE = '23514';
    END IF;
    IF jsonb_typeof(_payload->'decision_id') <> 'string'
       OR _payload->>'decision_id' <> _decision.decision_id::text THEN
        RAISE EXCEPTION 'decision_id mismatch' USING ERRCODE = '23514';
    END IF;
    IF jsonb_typeof(_payload->'decision_authority') <> 'string'
       OR _payload->>'decision_authority' <> _decision.decision_authority THEN
        RAISE EXCEPTION 'decision_authority mismatch' USING ERRCODE = '23514';
    END IF;
    IF jsonb_typeof(_payload->'outcome') <> 'string'
       OR _payload->>'outcome' <> _decision.outcome THEN
        RAISE EXCEPTION 'outcome mismatch' USING ERRCODE = '23514';
    END IF;

    -- reason_code: JSON null for SQL NULL, string for non-null
    IF _decision.reason_code IS NULL THEN
        IF jsonb_typeof(_payload->'reason_code') <> 'null' THEN
            RAISE EXCEPTION 'reason_code must be JSON null when decision has no reason'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF jsonb_typeof(_payload->'reason_code') <> 'string'
           OR _payload->>'reason_code' <> _decision.reason_code THEN
            RAISE EXCEPTION 'reason_code mismatch' USING ERRCODE = '23514';
        END IF;
    END IF;

    -- decided_at: exact canonical UTC Z text comparison
    _decided_at_text := _payload->>'decided_at';
    IF jsonb_typeof(_payload->'decided_at') <> 'string' THEN
        RAISE EXCEPTION 'decided_at must be a JSON string' USING ERRCODE = '23514';
    END IF;
    -- Compare with canonical c2a representation
    IF _decided_at_text <> (
       to_char(_decision.decided_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
       || CASE WHEN extract(microsecond FROM _decision.decided_at) = 0
               THEN 'Z'
               ELSE '.' || rtrim(to_char(extract(microsecond FROM _decision.decided_at), 'FM000000'), '0') || 'Z'
          END
    )
    THEN
        RAISE EXCEPTION 'decided_at text does not match canonical UTC Z representation'
            USING ERRCODE = '23514';
    END IF;

    IF jsonb_typeof(_payload->'runtime_gate_result_digest') <> 'string'
       OR _payload->>'runtime_gate_result_digest' <> _decision.runtime_gate_result_digest THEN
        RAISE EXCEPTION 'runtime_gate_result_digest mismatch' USING ERRCODE = '23514';
    END IF;
    IF jsonb_typeof(_payload->'decision_digest') <> 'string'
       OR _payload->>'decision_digest' <> _decision.decision_digest THEN
        RAISE EXCEPTION 'decision_digest mismatch' USING ERRCODE = '23514';
    END IF;

    -- graph_version string fields
    IF jsonb_typeof(_graph->'state_root') <> 'string'
       OR _graph->>'state_root' <> _decision.graph_state_root THEN
        RAISE EXCEPTION 'graph state_root mismatch' USING ERRCODE = '23514';
    END IF;
    IF jsonb_typeof(_graph->'ledger_head_hash') <> 'string'
       OR _graph->>'ledger_head_hash' <> _decision.graph_ledger_head_hash THEN
        RAISE EXCEPTION 'graph ledger_head_hash mismatch' USING ERRCODE = '23514';
    END IF;



    RETURN NEW;
END;
$$
"""
    )

    op.execute(
        "CREATE TRIGGER agent_events_validate_policy_event "
        "BEFORE INSERT ON agent_events "
        "FOR EACH ROW "
        "EXECUTE FUNCTION public.blackbread_validate_policy_event()"
    )

    # ── Privileges ──
    privilege_statements = (
        f"REVOKE ALL ON TABLE action_proposals FROM {RECORDER_ROLE}",
        f"REVOKE ALL ON TABLE decision_records FROM {RECORDER_ROLE}",
        f"REVOKE ALL ON TABLE agent_events FROM {RECORDER_ROLE}",
        f"REVOKE ALL ON TABLE engagements FROM {RECORDER_ROLE}",
        f"REVOKE ALL ON SCHEMA public FROM {RECORDER_ROLE}",
        f"GRANT USAGE ON SCHEMA public TO {RECORDER_ROLE}",
        f"GRANT SELECT, INSERT ON TABLE action_proposals TO {RECORDER_ROLE}",
        f"GRANT SELECT, INSERT ON TABLE decision_records TO {RECORDER_ROLE}",
        f"GRANT SELECT, INSERT ON TABLE agent_events TO {RECORDER_ROLE}",
        f"GRANT SELECT ON TABLE engagements TO {RECORDER_ROLE}",
        f"GRANT UPDATE (ledger_lock_token) ON TABLE engagements TO {RECORDER_ROLE}",
        "REVOKE ALL ON FUNCTION public.blackbread_validate_policy_event() FROM PUBLIC",
    )
    for stmt in privilege_statements:
        op.execute(sa.text(stmt))


def downgrade() -> None:
    conn = op.get_bind()

    # Refuse downgrade if data exists
    for table, where in (
        ("action_proposals", "1=1"),
        ("decision_records", "1=1"),
        ("agent_events", "schema_name = 'policy.decision.recorded'"),
        ("agent_events", "policy_decision_id IS NOT NULL"),
    ):
        count = conn.scalar(sa.text(f"SELECT count(*) FROM {table} WHERE {where}"))  # noqa: S608
        if count and count > 0:
            raise RuntimeError(
                f"Cannot downgrade: {table} contains {count} row(s) "
                f"(where {where}) that must not exist"
            )

    # Remove privileges
    revoke_statements = (
        f"REVOKE ALL ON TABLE action_proposals FROM {RECORDER_ROLE}",
        f"REVOKE ALL ON TABLE decision_records FROM {RECORDER_ROLE}",
        f"REVOKE ALL ON TABLE agent_events FROM {RECORDER_ROLE}",
        f"REVOKE ALL ON TABLE engagements FROM {RECORDER_ROLE}",
        f"REVOKE USAGE ON SCHEMA public FROM {RECORDER_ROLE}",
    )
    for stmt in revoke_statements:
        op.execute(sa.text(stmt))

    # Drop trigger and function
    op.execute(sa.text("DROP TRIGGER IF EXISTS agent_events_validate_policy_event ON agent_events"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS public.blackbread_validate_policy_event()"))

    # Drop index
    op.execute(sa.text("DROP INDEX IF EXISTS ix_agent_events_policy_decision_unique"))

    # Drop constraints and columns
    op.drop_constraint("ck_agent_events_policy_decision_coherence", "agent_events", type_="check")
    op.drop_constraint("fk_agent_events_policy_decision", "agent_events", type_="foreignkey")
    op.drop_column("agent_events", "policy_decision_id")

    op.drop_constraint("uq_decision_records_decision_identity", "decision_records", type_="unique")
    op.drop_constraint("uq_decision_records_proposal", "decision_records", type_="unique")
    op.drop_constraint(
        "ck_decision_records_eval_request_digest", "decision_records", type_="check"
    )
    op.drop_column("decision_records", "evaluation_request_digest")

    # Do NOT drop the cluster-level role.
