"""M1.4c2b0b exact-grant, RLS, and schema-object proofs for migration 0009 at head.

Observes the objects and privileges that ``alembic upgrade head`` (revision
``0009_m1_policy_record_authority``) leaves on the shared migrated test database. Proves the
recorder holds only the minimal SELECT/INSERT authority the future b1 transaction needs and no
write authority over the append-only record substrate, that PUBLIC and the runtime cannot use it
by privilege, that forced RLS is preserved, and that the lineage column, FK, partial-unique index,
CHECK, and ``SECURITY INVOKER`` validation trigger exist in the exact shape the contract requires.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.policy._policy_record_authority_support import (
    LINEAGE_FUNCTION,
    LINEAGE_TRIGGER,
    RECORDER_ROLE,
    RUNTIME_ROLE,
    table_privilege,
)

LINEAGE_FUNCTION_NAME = LINEAGE_FUNCTION
RLS_TABLES = ("agent_events", "action_proposals", "decision_records")


async def _scalar(engine: AsyncEngine, sql: str, **params: object) -> object:
    async with engine.connect() as conn:
        return await conn.scalar(text(sql), params)


async def test_recorder_holds_select_on_records_and_insert_on_events(
    policy_admin_engine: AsyncEngine,
) -> None:
    assert await table_privilege(policy_admin_engine, RECORDER_ROLE, "action_proposals", "SELECT")
    assert await table_privilege(policy_admin_engine, RECORDER_ROLE, "decision_records", "SELECT")
    assert await table_privilege(policy_admin_engine, RECORDER_ROLE, "agent_events", "INSERT")
    usage = await _scalar(
        policy_admin_engine,
        "SELECT has_schema_privilege(:r, 'public', 'USAGE')",
        r=RECORDER_ROLE,
    )
    assert usage is True


async def test_recorder_has_no_write_authority_over_records(
    policy_admin_engine: AsyncEngine,
) -> None:
    for table in ("action_proposals", "decision_records"):
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            granted = await table_privilege(policy_admin_engine, RECORDER_ROLE, table, privilege)
            assert granted is False, f"recorder must not hold {privilege} on {table}"
    # The reserved writer may append events but never read, update, delete, or truncate the ledger.
    for privilege in ("SELECT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        granted = await table_privilege(
            policy_admin_engine, RECORDER_ROLE, "agent_events", privilege
        )
        assert granted is False, f"recorder must not hold {privilege} on agent_events"


async def test_recorder_authority_is_minimal_across_other_tables(
    policy_admin_engine: AsyncEngine,
) -> None:
    # Enumerate the complete effective grant set rather than probing a few tables: the recorder's
    # table- and column-level privileges in schema public must be exactly the reviewed minimum.
    async with policy_admin_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee = :r AND table_schema = 'public' "
                    "UNION ALL "
                    "SELECT table_name, privilege_type FROM information_schema.column_privileges "
                    "WHERE grantee = :r AND table_schema = 'public'"
                ),
                {"r": RECORDER_ROLE},
            )
        ).all()
    granted = {(str(row[0]), str(row[1])) for row in rows}
    assert granted == {
        ("action_proposals", "SELECT"),
        ("decision_records", "SELECT"),
        ("agent_events", "INSERT"),
    }, f"recorder privileges must be exactly the minimal set, got {sorted(granted)}"
    create = await _scalar(
        policy_admin_engine,
        "SELECT has_schema_privilege(:r, 'public', 'CREATE')",
        r=RECORDER_ROLE,
    )
    assert create is False, "recorder must not be able to create objects in schema public"


async def test_public_and_runtime_cannot_touch_records_by_privilege(
    policy_admin_engine: AsyncEngine,
) -> None:
    for table in ("action_proposals", "decision_records"):
        for role in ("public", RUNTIME_ROLE):
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                granted = await table_privilege(policy_admin_engine, role, table, privilege)
                assert granted is False, f"{role} must not hold {privilege} on {table}"
    # The ordinary runtime keeps its pre-existing non-policy append authority.
    assert await table_privilege(policy_admin_engine, RUNTIME_ROLE, "agent_events", "INSERT")
    assert await table_privilege(policy_admin_engine, RUNTIME_ROLE, "agent_events", "SELECT")


async def test_forced_row_level_security_is_preserved(policy_admin_engine: AsyncEngine) -> None:
    async with policy_admin_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = ANY(:tables)"
                ),
                {"tables": list(RLS_TABLES)},
            )
        ).mappings()
        state = {row["relname"]: row for row in rows}
    for table in RLS_TABLES:
        assert state[table]["relrowsecurity"] is True, f"{table} RLS disabled"
        assert state[table]["relforcerowsecurity"] is True, f"{table} RLS not forced"


async def test_recorder_role_shape_unchanged_at_authority_head(
    policy_admin_engine: AsyncEngine,
) -> None:
    async with policy_admin_engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT rolcanlogin, rolinherit, rolbypassrls, rolsuper, "
                        "(rolpassword IS NULL) AS pw_null FROM pg_authid WHERE rolname = :n"
                    ),
                    {"n": RECORDER_ROLE},
                )
            )
            .mappings()
            .one()
        )
    assert row["rolcanlogin"] is False
    assert row["rolinherit"] is False
    assert row["rolbypassrls"] is False
    assert row["rolsuper"] is False
    assert row["pw_null"] is True


async def test_decision_identity_unique_and_event_lineage_column(
    policy_admin_engine: AsyncEngine,
) -> None:
    unique = await _scalar(
        policy_admin_engine,
        "SELECT contype::text FROM pg_constraint WHERE conname = 'uq_decision_records_identity'",
    )
    assert unique == "u"
    column = await _scalar(
        policy_admin_engine,
        "SELECT data_type || ':' || is_nullable FROM information_schema.columns "
        "WHERE table_name = 'agent_events' AND column_name = 'policy_decision_id'",
    )
    assert column == "uuid:YES"


async def test_lineage_fk_and_partial_unique_index_shape(
    policy_admin_engine: AsyncEngine,
) -> None:
    fk = await _scalar(
        policy_admin_engine,
        "SELECT confrelid::regclass::text FROM pg_constraint "
        "WHERE conname = 'fk_agent_events_policy_decision' AND contype = 'f' "
        "AND conrelid = 'agent_events'::regclass",
    )
    assert fk == "decision_records"
    fkdef = await _scalar(
        policy_admin_engine,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname = 'fk_agent_events_policy_decision'",
    )
    assert isinstance(fkdef, str)
    assert "FOREIGN KEY (tenant_id, engagement_id, policy_decision_id)" in fkdef
    assert "REFERENCES decision_records(tenant_id, engagement_id, decision_id)" in fkdef
    index = await _scalar(
        policy_admin_engine,
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_agent_events_policy_decision'",
    )
    assert isinstance(index, str)
    assert "UNIQUE INDEX" in index
    assert "(policy_decision_id IS NOT NULL)" in index


async def test_lineage_check_binds_schema_to_lineage_presence(
    policy_admin_engine: AsyncEngine,
) -> None:
    definition = await _scalar(
        policy_admin_engine,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname = 'ck_agent_events_policy_decision_lineage'",
    )
    assert isinstance(definition, str)
    assert "policy.decision.recorded" in definition
    assert "policy_decision_id IS NOT NULL" in definition
    assert "policy_decision_id IS NULL" in definition


async def test_validation_trigger_is_before_insert_security_invoker(
    policy_admin_engine: AsyncEngine,
) -> None:
    async with policy_admin_engine.connect() as conn:
        trigger = (
            (
                await conn.execute(
                    text(
                        "SELECT t.tgtype, t.tgenabled::text AS tgenabled, p.proname, "
                        "p.prosecdef, p.proconfig FROM pg_trigger t "
                        "JOIN pg_proc p ON p.oid = t.tgfoid "
                        "WHERE t.tgname = :n AND t.tgrelid = 'agent_events'::regclass"
                    ),
                    {"n": LINEAGE_TRIGGER},
                )
            )
            .mappings()
            .one()
        )
    assert trigger["proname"] == LINEAGE_FUNCTION_NAME
    assert trigger["prosecdef"] is False, "validation trigger must be SECURITY INVOKER"
    assert trigger["proconfig"] == ["search_path=pg_catalog, public"]
    # tgtype bit 0 = row-level, bit 1 = BEFORE, bit 2 = INSERT (see pg_trigger).
    assert trigger["tgtype"] & 1, "must be a row-level trigger"
    assert trigger["tgtype"] & 2, "must be a BEFORE trigger"
    assert trigger["tgtype"] & 4, "must fire on INSERT"
    assert trigger["tgenabled"] == "O", "trigger must be enabled in origin/local mode"
