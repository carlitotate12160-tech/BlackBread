"""M1.4c2b0 isolated 0007↔0008 migration lifecycle proofs.

Every test here runs against a private, disposable PostgreSQL database created by the lifecycle
harness — never the shared development or Oracle production database. Split out of
``test_policy_record_authority_migration.py`` by responsibility: that module proves the recorder's
catalog, ACL and role shape; this one proves migration behaviour across the 0007↔0008 boundary.
"""

from __future__ import annotations

import subprocess
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.policy._policy_record_builders import (
    DECISION_COLUMNS,
    decision_row,
    insert_decision,
    insert_proposal,
    proposal_row,
)
from tests.policy.conftest import run_alembic, seed_engagement

pytestmark = pytest.mark.anyio


REV_0007 = "0007_m1_policy_records"
REV_0008 = "0008_m1_policy_record_authority"


async def _alembic_version(engine: AsyncEngine) -> str | None:
    async with engine.begin() as conn:
        return await conn.scalar(text("SELECT version_num FROM alembic_version"))


async def _has_0008_objects(engine: AsyncEngine) -> bool:
    async with engine.begin() as conn:
        present = await conn.scalar(
            text(
                "SELECT (SELECT count(*) FROM pg_trigger "
                "        WHERE tgname = 'agent_events_validate_policy_event') "
                "     + (SELECT count(*) FROM information_schema.columns "
                "        WHERE table_name = 'agent_events' "
                "          AND column_name = 'policy_decision_id')"
            )
        )
    return bool(present)


_APPEND_ONLY = tuple(
    (t, f"{t}_reject_truncate") for t in ("agent_events", "action_proposals", "decision_records")
)

# Every column a c1 (0007) decision carries — the 0008 evaluation_request_digest is absent there.
_DECISION_0007_COLUMNS = tuple(c for c in DECISION_COLUMNS if c != "evaluation_request_digest")


async def _reset_lifecycle(engine: AsyncEngine, db: str) -> None:
    """Bring the shared lifecycle database back to an empty ``base`` from any prior state.

    The 0008 downgrade refuses while policy rows exist (the intended production guarantee), so any
    seeded rows are truncated first; then the full downgrade to base runs cleanly.
    """
    async with engine.begin() as conn:
        present = await conn.scalar(text("SELECT to_regclass('public.action_proposals')"))
        if present:
            for table, trigger in _APPEND_ONLY:
                await conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))
            await conn.execute(
                text("TRUNCATE agent_events, decision_records, action_proposals CASCADE")
            )
            for table, trigger in _APPEND_ONLY:
                await conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}"))
    run_alembic(db, "downgrade", "base")


async def _insert_decision_0007(engine: AsyncEngine, tenant: str, decision: dict) -> None:
    """Insert a decision using only the columns a 0007 schema defines."""
    columns = ", ".join(_DECISION_0007_COLUMNS)
    binds = ", ".join(f":{c}" for c in _DECISION_0007_COLUMNS)
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
        )
        await conn.execute(
            text(f"INSERT INTO decision_records ({columns}) VALUES ({binds})"),  # noqa: S608
            {c: decision[c] for c in _DECISION_0007_COLUMNS},
        )


async def _seed_proposal(engine: AsyncEngine, tenant: str) -> dict:
    """Commit one proposal at the current revision and return its coherent (unsaved) decision."""
    engagement = uuid.uuid4()
    proposal = proposal_row(tenant_id=tenant, engagement_id=engagement, proposal_id=uuid.uuid4())
    await seed_engagement(engine, tenant, engagement)
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
        )
        await insert_proposal(conn, proposal)
    return decision_row(proposal, tenant_id=tenant, engagement_id=engagement)


@pytest.mark.parametrize("seed_decision", [False, True], ids=["proposal-only", "with-decision"])
async def test_upgrade_refused_when_policy_rows_exist(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine, seed_decision: bool
) -> None:
    """0008 refuses to upgrade while any proposal (or proposal+decision) row survives at 0007."""
    await _reset_lifecycle(lifecycle_admin_engine, lifecycle_db)
    run_alembic(lifecycle_db, "upgrade", REV_0007)
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    decision = await _seed_proposal(lifecycle_admin_engine, tenant)
    if seed_decision:
        await _insert_decision_0007(lifecycle_admin_engine, tenant, decision)
    with pytest.raises(subprocess.CalledProcessError):
        run_alembic(lifecycle_db, "upgrade", REV_0008)
    assert await _alembic_version(lifecycle_admin_engine) == REV_0007
    assert await _has_0008_objects(lifecycle_admin_engine) is False


async def test_downgrade_refused_when_policy_state_exists(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    await _reset_lifecycle(lifecycle_admin_engine, lifecycle_db)
    run_alembic(lifecycle_db, "upgrade", REV_0008)
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    decision = await _seed_proposal(lifecycle_admin_engine, tenant)
    async with lifecycle_admin_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
        )
        await insert_decision(conn, decision)
    with pytest.raises(subprocess.CalledProcessError):
        run_alembic(lifecycle_db, "downgrade", REV_0007)
    assert await _alembic_version(lifecycle_admin_engine) == REV_0008
    assert await _has_0008_objects(lifecycle_admin_engine) is True


async def test_empty_0007_0008_0007_round_trip_preserves_unrelated_data(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    await _reset_lifecycle(lifecycle_admin_engine, lifecycle_db)
    run_alembic(lifecycle_db, "upgrade", REV_0007)
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    engagement = uuid.uuid4()
    await seed_engagement(lifecycle_admin_engine, tenant, engagement)

    run_alembic(lifecycle_db, "upgrade", REV_0008)
    assert await _has_0008_objects(lifecycle_admin_engine) is True
    run_alembic(lifecycle_db, "downgrade", REV_0007)
    assert await _has_0008_objects(lifecycle_admin_engine) is False

    async with lifecycle_admin_engine.begin() as conn:
        surviving = await conn.scalar(
            text("SELECT count(*) FROM engagements WHERE tenant_id = :t"), {"t": tenant}
        )
    assert surviving == 1


@pytest.mark.parametrize(
    "setup_sql, teardown_sql",
    [
        # Ordinary table grant in public.
        (
            ("GRANT SELECT ON clients TO blackbread_policy_recorder",),
            ("REVOKE SELECT ON clients FROM blackbread_policy_recorder",),
        ),
        # Column-level grant: invisible to has_table_privilege.
        (
            ("GRANT UPDATE (status) ON engagements TO blackbread_policy_recorder",),
            ("REVOKE UPDATE (status) ON engagements FROM blackbread_policy_recorder",),
        ),
        # View in public.
        (
            (
                "CREATE VIEW probe_view AS SELECT 1 AS x",
                "GRANT SELECT ON probe_view TO blackbread_policy_recorder",
            ),
            ("DROP VIEW IF EXISTS probe_view CASCADE",),
        ),
        # Sequence: relkind 'S', outside any table-only enumeration.
        (
            (
                "CREATE SEQUENCE probe_seq",
                "GRANT SELECT ON SEQUENCE probe_seq TO blackbread_policy_recorder",
            ),
            ("DROP SEQUENCE IF EXISTS probe_seq CASCADE",),
        ),
        # Table living outside schema public.
        (
            (
                "CREATE SCHEMA probe_ns",
                "CREATE TABLE probe_ns.probe_tbl (id int)",
                "GRANT SELECT ON probe_ns.probe_tbl TO blackbread_policy_recorder",
            ),
            ("DROP SCHEMA IF EXISTS probe_ns CASCADE",),
        ),
        # USAGE on a schema other than public.
        (
            (
                "CREATE SCHEMA probe_ns2",
                "GRANT USAGE ON SCHEMA probe_ns2 TO blackbread_policy_recorder",
            ),
            ("DROP SCHEMA IF EXISTS probe_ns2 CASCADE",),
        ),
        # PUBLIC USAGE on a non-system, non-public schema. Only PUBLIC USAGE on schema `public`
        # is an accepted PostgreSQL baseline; anywhere else it is an unexpected grant.
        (
            (
                "CREATE SCHEMA probe_ns3",
                "GRANT USAGE ON SCHEMA probe_ns3 TO PUBLIC",
            ),
            ("DROP SCHEMA IF EXISTS probe_ns3 CASCADE",),
        ),
        # PUBLIC CREATE on a non-system, non-public schema.
        (
            (
                "CREATE SCHEMA probe_ns4",
                "GRANT CREATE ON SCHEMA probe_ns4 TO PUBLIC",
            ),
            ("DROP SCHEMA IF EXISTS probe_ns4 CASCADE",),
        ),
        # A directly-invocable SECURITY DEFINER routine with proacl IS NULL, whose *effective*
        # privilege is the PostgreSQL default of EXECUTE to PUBLIC. aclexplode(NULL) yields no
        # rows, so an ACL-only sweep sees nothing; the effective default must be evaluated.
        (
            (
                "CREATE FUNCTION probe_secdef() RETURNS int LANGUAGE sql SECURITY DEFINER "
                "AS $fn$ SELECT 1 $fn$",
            ),
            ("DROP FUNCTION IF EXISTS probe_secdef()",),
        ),
    ],
    ids=[
        "table",
        "column",
        "view",
        "sequence",
        "other-schema-table",
        "other-schema-usage",
        "public-usage-other-schema",
        "public-create-other-schema",
        "secdef-routine-null-acl",
    ],
)
async def test_upgrade_refused_when_recorder_holds_unexpected_privilege(
    lifecycle_db: str,
    lifecycle_admin_engine: AsyncEngine,
    setup_sql: tuple[str, ...],
    teardown_sql: tuple[str, ...],
) -> None:
    """A pre-existing recorder carrying ANY unauthorized grant aborts the upgrade fail-closed.

    The audit must not be scoped to ordinary tables in schema ``public``: a view, sequence,
    out-of-schema table, or schema-level USAGE grant is equally unauthorized and equally invisible
    to a table-only enumeration. Grants are database-scoped, so they never leak past this
    disposable database, and the migration must abort without rewriting the cluster role.
    """
    await _reset_lifecycle(lifecycle_admin_engine, lifecycle_db)
    run_alembic(lifecycle_db, "upgrade", REV_0007)
    async with lifecycle_admin_engine.begin() as conn:
        for statement in setup_sql:
            await conn.execute(text(statement))
    try:
        with pytest.raises(subprocess.CalledProcessError):
            run_alembic(lifecycle_db, "upgrade", REV_0008)
        assert await _alembic_version(lifecycle_admin_engine) == REV_0007
        assert await _has_0008_objects(lifecycle_admin_engine) is False
        async with lifecycle_admin_engine.begin() as conn:
            flags = (
                await conn.execute(
                    text(
                        "SELECT rolcanlogin, rolsuper FROM pg_roles "
                        "WHERE rolname = 'blackbread_policy_recorder'"
                    )
                )
            ).one()
        assert flags == (False, False)  # migration aborted; role attributes untouched
    finally:
        async with lifecycle_admin_engine.begin() as conn:
            for statement in teardown_sql:
                await conn.execute(text(statement))
