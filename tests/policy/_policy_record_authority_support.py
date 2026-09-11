"""Shared catalog, grant, and lifecycle helpers for the M1.4c2b0b recorder-authority tests.

The ``blackbread_policy_recorder`` role is cluster-global, so the 0009 grants it holds on the shared
migrated test database make it *not* dependency-free everywhere. Revision-0008 identity/lifecycle
proofs (which drop and recreate the role and assert a dependency-free shape) therefore run only
while those shared grants are suspended, and this module owns that suspend/restore. It never mutates
the
shared or Oracle production schema irreversibly: it revokes exactly the 0009 grants and re-applies
them (restoring head) in ``finally``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from tests.conftest import TEST_MIGRATION_DATABASE_URL
from tests.policy.conftest import ROOT

RECORDER_ROLE = "blackbread_policy_recorder"
RUNTIME_ROLE = "blackbread_runtime"
REV_0007 = "0007_m1_policy_records"
REV_0008 = "0008_m1_policy_recorder_identity"
REV_0009 = "0009_m1_policy_record_authority"
TENANT_GUC = "blackbread.tenant_id"
POLICY_EVENT_SCHEMA = "policy.decision.recorded"
LINEAGE_TRIGGER = "agent_events_validate_policy_decision"
LINEAGE_FUNCTION = "blackbread_validate_policy_decision_event"

_CREATE_CLEAN = (
    f"CREATE ROLE {RECORDER_ROLE} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
    "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1 PASSWORD NULL"
)
_APPEND_ONLY_TRIGGERS = (
    ("agent_events", "agent_events_reject_mutation"),
    ("agent_events", "agent_events_reject_truncate"),
    ("action_proposals", "action_proposals_reject_mutation"),
    ("action_proposals", "action_proposals_reject_truncate"),
    ("decision_records", "decision_records_reject_mutation"),
    ("decision_records", "decision_records_reject_truncate"),
)


def _migration_module() -> Any:
    """Import migration 0009 by path so tests reuse its exact grant/revoke statements."""
    path = ROOT / "migrations" / "versions" / "0009_m1_policy_record_authority.py"
    spec = importlib.util.spec_from_file_location("_m0009_authority", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUTHORITY_GRANTS: tuple[str, ...] = _migration_module()._GRANTS
AUTHORITY_REVOKES: tuple[str, ...] = _migration_module()._REVOKES


def _autocommit(url: str = TEST_MIGRATION_DATABASE_URL) -> AsyncEngine:
    return create_async_engine(url, isolation_level="AUTOCOMMIT")


async def run_admin(sql: str | Sequence[str], *, url: str = TEST_MIGRATION_DATABASE_URL) -> None:
    statements = (sql,) if isinstance(sql, str) else tuple(sql)
    engine = _autocommit(url)
    try:
        async with engine.connect() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


async def drop_recorder() -> None:
    await run_admin(f"DROP ROLE IF EXISTS {RECORDER_ROLE}")


async def ensure_clean_recorder() -> None:
    await drop_recorder()
    await run_admin(_CREATE_CLEAN)


async def recorder_present(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
        return bool(
            await conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_authid WHERE rolname = :n)"),
                {"n": RECORDER_ROLE},
            )
        )


async def recorder_oid(engine: AsyncEngine) -> int | None:
    async with engine.connect() as conn:
        return await conn.scalar(
            text("SELECT oid FROM pg_authid WHERE rolname = :n"), {"n": RECORDER_ROLE}
        )


async def alembic_version(engine: AsyncEngine) -> str | None:
    async with engine.connect() as conn:
        return await conn.scalar(text("SELECT version_num FROM alembic_version"))


async def dependency_counts(engine: AsyncEngine) -> tuple[int, int, int]:
    """Cluster-wide (shdepend, membership, role-setting) counts for the recorder role."""
    oid = await recorder_oid(engine)
    assert oid is not None
    async with engine.connect() as conn:
        shdepend = await conn.scalar(
            text(
                "SELECT count(*) FROM pg_shdepend "
                "WHERE refclassid = 'pg_authid'::regclass AND refobjid = :o"
            ),
            {"o": oid},
        )
        members = await conn.scalar(
            text("SELECT count(*) FROM pg_auth_members WHERE roleid=:o OR member=:o OR grantor=:o"),
            {"o": oid},
        )
        settings = await conn.scalar(
            text("SELECT count(*) FROM pg_db_role_setting WHERE setrole = :o"), {"o": oid}
        )
    return int(shdepend or 0), int(members or 0), int(settings or 0)


async def table_privilege(engine: AsyncEngine, role: str, table: str, privilege: str) -> bool:
    async with engine.connect() as conn:
        return bool(
            await conn.scalar(
                text("SELECT has_table_privilege(:r, :t, :p)"),
                {"r": role, "t": table, "p": privilege},
            )
        )


def lifecycle_url(db_name: str) -> str:
    """Return the superuser connection URL for a disposable lifecycle database."""
    return (
        make_url(TEST_MIGRATION_DATABASE_URL)
        .set(database=db_name)
        .render_as_string(hide_password=False)
    )


def alembic_env(db_name: str) -> dict[str, str]:
    env = os.environ.copy()
    env["BLACKBREAD_DATABASE_URL"] = (
        make_url(TEST_MIGRATION_DATABASE_URL)
        .set(database=db_name)
        .render_as_string(hide_password=False)
    )
    return env


def run_alembic_step(db_name: str, direction: str, target: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", direction, target],
        cwd=ROOT,
        env=alembic_env(db_name),
        check=True,
    )


def reset_to(db_name: str, target: str) -> None:
    """Downgrade a disposable database to base then re-upgrade to an exact revision."""
    run_alembic_step(db_name, "downgrade", "base")
    run_alembic_step(db_name, "upgrade", target)


def alembic_expecting_failure(db_name: str, direction: str, target: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", direction, target],
        cwd=ROOT,
        env=alembic_env(db_name),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, f"expected {direction} {target} to fail:\n{result.stdout}"
    return result.stdout + result.stderr


async def truncate_policy_rows(url: str = TEST_MIGRATION_DATABASE_URL) -> None:
    """Empty the append-only policy substrate on ``url`` (disabling the reject triggers first).

    Each ``ALTER TABLE`` commits independently under AUTOCOMMIT, so a disable or TRUNCATE that
    raises must not leave append-only enforcement off: only the triggers that actually disabled are
    re-enabled, in ``finally``.
    """
    engine = _autocommit(url)
    try:
        async with engine.connect() as conn:
            disabled: list[tuple[str, str]] = []
            try:
                for table, trigger in _APPEND_ONLY_TRIGGERS:
                    await conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))
                    disabled.append((table, trigger))
                # CASCADE also clears read-model tables (e.g. graph_projection_snapshots) whose FK
                # references agent_events; those projections are rebuildable and safe to drop here.
                await conn.execute(
                    text("TRUNCATE decision_records, action_proposals, agent_events CASCADE")
                )
            finally:
                for table, trigger in disabled:
                    await conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}"))
    finally:
        await engine.dispose()


async def _restore_shared_head() -> None:
    """Restore the shared recorder to exact 0009 head: clean inert role plus its exact grants."""
    await ensure_clean_recorder()
    await run_admin(AUTHORITY_GRANTS)


@pytest.fixture(scope="module")
def suspend_shared_authority_head(migrated_database: None) -> Iterator[None]:
    """Suspend the shared database's 0009 recorder grants for revision-0008 role proofs.

    Revoking the exact grants makes the cluster-global recorder dependency-free so a 0008-level test
    may drop/recreate it and assert the inert shape. Head is always restored in ``finally`` —
    including when a revoke partially commits under AUTOCOMMIT and then raises, so the shared
    database is never left with the recorder's grants half-suspended. The ``migrated_database``
    dependency forces the shared schema to head first — without it, a run whose random order reaches
    this module first revokes grants on tables that do not exist yet.
    """
    try:
        asyncio.run(run_admin(AUTHORITY_REVOKES))
        yield
    finally:
        asyncio.run(_restore_shared_head())


@pytest.fixture(scope="session", autouse=True)
def clear_policy_rows_before_base_downgrade(migrated_database: None) -> Iterator[None]:
    """Empty the policy substrate before the session downgrades the shared database to base.

    Migration 0009 refuses to downgrade while proposals, decisions, or policy-decision events
    exist, so the shared ``migrated_database`` teardown (``alembic downgrade base``) would fail on
    any rows a record/lineage test left behind. This session finalizer runs before that teardown and
    truncates them; ordinary per-test truncation still keeps individual tests isolated.
    """
    yield
    asyncio.run(truncate_policy_rows())


async def open_recorder_txn(
    conn: AsyncConnection, tenant_id: str, *, role: str = RECORDER_ROLE
) -> None:
    """Assume the recorder identity and bind the tenant GUC on ``conn``'s open transaction."""
    await conn.execute(text("SELECT set_config(:k, :v, true)"), {"k": TENANT_GUC, "v": tenant_id})
    if role:
        await conn.execute(text(f"SET LOCAL ROLE {role}"))
