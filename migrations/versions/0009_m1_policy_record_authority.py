"""M1.4c2b0b inert recorder authority and database-enforced decision/event lineage.

Grants the pre-existing inert ``blackbread_policy_recorder`` role exactly the minimum privileges a
future authenticated evaluate-and-record transaction (M1.4c2b1) needs -- ``SELECT`` on the durable
proposal/decision substrate and ``INSERT`` on the ledger -- and installs the durable lineage that
binds a ``policy.decision.recorded`` event to the exact ``DecisionRecord`` and its ``ActionProposal``
under the same tenant and engagement.

The role remains NOLOGIN / NOINHERIT / password-free / membership-free and is unreachable from any
production entry point after this slice; it is exercised only by a superuser ``SET ROLE`` in tests
and by the later b1 transaction. This migration owns the database boundary only. It does not run the
Policy evaluator, does not authenticate the producer of a durable record, and an ``ALLOW`` row is not
execution permission.

The lineage column ``agent_events.policy_decision_id`` is derived by the ``SECURITY INVOKER``
validation trigger from the event's ``causation_id``; a caller may not supply it. The trigger and the
FK/check/partial-unique constraints -- not a Python wrapper -- own record-to-event integrity and the
exact database writer identity.
"""

# ruff: noqa: S608 -- every SQL string here interpolates only module-constant identifiers
# (role, schema, function names), never caller input; this is static migration DDL.
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_m1_policy_record_authority"
down_revision: str | None = "0008_m1_policy_recorder_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECORDER_ROLE = "blackbread_policy_recorder"
POLICY_EVENT_SCHEMA = "policy.decision.recorded"
LINEAGE_TRIGGER = "agent_events_validate_policy_decision"
LINEAGE_FUNCTION = "blackbread_validate_policy_decision_event"

# Exact privilege set the future b1 transaction needs and nothing more. Defence-in-depth REVOKEs run
# first so the SELECT/INSERT-only guarantee holds even if a future ALTER DEFAULT PRIVILEGES grants
# DML to the recorder; revoking from PUBLIC does not remove role-direct grants.
_GRANTS = (
    f"REVOKE ALL ON TABLE action_proposals, decision_records, agent_events FROM {RECORDER_ROLE}",
    f"GRANT USAGE ON SCHEMA public TO {RECORDER_ROLE}",
    f"GRANT SELECT ON TABLE action_proposals, decision_records TO {RECORDER_ROLE}",
    f"GRANT INSERT ON TABLE agent_events TO {RECORDER_ROLE}",
    f"REVOKE ALL ON FUNCTION {LINEAGE_FUNCTION}() FROM PUBLIC",
)
_REVOKES = (
    f"REVOKE INSERT ON TABLE agent_events FROM {RECORDER_ROLE}",
    f"REVOKE SELECT ON TABLE action_proposals, decision_records FROM {RECORDER_ROLE}",
    f"REVOKE USAGE ON SCHEMA public FROM {RECORDER_ROLE}",
)

# One JSONB equality of the whole payload would treat the JSON number ``1.0`` as equal to the integer
# ``1``; the contract stores integers, so those four fields are additionally checked for a canonical
# integer text form. Timestamps are compared as ``timestamptz`` so instant equality is exact without
# depending on a textual format. Every scalar comparison is NULL-safe (``reason_code`` is JSON null
# for an ALLOW decision). The interpolations below are module-constant identifiers, never input.
_VALIDATE_FUNCTION = f"""
CREATE FUNCTION {LINEAGE_FUNCTION}()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
DECLARE
    decision public.decision_records%ROWTYPE;
    proposal public.action_proposals%ROWTYPE;
    tenant_guc text := current_setting('blackbread.tenant_id', true);
    payload jsonb := NEW.payload;
    graph jsonb;
BEGIN
    IF NEW.schema_name <> '{POLICY_EVENT_SCHEMA}' THEN
        -- Non-policy events: the reserved recorder may not author them, and the database-derived
        -- lineage column must stay empty for a normal ledger append.
        IF current_user = '{RECORDER_ROLE}' THEN
            RAISE EXCEPTION 'recorder identity may only write {POLICY_EVENT_SCHEMA} events'
                USING ERRCODE = '42501';
        END IF;
        IF NEW.policy_decision_id IS NOT NULL THEN
            RAISE EXCEPTION 'policy_decision_id is reserved for {POLICY_EVENT_SCHEMA} events'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    -- Reserved writer identity and the only version this slice admits.
    IF current_user <> '{RECORDER_ROLE}' THEN
        RAISE EXCEPTION '{POLICY_EVENT_SCHEMA} requires the reserved recorder identity'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.schema_version <> 1 THEN
        RAISE EXCEPTION 'unsupported {POLICY_EVENT_SCHEMA} schema version'
            USING ERRCODE = '23514';
    END IF;

    -- The lineage column is database-derived from causation; a caller may not supply its own value.
    IF NEW.policy_decision_id IS NOT NULL THEN
        RAISE EXCEPTION 'policy_decision_id is database-derived and must not be supplied'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.correlation_id IS NULL OR NEW.causation_id IS NULL THEN
        RAISE EXCEPTION 'policy decision event requires correlation and causation ids'
            USING ERRCODE = '23514';
    END IF;
    NEW.policy_decision_id := NEW.causation_id;

    -- Transaction-local tenant context must match the event tenant (belt-and-suspenders with RLS).
    IF tenant_guc IS DISTINCT FROM NEW.tenant_id THEN
        RAISE EXCEPTION 'tenant context does not match the policy decision event'
            USING ERRCODE = '42501';
    END IF;

    -- Envelope fields owned by the projection contract.
    IF NEW.producer <> 'policy-record-transaction.v1'
       OR NEW.sensitivity <> 'internal'
       OR NEW.redaction_refs <> '[]'::jsonb THEN
        RAISE EXCEPTION 'policy decision event envelope does not match the recorder contract'
            USING ERRCODE = '23514';
    END IF;

    -- The exact durable decision and its exact proposal, both under this tenant and engagement.
    SELECT * INTO decision FROM public.decision_records
        WHERE tenant_id = NEW.tenant_id
          AND engagement_id = NEW.engagement_id
          AND decision_id = NEW.causation_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'referenced decision does not exist under this tenant and engagement'
            USING ERRCODE = '23503';
    END IF;
    SELECT * INTO proposal FROM public.action_proposals
        WHERE tenant_id = NEW.tenant_id
          AND engagement_id = NEW.engagement_id
          AND proposal_id = NEW.correlation_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'referenced proposal does not exist under this tenant and engagement'
            USING ERRCODE = '23503';
    END IF;
    IF decision.proposal_id <> NEW.correlation_id
       OR decision.proposal_digest <> proposal.proposal_digest THEN
        RAISE EXCEPTION 'decision does not reference the correlated proposal'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.occurred_at <> decision.decided_at THEN
        RAISE EXCEPTION 'event occurrence time does not match the decision'
            USING ERRCODE = '23514';
    END IF;

    -- Exact payload key set: rejects missing, extra, empty, and nested-shape mutations.
    IF NOT (payload ?& ARRAY[
                'decision_schema_name','decision_schema_version','proposal_id','proposal_digest',
                'idempotency_key','decision_id','decision_authority','outcome','reason_code',
                'decided_at','graph_version','runtime_gate_result_digest','decision_digest']
            AND (SELECT count(*) FROM jsonb_object_keys(payload)) = 13) THEN
        RAISE EXCEPTION 'policy decision payload key set is not exact'
            USING ERRCODE = '23514';
    END IF;
    graph := payload->'graph_version';
    IF jsonb_typeof(graph) <> 'object'
       OR NOT (graph ?& ARRAY['state_root_version','projector_version','state_root',
                              'ledger_event_count','ledger_head_hash']
               AND (SELECT count(*) FROM jsonb_object_keys(graph)) = 5) THEN
        RAISE EXCEPTION 'policy decision graph_version key set is not exact'
            USING ERRCODE = '23514';
    END IF;

    -- Exact scalar values against the durable rows (NULL-safe; reason_code is JSON null on ALLOW).
    IF payload->>'decision_schema_name' IS DISTINCT FROM decision.schema_name
       OR payload->>'decision_authority' IS DISTINCT FROM decision.decision_authority
       OR payload->>'outcome' IS DISTINCT FROM decision.outcome
       OR payload->>'reason_code' IS DISTINCT FROM decision.reason_code
       OR (payload->>'proposal_id')::uuid IS DISTINCT FROM proposal.proposal_id
       OR (payload->>'decision_id')::uuid IS DISTINCT FROM decision.decision_id
       OR payload->>'proposal_digest' IS DISTINCT FROM proposal.proposal_digest
       OR payload->>'idempotency_key' IS DISTINCT FROM proposal.idempotency_key
       OR payload->>'runtime_gate_result_digest' IS DISTINCT FROM decision.runtime_gate_result_digest
       OR payload->>'decision_digest' IS DISTINCT FROM decision.decision_digest
       OR (payload->>'decided_at')::timestamptz IS DISTINCT FROM decision.decided_at
       OR graph->>'state_root' IS DISTINCT FROM decision.graph_state_root
       OR graph->>'ledger_head_hash' IS DISTINCT FROM decision.graph_ledger_head_hash THEN
        RAISE EXCEPTION 'policy decision payload does not match the durable decision lineage'
            USING ERRCODE = '23514';
    END IF;

    -- Canonical integers: a fractional/exponent JSON number (e.g. 1.0) must not stand in for the
    -- integer the contract stores. ``->>`` turns a JSON null into SQL NULL, which would make these
    -- predicates evaluate to NULL and skip the rejection branch, so each field is checked with an
    -- explicit IS NULL first and the comparison itself is NULL-safe (IS DISTINCT FROM).
    IF payload->>'decision_schema_version' IS NULL
       OR payload->>'decision_schema_version' !~ '^[0-9]+$'
       OR (payload->>'decision_schema_version')::bigint IS DISTINCT FROM decision.schema_version
       OR graph->>'state_root_version' IS NULL
       OR graph->>'state_root_version' !~ '^[0-9]+$'
       OR (graph->>'state_root_version')::bigint IS DISTINCT FROM decision.graph_state_root_version
       OR graph->>'projector_version' IS NULL
       OR graph->>'projector_version' !~ '^[0-9]+$'
       OR (graph->>'projector_version')::bigint IS DISTINCT FROM decision.graph_projector_version
       OR graph->>'ledger_event_count' IS NULL
       OR graph->>'ledger_event_count' !~ '^[0-9]+$'
       OR (graph->>'ledger_event_count')::bigint IS DISTINCT FROM decision.graph_ledger_event_count THEN
        RAISE EXCEPTION 'policy decision payload integers are not canonical or do not match'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$
"""

_LINEAGE_CHECK = (
    "CASE WHEN schema_name = 'policy.decision.recorded' "
    "THEN schema_version = 1 AND policy_decision_id IS NOT NULL "
    "ELSE policy_decision_id IS NULL END"
)


# The recorder must still hold the complete inert shape 0008 owns before this migration grants it
# authority: granting SELECT/INSERT to a role that drifted out-of-band (INHERIT, a membership, a
# password, a dependency, or a role setting) would silently extend the reserved writer beyond the
# reviewed contract. The checks below mirror 0008's inert contract exactly, fail closed, and run
# before any grant so the cluster-global pg_shdepend count is still zero at check time.
_ROLE_ATTRIBUTES = sa.text(
    "SELECT oid, rolcanlogin, rolinherit, rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
    "rolbypassrls, rolconnlimit, (rolpassword IS NOT NULL) AS has_password, "
    "(rolvaliduntil IS NOT NULL) AS has_validity FROM pg_authid WHERE rolname = :name"
)
_DIRECT_DEPENDENCIES = sa.text(
    "SELECT count(*) FROM pg_shdepend WHERE refclassid = 'pg_authid'::regclass AND refobjid = :oid"
)
_MEMBERSHIPS = sa.text(
    "SELECT count(*) FROM pg_auth_members WHERE roleid = :oid OR member = :oid OR grantor = :oid"
)
_ROLE_SETTINGS = sa.text("SELECT count(*) FROM pg_db_role_setting WHERE setrole = :oid")


def _require_inert_recorder() -> None:
    """Fail closed unless the recorder role still holds the exact inert identity 0008 owns."""
    bind = op.get_bind()
    row = bind.execute(_ROLE_ATTRIBUTES, {"name": RECORDER_ROLE}).mappings().one_or_none()
    if row is None:
        raise RuntimeError(f"required inert role {RECORDER_ROLE} does not exist")
    violations = [
        label
        for label, value in (
            ("LOGIN", row["rolcanlogin"]),
            ("INHERIT", row["rolinherit"]),
            ("SUPERUSER", row["rolsuper"]),
            ("CREATEDB", row["rolcreatedb"]),
            ("CREATEROLE", row["rolcreaterole"]),
            ("REPLICATION", row["rolreplication"]),
            ("BYPASSRLS", row["rolbypassrls"]),
            ("PASSWORD", row["has_password"]),
            ("VALID UNTIL", row["has_validity"]),
        )
        if value
    ]
    if int(row["rolconnlimit"]) != -1:
        violations.append("CONNECTION LIMIT")
    oid = int(row["oid"])
    dependencies = int(bind.scalar(_DIRECT_DEPENDENCIES, {"oid": oid}) or 0)
    memberships = int(bind.scalar(_MEMBERSHIPS, {"oid": oid}) or 0)
    settings = int(bind.scalar(_ROLE_SETTINGS, {"oid": oid}) or 0)
    if violations or dependencies or memberships or settings:
        raise RuntimeError(
            f"{RECORDER_ROLE} must still be the exact inert, dependency-free identity 0008 owns "
            f"before it is granted authority (attribute violations={violations}, "
            f"direct_dependencies={dependencies}, memberships={memberships}, "
            f"settings={settings}); refusing to normalise it"
        )


def upgrade() -> None:
    _require_inert_recorder()
    op.create_unique_constraint(
        "uq_decision_records_identity",
        "decision_records",
        ["tenant_id", "engagement_id", "decision_id"],
    )
    op.add_column("agent_events", sa.Column("policy_decision_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_agent_events_policy_decision",
        "agent_events",
        "decision_records",
        ["tenant_id", "engagement_id", "policy_decision_id"],
        ["tenant_id", "engagement_id", "decision_id"],
        ondelete="RESTRICT",
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_agent_events_policy_decision ON agent_events "
            "(tenant_id, engagement_id, policy_decision_id) WHERE policy_decision_id IS NOT NULL"
        )
    )
    op.create_check_constraint(
        "ck_agent_events_policy_decision_lineage", "agent_events", _LINEAGE_CHECK
    )
    op.execute(sa.text(_VALIDATE_FUNCTION))
    op.execute(
        sa.text(
            f"CREATE TRIGGER {LINEAGE_TRIGGER} BEFORE INSERT ON agent_events "
            f"FOR EACH ROW EXECUTE FUNCTION {LINEAGE_FUNCTION}()"
        )
    )
    for statement in _GRANTS:
        op.execute(sa.text(statement))


def _refuse_downgrade_with_records() -> None:
    bind = op.get_bind()
    total = bind.scalar(
        sa.text(
            "SELECT (SELECT count(*) FROM action_proposals) "
            "+ (SELECT count(*) FROM decision_records) "
            "+ (SELECT count(*) FROM agent_events WHERE schema_name = :schema)"
        ),
        {"schema": POLICY_EVENT_SCHEMA},
    )
    if int(total or 0) > 0:
        raise RuntimeError(
            "refusing to downgrade 0009 while action proposals, decision records, or policy "
            "decision events exist; the recorder authority is still in use"
        )


def downgrade() -> None:
    _refuse_downgrade_with_records()
    op.execute(sa.text(f"DROP TRIGGER {LINEAGE_TRIGGER} ON agent_events"))
    op.execute(sa.text(f"DROP FUNCTION {LINEAGE_FUNCTION}()"))
    op.drop_constraint("ck_agent_events_policy_decision_lineage", "agent_events")
    op.execute(sa.text("DROP INDEX uq_agent_events_policy_decision"))
    op.drop_constraint("fk_agent_events_policy_decision", "agent_events", type_="foreignkey")
    op.drop_column("agent_events", "policy_decision_id")
    op.drop_constraint("uq_decision_records_identity", "decision_records", type_="unique")
    for statement in _REVOKES:
        op.execute(sa.text(statement))
