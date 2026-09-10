"""Migration 0007 lifecycle: 0006 -> 0007 -> 0006 -> 0007 on an isolated disposable database.

Runs only against a private throwaway database created by the lifecycle harness; it never touches
the shared development or Oracle production database. Proves the upgrade creates the M1.4c1 objects,
the downgrade removes only those objects, and representative <=0006 ledger behavior survives the
round trip.

Pinned to REV_0007 (not head) so this suite does not silently absorb c2b0 responsibilities.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.policy.conftest import run_alembic, seed_engagement, seed_ledger_event

BASE = "base"
REV_0006 = "0006_m1_temporal_scope_graph"
REV_0007 = "0007_m1_policy_records"
NEW_TABLES = ("action_proposals", "decision_records")


async def _table_exists(admin: AsyncEngine, table: str) -> bool:
    async with admin.begin() as conn:
        value = await conn.scalar(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"})
    return value is not None


async def _function_exists(admin: AsyncEngine, name: str) -> bool:
    async with admin.begin() as conn:
        return bool(
            await conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = :n)"), {"n": name}
            )
        )


async def _ledger_count(admin: AsyncEngine, tenant: str) -> int:
    async with admin.begin() as conn:
        value = await conn.scalar(
            text("SELECT count(*) FROM agent_events WHERE tenant_id = :t"), {"t": tenant}
        )
    return int(value or 0)


async def _seed_representative_0006(admin: AsyncEngine) -> str:
    """Seed one engagement and one ledger event, exercising the <=0006 advance trigger."""
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    engagement_id = uuid.uuid4()
    await seed_engagement(admin, tenant, engagement_id)
    await seed_ledger_event(admin, tenant, engagement_id)
    return tenant


async def test_full_lifecycle_preserves_0006_behavior(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    run_alembic(lifecycle_db, "downgrade", BASE)
    run_alembic(lifecycle_db, "upgrade", REV_0006)

    tenant = await _seed_representative_0006(lifecycle_admin_engine)
    assert await _ledger_count(lifecycle_admin_engine, tenant) == 1
    for table in NEW_TABLES:
        assert not await _table_exists(lifecycle_admin_engine, table)

    # 0006 -> 0007
    run_alembic(lifecycle_db, "upgrade", REV_0007)
    for table in NEW_TABLES:
        assert await _table_exists(lifecycle_admin_engine, table)
    assert await _function_exists(
        lifecycle_admin_engine, "blackbread_reject_policy_record_mutation"
    )
    assert await _ledger_count(lifecycle_admin_engine, tenant) == 1
    # <=0006 behavior still works after the upgrade.
    tenant_after_upgrade = await _seed_representative_0006(lifecycle_admin_engine)
    assert await _ledger_count(lifecycle_admin_engine, tenant_after_upgrade) == 1

    # 0007 -> 0006 removes only M1.4c1-owned objects.
    run_alembic(lifecycle_db, "downgrade", REV_0006)
    for table in NEW_TABLES:
        assert not await _table_exists(lifecycle_admin_engine, table)
    assert not await _function_exists(
        lifecycle_admin_engine, "blackbread_reject_policy_record_mutation"
    )
    # 0006-owned tables and the seeded ledger rows survive; the advance trigger still works.
    assert await _table_exists(lifecycle_admin_engine, "graph_temporal_scope_roots")
    assert await _ledger_count(lifecycle_admin_engine, tenant) == 1
    tenant_after_downgrade = await _seed_representative_0006(lifecycle_admin_engine)
    assert await _ledger_count(lifecycle_admin_engine, tenant_after_downgrade) == 1

    # 0006 -> 0007 again.
    run_alembic(lifecycle_db, "upgrade", REV_0007)
    for table in NEW_TABLES:
        assert await _table_exists(lifecycle_admin_engine, table)


async def test_upgrade_installs_rls_triggers_privileges_and_lineage(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    run_alembic(lifecycle_db, "downgrade", BASE)
    run_alembic(lifecycle_db, "upgrade", REV_0007)

    async with lifecycle_admin_engine.begin() as conn:
        for table in NEW_TABLES:
            forced = await conn.scalar(
                text("SELECT relforcerowsecurity FROM pg_class WHERE relname = :t"), {"t": table}
            )
            assert forced is True, table
            policies = await conn.scalar(
                text("SELECT count(*) FROM pg_policies WHERE tablename = :t"), {"t": table}
            )
            assert int(policies or 0) == 1, table
            triggers = await conn.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = to_regclass(:t) "
                    "AND NOT tgisinternal"
                ),
                {"t": f"public.{table}"},
            )
            assert int(triggers or 0) == 2, table
            assert (
                await conn.scalar(
                    text("SELECT has_table_privilege('blackbread_runtime', :t, 'SELECT')"),
                    {"t": table},
                )
                is True
            )
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert (
                    await conn.scalar(
                        text("SELECT has_table_privilege('blackbread_runtime', :t, :p)"),
                        {"t": table, "p": privilege},
                    )
                    is False
                ), f"{table}:{privilege}"

        # The exact composite decision-to-proposal lineage foreign key exists.
        lineage_fk = await conn.scalar(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conname = 'fk_decision_records_proposal_lineage' AND contype = 'f'"
            )
        )
        assert int(lineage_fk or 0) == 1


# ALTER DEFAULT PRIVILEGES on schema public granting DML to the runtime role, applied AS the same
# (admin) role that runs Alembic, so tables the 0007 migration creates would inherit those grants
# unless the migration explicitly revokes them. Confined to the disposable lifecycle database.
_GRANT_DEFAULTS = (
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
    "GRANT INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO blackbread_runtime"
)
_REVOKE_DEFAULTS = (
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
    "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLES FROM blackbread_runtime"
)


async def test_upgrade_strips_default_privilege_dml_from_runtime(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    """Regression: even when default privileges would grant the runtime role DML on new tables,
    the 0007 migration must leave blackbread_runtime with SELECT only. Fails on the pre-correction
    head (no REVOKE ... FROM blackbread_runtime); passes after the correction."""
    run_alembic(lifecycle_db, "downgrade", BASE)
    run_alembic(lifecycle_db, "upgrade", REV_0006)

    async with lifecycle_admin_engine.begin() as conn:
        await conn.execute(text(_GRANT_DEFAULTS))
    try:
        run_alembic(lifecycle_db, "upgrade", REV_0007)
        async with lifecycle_admin_engine.begin() as conn:
            for table in NEW_TABLES:
                has_select = await conn.scalar(
                    text("SELECT has_table_privilege('blackbread_runtime', :t, 'SELECT')"),
                    {"t": table},
                )
                assert has_select is True, table
                for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    leaked = await conn.scalar(
                        text("SELECT has_table_privilege('blackbread_runtime', :t, :p)"),
                        {"t": table, "p": privilege},
                    )
                    assert leaked is False, f"{table}:{privilege} leaked to runtime via defaults"
    finally:
        # Reset the default privileges so the shared module-scoped lifecycle DB stays clean for
        # sibling tests (ALTER DEFAULT PRIVILEGES is database-scoped, surviving downgrade/upgrade).
        async with lifecycle_admin_engine.begin() as conn:
            await conn.execute(text(_REVOKE_DEFAULTS))
