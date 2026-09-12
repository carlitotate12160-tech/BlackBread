"""M1.4c2b1 recorder-owned evaluate-and-record routine, INSERT authority, and b1 uniqueness.

Expands the reserved ``blackbread_policy_recorder`` role from the SELECT/INSERT-only 0009 baseline to
the exact authority the first production evaluate-and-record transaction needs: additional ``INSERT``
on ``action_proposals`` and ``decision_records`` (still no UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER),
one database-uniqueness guarantee of at most one decision per ``(tenant_id, engagement_id,
proposal_id)``, and exactly one runtime-reachable ``SECURITY DEFINER`` routine
``public.blackbread_record_policy_decision`` owned by the recorder that inserts the immutable
proposal, decision, and hash-chained ``policy.decision.recorded`` event as one atomic unit.

``blackbread_runtime`` gains no privilege at all in this slice: the M1.4c2b1a substrate ships
dormant, so ``PUBLIC`` EXECUTE is revoked and no ``EXECUTE`` grant is issued to anyone — no login
role can invoke the routine and the store module has no production importer. The runtime activation
grant is M1.4c2b1b scope. The routine takes three strict PostgreSQL composite row types (no dynamic
SQL, no permissive JSON),
validates the transaction-local tenant GUC against all three records and the proposal/decision/event
correspondence, refuses a caller-supplied ``policy_decision_id``, and relies on the existing 0009
``SECURITY INVOKER`` trigger for exact payload/event lineage and for deriving ``policy_decision_id``
from ``causation_id``. Owner identity is load-bearing: only the recorder may author the reserved
event, so the routine must be owned by the recorder. An ``ALLOW`` row remains a Policy outcome only.
"""

# ruff: noqa: S608 -- every SQL string here interpolates only module-constant identifiers
# (role, schema, function, column names), never caller input; this is static migration DDL.
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_m1_policy_record_txn"
down_revision: str | None = "0009_m1_policy_record_authority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECORDER_ROLE = "blackbread_policy_recorder"
RUNTIME_ROLE = "blackbread_runtime"
ROUTINE = "blackbread_record_policy_decision"
ROUTINE_SIGNATURE = (
    f"public.{ROUTINE}(public.action_proposals, public.decision_records, public.agent_events)"
)
DECISION_PROPOSAL_UNIQUE = "uq_decision_records_proposal"

# The exact revision-0009 recorder grant set (table_name, privilege) this migration expands from.
_EXPECTED_0009_GRANTS = frozenset(
    {
        ("action_proposals", "SELECT"),
        ("decision_records", "SELECT"),
        ("agent_events", "INSERT"),
    }
)

# The additional b1 authority: INSERT (only) on the two record tables. Defence-in-depth REVOKEs of
# every other DML run first so the SELECT/INSERT-only guarantee holds even against a stray grant.
INSERT_GRANTS: tuple[str, ...] = (
    f"REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
    f"ON TABLE action_proposals, decision_records FROM {RECORDER_ROLE}",
    f"GRANT INSERT ON TABLE action_proposals, decision_records TO {RECORDER_ROLE}",
)
INSERT_REVOKES: tuple[str, ...] = (
    f"REVOKE INSERT ON TABLE action_proposals, decision_records FROM {RECORDER_ROLE}",
)

# The recorder-owned routine. It inserts proposal, decision, then event in that order, leaves
# ``policy_decision_id`` for the 0009 trigger to derive, and returns the inserted event id. The
# 0009 SECURITY INVOKER trigger (running as the recorder inside this SECURITY DEFINER routine) owns
# the exact payload/event-lineage validation; this routine owns tenant-GUC and structural
# correspondence and the reserved-lineage refusal.
CREATE_ROUTINE = f"""
CREATE FUNCTION public.{ROUTINE}(
    p public.action_proposals,
    d public.decision_records,
    e public.agent_events
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    tenant_guc text := current_setting('blackbread.tenant_id', true);
BEGIN
    -- The lineage column is database-derived; a caller may not supply its own value.
    IF e.policy_decision_id IS NOT NULL THEN
        RAISE EXCEPTION 'policy_decision_id is database-derived and must not be supplied'
            USING ERRCODE = '23514';
    END IF;

    -- Transaction-local tenant context must match all three records (belt-and-suspenders with RLS).
    IF tenant_guc IS DISTINCT FROM p.tenant_id
       OR tenant_guc IS DISTINCT FROM d.tenant_id
       OR tenant_guc IS DISTINCT FROM e.tenant_id THEN
        RAISE EXCEPTION 'tenant context does not match the recorded policy decision triple'
            USING ERRCODE = '42501';
    END IF;

    -- Proposal/decision/event correspondence: one engagement, one proposal, one decision.
    IF p.engagement_id IS DISTINCT FROM d.engagement_id
       OR p.engagement_id IS DISTINCT FROM e.engagement_id
       OR d.proposal_id IS DISTINCT FROM p.proposal_id
       OR d.proposal_digest IS DISTINCT FROM p.proposal_digest
       OR e.correlation_id IS DISTINCT FROM p.proposal_id
       OR e.causation_id IS DISTINCT FROM d.decision_id THEN
        RAISE EXCEPTION 'policy decision triple lineage is not self-consistent'
            USING ERRCODE = '23514';
    END IF;

    INSERT INTO public.action_proposals (
        schema_name, schema_version, proposal_id, tenant_id, engagement_id, agent_instance_id,
        agent_role, capability_id, target_kind, target_value, input_schema_ref, parameters,
        intended_proof, precondition_refs, oracle_ref, risk, cost, information_gain, opsec_noise,
        target_requests, deadline_seconds, target_identity_tier, graph_state_root_version,
        graph_projector_version, graph_state_root, graph_ledger_event_count,
        graph_ledger_head_hash, idempotency_key, created_at, expires_at, proposal_digest
    ) VALUES (
        p.schema_name, p.schema_version, p.proposal_id, p.tenant_id, p.engagement_id,
        p.agent_instance_id, p.agent_role, p.capability_id, p.target_kind, p.target_value,
        p.input_schema_ref, p.parameters, p.intended_proof, p.precondition_refs, p.oracle_ref,
        p.risk, p.cost, p.information_gain, p.opsec_noise, p.target_requests, p.deadline_seconds,
        p.target_identity_tier, p.graph_state_root_version, p.graph_projector_version,
        p.graph_state_root, p.graph_ledger_event_count, p.graph_ledger_head_hash,
        p.idempotency_key, p.created_at, p.expires_at, p.proposal_digest
    );

    INSERT INTO public.decision_records (
        schema_name, schema_version, decision_id, tenant_id, engagement_id, proposal_id,
        proposal_digest, decision_authority, outcome, reason_code, decided_at,
        graph_state_root_version, graph_projector_version, graph_state_root,
        graph_ledger_event_count, graph_ledger_head_hash, runtime_gate_result_digest,
        decision_digest
    ) VALUES (
        d.schema_name, d.schema_version, d.decision_id, d.tenant_id, d.engagement_id, d.proposal_id,
        d.proposal_digest, d.decision_authority, d.outcome, d.reason_code, d.decided_at,
        d.graph_state_root_version, d.graph_projector_version, d.graph_state_root,
        d.graph_ledger_event_count, d.graph_ledger_head_hash, d.runtime_gate_result_digest,
        d.decision_digest
    );

    -- Explicit columns; ``policy_decision_id`` is left database-derived by the 0009 trigger. No
    -- RETURNING clause: the recorder holds INSERT but deliberately no SELECT on agent_events, and
    -- RETURNING would require SELECT. The inserted id is exactly the caller-materialized ``e.id``.
    INSERT INTO public.agent_events (
        id, engagement_id, tenant_id, sequence, schema_name, schema_version, producer,
        correlation_id, causation_id, occurred_at, recorded_at, payload, payload_hash,
        prev_event_hash, event_hash, hash_algorithm, hash_version, sensitivity, redaction_refs
    ) VALUES (
        e.id, e.engagement_id, e.tenant_id, e.sequence, e.schema_name, e.schema_version, e.producer,
        e.correlation_id, e.causation_id, e.occurred_at, e.recorded_at, e.payload, e.payload_hash,
        e.prev_event_hash, e.event_hash, e.hash_algorithm, e.hash_version, e.sensitivity,
        e.redaction_refs
    );

    RETURN e.id;
END;
$$
"""

DROP_ROUTINE = f"DROP FUNCTION IF EXISTS {ROUTINE_SIGNATURE}"
OWN_ROUTINE = f"ALTER FUNCTION {ROUTINE_SIGNATURE} OWNER TO {RECORDER_ROLE}"
# Dormant privilege shape: strip the default PUBLIC EXECUTE and defence-in-depth revoke the
# runtime role's EXECUTE so a stray ALTER DEFAULT PRIVILEGES cannot silently activate the routine.
# No GRANT is issued: only the recorder owner (a NOLOGIN role) may execute until M1.4c2b1b grants
# the activation identity.
ROUTINE_PRIVILEGE_STATEMENTS: tuple[str, ...] = (
    f"REVOKE ALL ON FUNCTION {ROUTINE_SIGNATURE} FROM PUBLIC",
    f"REVOKE EXECUTE ON FUNCTION {ROUTINE_SIGNATURE} FROM {RUNTIME_ROLE}",
)

_ROLE_ATTRIBUTES = sa.text(
    "SELECT oid, rolcanlogin, rolinherit, rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
    "rolbypassrls, (rolpassword IS NOT NULL) AS has_password FROM pg_authid WHERE rolname = :name"
)
_MEMBERSHIPS = sa.text(
    "SELECT count(*) FROM pg_auth_members WHERE roleid = :oid OR member = :oid OR grantor = :oid"
)
_ROLE_SETTINGS = sa.text("SELECT count(*) FROM pg_db_role_setting WHERE setrole = :oid")
_GRANT_SET = sa.text(
    "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
    "WHERE grantee = :r AND table_schema = 'public' "
    "UNION "
    "SELECT table_name, privilege_type FROM information_schema.column_privileges "
    "WHERE grantee = :r AND table_schema = 'public'"
)


def _attribute_violations(row: sa.engine.RowMapping) -> list[str]:
    return [
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
        )
        if value
    ]


def _require_revision_0009_baseline() -> None:
    """Fail closed unless the recorder still holds exactly its inert 0009 shape and grant set.

    Expanding authority on a role that drifted out-of-band (a login, an inheritance, a membership, a
    role setting, or an unexpected grant) would silently extend the reserved writer past the reviewed
    0009 contract, so this refuses to build the routine on anything but the exact expected baseline.
    """
    bind = op.get_bind()
    row = bind.execute(_ROLE_ATTRIBUTES, {"name": RECORDER_ROLE}).mappings().one_or_none()
    if row is None:
        raise RuntimeError(f"required recorder role {RECORDER_ROLE} does not exist")
    violations = _attribute_violations(row)
    oid = int(row["oid"])
    memberships = int(bind.scalar(_MEMBERSHIPS, {"oid": oid}) or 0)
    settings = int(bind.scalar(_ROLE_SETTINGS, {"oid": oid}) or 0)
    grants = {
        (str(record[0]), str(record[1]))
        for record in bind.execute(_GRANT_SET, {"r": RECORDER_ROLE}).all()
    }
    if violations or memberships or settings or grants != set(_EXPECTED_0009_GRANTS):
        raise RuntimeError(
            f"{RECORDER_ROLE} must still be the exact inert revision-0009 identity before b1 "
            f"expands its authority (attribute violations={violations}, memberships={memberships}, "
            f"settings={settings}, grants={sorted(grants)}); refusing to normalise it"
        )


def upgrade() -> None:
    _require_revision_0009_baseline()
    op.create_unique_constraint(
        DECISION_PROPOSAL_UNIQUE,
        "decision_records",
        ["tenant_id", "engagement_id", "proposal_id"],
    )
    for statement in INSERT_GRANTS:
        op.execute(sa.text(statement))
    op.execute(sa.text(CREATE_ROUTINE))
    op.execute(sa.text(OWN_ROUTINE))
    for statement in ROUTINE_PRIVILEGE_STATEMENTS:
        op.execute(sa.text(statement))


def downgrade() -> None:
    op.execute(sa.text(DROP_ROUTINE))
    for statement in INSERT_REVOKES:
        op.execute(sa.text(statement))
    op.drop_constraint(DECISION_PROPOSAL_UNIQUE, "decision_records", type_="unique")
