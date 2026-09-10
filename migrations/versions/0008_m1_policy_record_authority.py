"""Policy-record authority substrate: inert recorder role, lineage constraints, and event trigger.

Migration 0008 creates/validates the inert ``blackbread_policy_recorder`` role fail-closed, adds
``decision_records.evaluation_request_digest`` and its uniqueness constraints, adds the
``agent_events.policy_decision_id`` lineage column with its composite FK, coherence CHECK and
partial unique index, installs a SECURITY INVOKER trigger enforcing exact decision-event lineage,
and grants narrowly bounded recorder privileges. The slice is intentionally unwired; M1.4c2b1
exclusively owns evaluate-and-record transactions.
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

# A recorder created by ``init-runtime.sh`` holds no object grants; any pre-existing privilege is
# unexpected and must abort the migration rather than be normalised away.
_ACCEPTABLE_PRE_UPGRADE_PRIVILEGES: frozenset[tuple[str, str]] = frozenset()

_TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

_EFFECTIVE_TABLE_PRIVILEGES = sa.text(
    "SELECT c.relname AS table_name, p.priv AS privilege "
    "FROM pg_class AS c "
    "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
    "CROSS JOIN unnest(CAST(:privs AS text[])) AS p(priv) "
    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
    "AND has_table_privilege(:role, c.oid, p.priv) "
    "ORDER BY c.relname, p.priv"
)

# has_table_privilege reports only table-wide privileges, so a column-level grant (e.g.
# ``UPDATE (status) ON engagements``) is enumerated separately to keep validation fail-closed.
_EFFECTIVE_COLUMN_PRIVILEGES = sa.text(
    "SELECT table_name, column_name, privilege_type "
    "FROM information_schema.column_privileges "
    "WHERE table_schema = 'public' AND grantee IN (:role, 'PUBLIC') "
    "ORDER BY table_name, column_name, privilege_type"
)

_ROLE_FLAGS = sa.text(
    "SELECT rolcanlogin, rolsuper, rolbypassrls, rolinherit, "
    "rolcreatedb, rolcreaterole, rolreplication FROM pg_roles WHERE rolname = :role"
)

_RECORDER_TABLES = ("action_proposals", "decision_records", "agent_events", "engagements")
_TABLE_REVOKES = tuple(f"REVOKE ALL ON TABLE {t} FROM {{role}}" for t in _RECORDER_TABLES)

_GRANTS = (
    *_TABLE_REVOKES,
    "REVOKE ALL ON SCHEMA public FROM {role}",
    "GRANT USAGE ON SCHEMA public TO {role}",
    "GRANT SELECT, INSERT ON TABLE action_proposals TO {role}",
    "GRANT SELECT, INSERT ON TABLE decision_records TO {role}",
    "GRANT SELECT, INSERT ON TABLE agent_events TO {role}",
    "GRANT SELECT ON TABLE engagements TO {role}",
    # SELECT ... FOR UPDATE on the ledger anchor needs UPDATE on at least one column; the lock
    # token is the only engagements column the recorder may ever write.
    "GRANT UPDATE (ledger_lock_token) ON TABLE engagements TO {role}",
    "REVOKE ALL ON FUNCTION public.blackbread_validate_policy_event() FROM PUBLIC",
)

_REVOKES = (*_TABLE_REVOKES, "REVOKE USAGE ON SCHEMA public FROM {role}")

# The trigger compares the whole payload against an object rebuilt from the durable proposal and
# decision rows. jsonb equality is exact over keys, types and values (an empty object or wrong
# type can never pass); the only gap is numeric scale (2.0 == 2), closed by the canonical-text
# check that follows.
_TRIGGER_FUNCTION = """
CREATE FUNCTION public.blackbread_validate_policy_event()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
DECLARE
    _decision public.decision_records%ROWTYPE;
    _proposal public.action_proposals%ROWTYPE;
    _expected jsonb;
    _graph jsonb;
    _decided_at text;
    _tenant text;
BEGIN
    IF NEW.schema_name <> 'policy.decision.recorded' THEN
        IF current_user = 'blackbread_policy_recorder' THEN
            RAISE EXCEPTION 'blackbread_policy_recorder may only insert policy.decision.recorded'
                USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END IF;

    IF current_user <> 'blackbread_policy_recorder' THEN
        RAISE EXCEPTION 'policy.decision.recorded is reserved for blackbread_policy_recorder'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.schema_version <> 1 THEN
        RAISE EXCEPTION 'policy.decision.recorded requires schema_version 1'
            USING ERRCODE = '23514';
    END IF;

    -- Lineage identity.  append_event() has no policy_decision_id input, so the column is derived
    -- from the hash-covered causation_id and then bound to the stored decision and the payload.
    IF NEW.causation_id IS NULL THEN
        RAISE EXCEPTION 'policy event requires a non-null causation_id'
            USING ERRCODE = '23502';
    END IF;
    IF NEW.policy_decision_id IS NULL THEN
        NEW.policy_decision_id := NEW.causation_id;
    ELSIF NEW.policy_decision_id <> NEW.causation_id THEN
        RAISE EXCEPTION 'policy_decision_id must equal causation_id'
            USING ERRCODE = '23514';
    END IF;

    _tenant := current_setting('blackbread.tenant_id', true);
    IF _tenant IS NULL OR _tenant = '' THEN
        RAISE EXCEPTION 'blackbread.tenant_id is not set'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.tenant_id <> _tenant THEN
        RAISE EXCEPTION 'event tenant_id does not match the session tenant'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO _decision FROM public.decision_records
     WHERE decision_id = NEW.policy_decision_id
       AND tenant_id = NEW.tenant_id
       AND engagement_id = NEW.engagement_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'referenced decision not found for this tenant and engagement'
            USING ERRCODE = '23503';
    END IF;

    SELECT * INTO _proposal FROM public.action_proposals
     WHERE proposal_id = _decision.proposal_id
       AND tenant_id = NEW.tenant_id
       AND engagement_id = NEW.engagement_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'referenced proposal not found for this tenant and engagement'
            USING ERRCODE = '23503';
    END IF;

    IF NEW.producer <> 'policy-record-transaction.v1' THEN
        RAISE EXCEPTION 'producer must be policy-record-transaction.v1'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.correlation_id IS DISTINCT FROM _proposal.proposal_id THEN
        RAISE EXCEPTION 'correlation_id must equal proposal_id'
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
    IF NEW.redaction_refs <> '[]'::jsonb THEN
        RAISE EXCEPTION 'redaction_refs must be empty'
            USING ERRCODE = '23514';
    END IF;

    -- Canonical c2a rendering: ISO-8601 UTC with a 'Z' suffix and six fractional digits only when
    -- the microsecond part is non-zero.  This mirrors datetime.isoformat() exactly, including
    -- trailing zeros, which must not be trimmed.  extract(microseconds ...) also carries the
    -- seconds field, so the modulo is load bearing.
    _decided_at := to_char(_decision.decided_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
        || CASE
             WHEN extract(microseconds FROM (_decision.decided_at AT TIME ZONE 'UTC'))::bigint
                  % 1000000 = 0
             THEN ''
             ELSE '.' || to_char(_decision.decided_at AT TIME ZONE 'UTC', 'US')
           END
        || 'Z';

    _expected := jsonb_build_object(
        'decision_schema_name', _decision.schema_name,
        'decision_schema_version', _decision.schema_version,
        'proposal_id', _proposal.proposal_id,
        'proposal_digest', _proposal.proposal_digest,
        'idempotency_key', _proposal.idempotency_key,
        'decision_id', _decision.decision_id,
        'decision_authority', _decision.decision_authority,
        'outcome', _decision.outcome,
        'reason_code', _decision.reason_code,
        'decided_at', _decided_at,
        'graph_version', jsonb_build_object(
            'state_root_version', _decision.graph_state_root_version,
            'projector_version', _decision.graph_projector_version,
            'state_root', _decision.graph_state_root,
            'ledger_event_count', _decision.graph_ledger_event_count,
            'ledger_head_hash', _decision.graph_ledger_head_hash
        ),
        'runtime_gate_result_digest', _decision.runtime_gate_result_digest,
        'decision_digest', _decision.decision_digest
    );

    IF NEW.payload IS DISTINCT FROM _expected THEN
        RAISE EXCEPTION 'payload does not match the stored decision lineage'
            USING ERRCODE = '23514';
    END IF;

    -- jsonb equality treats 2.0 and 2e0 as equal to 2; the released c2a schema does not.
    _graph := NEW.payload->'graph_version';
    IF (NEW.payload->>'decision_schema_version') <> _decision.schema_version::text
       OR (_graph->>'state_root_version') <> _decision.graph_state_root_version::text
       OR (_graph->>'projector_version') <> _decision.graph_projector_version::text
       OR (_graph->>'ledger_event_count') <> _decision.graph_ledger_event_count::text THEN
        RAISE EXCEPTION 'integer payload fields must use canonical decimal text'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$
"""


def _effective_table_privileges(conn: sa.engine.Connection) -> set[tuple[str, str]]:
    """Every table privilege the recorder currently holds, including any reaching it via PUBLIC."""
    params = {"role": RECORDER_ROLE, "privs": list(_TABLE_PRIVILEGES)}
    return {tuple(row) for row in conn.execute(_EFFECTIVE_TABLE_PRIVILEGES, params).all()}


def _effective_column_privileges(conn: sa.engine.Connection) -> list[tuple[str, ...]]:
    """Column-level grants the recorder holds directly or via PUBLIC (missed by table checks)."""
    rows = conn.execute(_EFFECTIVE_COLUMN_PRIVILEGES, {"role": RECORDER_ROLE}).all()
    return [tuple(row) for row in rows]


def _validate_existing_recorder(conn: sa.engine.Connection) -> None:
    """Fail closed on a pre-existing recorder that is not exactly the inert shape 0008 expects."""
    flags = conn.execute(_ROLE_FLAGS, {"role": RECORDER_ROLE}).one()
    if tuple(flags) != (False,) * 7:
        raise RuntimeError(f"pre-existing {RECORDER_ROLE} has incompatible attributes: {flags}")

    if conn.scalar(
        sa.text("SELECT rolpassword IS NOT NULL FROM pg_authid WHERE rolname = :role"),
        {"role": RECORDER_ROLE},
    ):
        raise RuntimeError(f"pre-existing {RECORDER_ROLE} has a password")

    memberships = conn.scalar(
        sa.text(
            "SELECT count(*) FROM pg_auth_members AS m "
            "JOIN pg_roles AS r ON r.rolname = :role "
            "WHERE m.member = r.oid OR m.roleid = r.oid"
        ),
        {"role": RECORDER_ROLE},
    )
    if memberships:
        raise RuntimeError(f"pre-existing {RECORDER_ROLE} has {memberships} role membership(s)")

    if conn.scalar(
        sa.text("SELECT has_schema_privilege(:role, 'public', 'CREATE')"), {"role": RECORDER_ROLE}
    ):
        raise RuntimeError(f"pre-existing {RECORDER_ROLE} has CREATE on schema public")

    unexpected = sorted(_effective_table_privileges(conn) - _ACCEPTABLE_PRE_UPGRADE_PRIVILEGES)
    if unexpected:
        raise RuntimeError(
            f"pre-existing {RECORDER_ROLE} holds unexpected table privileges {unexpected}; "
            "0008 refuses to normalise it. A privilege reaching the recorder through PUBLIC "
            "cannot be corrected inside the named-role boundary and must be resolved by the "
            "repository owner before upgrading."
        )

    # A freshly bootstrapped recorder holds no column grants; any present are invisible to
    # has_table_privilege and would survive a table-wide REVOKE, so they abort the upgrade.
    unexpected_columns = _effective_column_privileges(conn)
    if unexpected_columns:
        raise RuntimeError(
            f"pre-existing {RECORDER_ROLE} holds unexpected column privileges "
            f"{unexpected_columns}; resolve the grant before upgrading."
        )


def _ensure_recorder_role(conn: sa.engine.Connection) -> None:
    """Create the inert recorder role when absent; otherwise validate it fail-closed."""
    exists = conn.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
        {"role": RECORDER_ROLE},
    )
    if exists:
        _validate_existing_recorder(conn)
        return
    conn.exec_driver_sql(
        f"CREATE ROLE {RECORDER_ROLE} NOLOGIN NOINHERIT NOSUPERUSER "
        "NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION"
    )


def _assert_no_policy_state(conn: sa.engine.Connection, action: str) -> None:
    """Abort unless every policy-record table and the reserved-event slice are empty."""
    for table, predicate in (
        ("action_proposals", "TRUE"),
        ("decision_records", "TRUE"),
        ("agent_events", "schema_name = 'policy.decision.recorded'"),
    ):
        count = conn.exec_driver_sql(
            f"SELECT count(*) FROM {table} WHERE {predicate}"  # noqa: S608 - fixed literals
        ).scalar()
        if count:
            raise RuntimeError(
                f"cannot {action}: {table} holds {count} row(s) matching {predicate}"
            )


def upgrade() -> None:
    conn = op.get_bind()
    require_isolatable_runtime_role(conn)
    _ensure_recorder_role(conn)
    _assert_no_policy_state(conn, "upgrade")

    op.add_column(
        "decision_records",
        sa.Column("evaluation_request_digest", sa.String(64), nullable=False),
    )
    op.create_check_constraint(
        "ck_decision_records_eval_request_digest",
        "decision_records",
        "evaluation_request_digest ~ '^[0-9a-f]{64}$'",
    )
    op.create_unique_constraint(
        "uq_decision_records_proposal",
        "decision_records",
        ["tenant_id", "engagement_id", "proposal_id"],
    )
    op.create_unique_constraint(
        "uq_decision_records_decision_identity",
        "decision_records",
        ["tenant_id", "engagement_id", "decision_id"],
    )

    op.add_column(
        "agent_events",
        sa.Column("policy_decision_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_events_policy_decision",
        "agent_events",
        "decision_records",
        ["tenant_id", "engagement_id", "policy_decision_id"],
        ["tenant_id", "engagement_id", "decision_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_agent_events_policy_decision_coherence",
        "agent_events",
        "(schema_name = 'policy.decision.recorded' AND schema_version = 1 "
        "AND policy_decision_id IS NOT NULL) "
        "OR (schema_name <> 'policy.decision.recorded' AND policy_decision_id IS NULL)",
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_agent_events_policy_decision_unique "
        "ON agent_events (policy_decision_id) WHERE policy_decision_id IS NOT NULL"
    )

    conn.exec_driver_sql(_TRIGGER_FUNCTION)
    op.execute(
        "CREATE TRIGGER agent_events_validate_policy_event "
        "BEFORE INSERT ON agent_events FOR EACH ROW "
        "EXECUTE FUNCTION public.blackbread_validate_policy_event()"
    )

    for statement in _GRANTS:
        conn.exec_driver_sql(statement.format(role=RECORDER_ROLE))


def downgrade() -> None:
    conn = op.get_bind()
    _assert_no_policy_state(conn, "downgrade")
    if conn.exec_driver_sql(
        "SELECT count(*) FROM agent_events WHERE policy_decision_id IS NOT NULL"
    ).scalar():
        raise RuntimeError("cannot downgrade: agent_events holds policy lineage references")

    for statement in _REVOKES:
        conn.exec_driver_sql(statement.format(role=RECORDER_ROLE))

    op.execute("DROP TRIGGER IF EXISTS agent_events_validate_policy_event ON agent_events")
    op.execute("DROP FUNCTION IF EXISTS public.blackbread_validate_policy_event()")
    op.execute("DROP INDEX IF EXISTS ix_agent_events_policy_decision_unique")
    op.drop_constraint("ck_agent_events_policy_decision_coherence", "agent_events", type_="check")
    op.drop_constraint("fk_agent_events_policy_decision", "agent_events", type_="foreignkey")
    op.drop_column("agent_events", "policy_decision_id")
    op.drop_constraint("uq_decision_records_decision_identity", "decision_records", type_="unique")
    op.drop_constraint("uq_decision_records_proposal", "decision_records", type_="unique")
    op.drop_constraint("ck_decision_records_eval_request_digest", "decision_records", type_="check")
    op.drop_column("decision_records", "evaluation_request_digest")
    # The cluster-level role is deployment-owned and is never dropped from Alembic.
