"""M1.4c2b0a recorder-role migration lifecycle, rejection, downgrade, and reconciliation proofs.

Runs against the private throwaway database created by the lifecycle harness; it never mutates the
shared development or Oracle production database. Because a cluster role is global, a module-scoped
finalizer restores ``blackbread_policy_recorder`` to the exact inert, dependency-free identity after
this module so the shared session teardown (``alembic downgrade base`` -> ``DROP ROLE``) holds.

Proves: create-from-absent and exact committed shape; clean pre-existing continuity with an
unchanged OID; the attribute/identity/role-setting, membership, and direct-dependency rejection
matrices leave Alembic at ``0007`` without silently normalising the role; a cluster-wide dependency
in a second database is still detected; the downgrade round trip and its dependency-guarded abort;
and the commit-ambiguity reconciliation matrix over real committed and rolled-back transactions.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.conftest import TEST_MIGRATION_DATABASE_URL
from tests.policy.conftest import ROOT, run_alembic

REV_0007 = "0007_m1_policy_records"
REV_0008 = "0008_m1_policy_recorder_identity"
RECORDER_ROLE = "blackbread_policy_recorder"
PROBE_ROLE = "blackbread_recorder_probe"
_CREATE_CLEAN = (
    f"CREATE ROLE {RECORDER_ROLE} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
    "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1 PASSWORD NULL"
)
_MIGRATION_FILE = ROOT / "migrations" / "versions" / "0008_m1_policy_recorder_identity.py"


def _load_reconciler():  # imports the migration module by path to exercise its pure classifier
    spec = importlib.util.spec_from_file_location("_m0008_identity", _MIGRATION_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.reconcile_recorder_migration_state


async def _run_admin(sql: str) -> None:
    admin = create_async_engine(TEST_MIGRATION_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await admin.dispose()


async def _drop_recorder() -> None:
    await _run_admin(f"DROP ROLE IF EXISTS {RECORDER_ROLE}")


async def _ensure_clean_recorder() -> None:
    await _drop_recorder()
    await _run_admin(_CREATE_CLEAN)


@pytest.fixture(scope="module", autouse=True)
def restore_recorder_after_module() -> Iterator[None]:
    yield
    asyncio.run(_ensure_clean_recorder())


async def _recorder_present(admin: AsyncEngine) -> bool:
    async with admin.connect() as conn:
        return bool(
            await conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_authid WHERE rolname = :n)"),
                {"n": RECORDER_ROLE},
            )
        )


async def _recorder_oid(admin: AsyncEngine) -> int | None:
    async with admin.connect() as conn:
        return await conn.scalar(
            text("SELECT oid FROM pg_authid WHERE rolname = :n"), {"n": RECORDER_ROLE}
        )


async def _alembic_version(admin: AsyncEngine) -> str | None:
    async with admin.connect() as conn:
        return await conn.scalar(text("SELECT version_num FROM alembic_version"))


async def _dependency_counts(admin: AsyncEngine) -> tuple[int, int, int]:
    oid = await _recorder_oid(admin)
    assert oid is not None
    async with admin.connect() as conn:
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


def _alembic_env(db_name: str) -> dict[str, str]:
    env = os.environ.copy()
    env["BLACKBREAD_DATABASE_URL"] = (
        make_url(TEST_MIGRATION_DATABASE_URL)
        .set(database=db_name)
        .render_as_string(hide_password=False)
    )
    return env


def _alembic_expecting_failure(db_name: str, direction: str, target: str) -> str:
    """Run an alembic step that must fail, returning combined output for reason assertions."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", direction, target],
        cwd=ROOT,
        env=_alembic_env(db_name),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, f"expected {direction} to fail, got success:\n{result.stdout}"
    return result.stdout + result.stderr


async def _reset_to_0007(lifecycle_db: str) -> None:
    run_alembic(lifecycle_db, "downgrade", "base")
    run_alembic(lifecycle_db, "upgrade", REV_0007)


async def test_upgrade_creates_recorder_from_absent(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    await _reset_to_0007(lifecycle_db)
    await _drop_recorder()
    assert not await _recorder_present(lifecycle_admin_engine)

    run_alembic(lifecycle_db, "upgrade", REV_0008)

    assert await _alembic_version(lifecycle_admin_engine) == REV_0008
    assert await _recorder_present(lifecycle_admin_engine)
    assert await _dependency_counts(lifecycle_admin_engine) == (0, 0, 0)


async def test_clean_pre_existing_role_preserved_with_same_oid(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    await _reset_to_0007(lifecycle_db)
    await _ensure_clean_recorder()
    oid_before = await _recorder_oid(lifecycle_admin_engine)

    run_alembic(lifecycle_db, "upgrade", REV_0008)

    assert await _alembic_version(lifecycle_admin_engine) == REV_0008
    assert await _recorder_oid(lifecycle_admin_engine) == oid_before, "role was dropped/recreated"


# label -> (attribute fragment that breaks the inert shape, fragment that restores it).
_ATTRIBUTE_CASES: tuple[tuple[str, str, str], ...] = (
    ("login", "LOGIN", "NOLOGIN"),
    ("inherit", "INHERIT", "NOINHERIT"),
    ("superuser", "SUPERUSER", "NOSUPERUSER"),
    ("createdb", "CREATEDB", "NOCREATEDB"),
    ("createrole", "CREATEROLE", "NOCREATEROLE"),
    ("replication", "REPLICATION", "NOREPLICATION"),
    ("bypassrls", "BYPASSRLS", "NOBYPASSRLS"),
    ("connlimit", "CONNECTION LIMIT 5", "CONNECTION LIMIT -1"),
    ("password", "PASSWORD 'not-inert'", "PASSWORD NULL"),
    ("validity", "VALID UNTIL '2030-01-01'", "VALID UNTIL 'infinity'"),
    ("role_setting", "SET search_path = public", "RESET search_path"),
)


@pytest.mark.parametrize(
    ("label", "break_frag", "restore_frag"),
    _ATTRIBUTE_CASES,
    ids=[case[0] for case in _ATTRIBUTE_CASES],
)
async def test_upgrade_rejects_non_inert_role(
    lifecycle_db: str,
    lifecycle_admin_engine: AsyncEngine,
    label: str,
    break_frag: str,
    restore_frag: str,
) -> None:
    await _reset_to_0007(lifecycle_db)
    await _ensure_clean_recorder()
    oid_before = await _recorder_oid(lifecycle_admin_engine)
    await _run_admin(f"ALTER ROLE {RECORDER_ROLE} {break_frag}")
    try:
        output = _alembic_expecting_failure(lifecycle_db, "upgrade", REV_0008)
        assert RECORDER_ROLE in output, f"{label}: failure must name the recorder role"
        assert await _alembic_version(lifecycle_admin_engine) == REV_0007
        # No silent normalisation: the role is still present and the same object.
        assert await _recorder_oid(lifecycle_admin_engine) == oid_before
    finally:
        await _run_admin(f"ALTER ROLE {RECORDER_ROLE} {restore_frag}")


_MEMBERSHIP_CASES = (
    ("recorder_is_member", f"GRANT {PROBE_ROLE} TO {RECORDER_ROLE}"),
    ("recorder_has_member", f"GRANT {RECORDER_ROLE} TO {PROBE_ROLE}"),
)


@pytest.mark.parametrize(
    ("label", "grant_sql"),
    _MEMBERSHIP_CASES,
    ids=[case[0] for case in _MEMBERSHIP_CASES],
)
async def test_upgrade_rejects_role_membership(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine, label: str, grant_sql: str
) -> None:
    await _reset_to_0007(lifecycle_db)
    await _ensure_clean_recorder()
    await _run_admin(f"CREATE ROLE {PROBE_ROLE} NOLOGIN")
    await _run_admin(grant_sql)
    try:
        output = _alembic_expecting_failure(lifecycle_db, "upgrade", REV_0008)
        assert RECORDER_ROLE in output
        assert await _alembic_version(lifecycle_admin_engine) == REV_0007
        # Membership was not silently revoked by the failed migration.
        _, members, _ = await _dependency_counts(lifecycle_admin_engine)
        assert members >= 1, f"{label}: membership must survive the rejected upgrade"
    finally:
        await _run_admin(f"DROP ROLE IF EXISTS {PROBE_ROLE}")


# label -> (setup statements creating a recorder dependency, cleanup statements). ``{db}`` is the
# lifecycle database name.
_DEPENDENCY_CASES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "owned_table",
        ("CREATE TABLE probe_t (id int)", f"ALTER TABLE probe_t OWNER TO {RECORDER_ROLE}"),
        ("DROP TABLE IF EXISTS probe_t",),
    ),
    (
        "owned_schema",
        (f"CREATE SCHEMA probe_s AUTHORIZATION {RECORDER_ROLE}",),
        ("DROP SCHEMA IF EXISTS probe_s CASCADE",),
    ),
    (
        "owned_routine",
        (
            "CREATE FUNCTION probe_fn() RETURNS int LANGUAGE sql AS 'SELECT 1'",
            f"ALTER FUNCTION probe_fn() OWNER TO {RECORDER_ROLE}",
        ),
        ("DROP FUNCTION IF EXISTS probe_fn()",),
    ),
    (
        "table_grant",
        ("CREATE TABLE probe_t (id int)", f"GRANT SELECT ON probe_t TO {RECORDER_ROLE}"),
        ("DROP TABLE IF EXISTS probe_t",),
    ),
    (
        "column_grant",
        (
            "CREATE TABLE probe_t (id int, secret int)",
            f"GRANT SELECT (secret) ON probe_t TO {RECORDER_ROLE}",
        ),
        ("DROP TABLE IF EXISTS probe_t",),
    ),
    (
        "sequence_grant",
        ("CREATE SEQUENCE probe_seq", f"GRANT USAGE ON SEQUENCE probe_seq TO {RECORDER_ROLE}"),
        ("DROP SEQUENCE IF EXISTS probe_seq",),
    ),
    (
        "schema_grant",
        ("CREATE SCHEMA probe_s", f"GRANT USAGE ON SCHEMA probe_s TO {RECORDER_ROLE}"),
        ("DROP SCHEMA IF EXISTS probe_s CASCADE",),
    ),
    (
        "database_privilege",
        (f"GRANT CREATE ON DATABASE {{db}} TO {RECORDER_ROLE}",),
        (f"REVOKE CREATE ON DATABASE {{db}} FROM {RECORDER_ROLE}",),
    ),
    (
        "default_acl",
        (f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {RECORDER_ROLE}",),
        (
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "  # noqa: S608 - static DDL, role name only
            f"REVOKE SELECT ON TABLES FROM {RECORDER_ROLE}",
        ),
    ),
    (
        "rls_policy",
        (
            "CREATE TABLE probe_t (id int)",
            f"CREATE POLICY probe_pol ON probe_t FOR SELECT TO {RECORDER_ROLE} USING (true)",
        ),
        ("DROP TABLE IF EXISTS probe_t",),
    ),
)


@pytest.mark.parametrize(
    ("label", "setup", "cleanup"),
    _DEPENDENCY_CASES,
    ids=[case[0] for case in _DEPENDENCY_CASES],
)
async def test_upgrade_rejects_direct_dependency(
    lifecycle_db: str,
    lifecycle_admin_engine: AsyncEngine,
    label: str,
    setup: tuple[str, ...],
    cleanup: tuple[str, ...],
) -> None:
    await _reset_to_0007(lifecycle_db)
    await _ensure_clean_recorder()
    lifecycle_url = make_url(TEST_MIGRATION_DATABASE_URL).set(database=lifecycle_db)
    probe = create_async_engine(lifecycle_url, isolation_level="AUTOCOMMIT")
    try:
        async with probe.connect() as conn:
            for statement in setup:
                await conn.execute(text(statement.format(db=lifecycle_db)))
        output = _alembic_expecting_failure(lifecycle_db, "upgrade", REV_0008)
        assert RECORDER_ROLE in output, f"{label}: failure must name the recorder role"
        assert await _alembic_version(lifecycle_admin_engine) == REV_0007
    finally:
        async with probe.connect() as conn:
            for statement in cleanup:
                await conn.execute(text(statement.format(db=lifecycle_db)))
        await probe.dispose()


async def test_upgrade_rejects_dependency_in_second_database(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    """A cluster-wide pg_shdepend authority must detect a recorder dependency in a *second*
    database, not only the migration's own database."""
    await _reset_to_0007(lifecycle_db)
    await _ensure_clean_recorder()
    other_db = f"blackbread_test_recorder_{uuid.uuid4().hex[:8]}"
    await _run_admin(f"CREATE DATABASE {other_db}")
    other_url = make_url(TEST_MIGRATION_DATABASE_URL).set(database=other_db)
    other = create_async_engine(other_url, isolation_level="AUTOCOMMIT")
    try:
        async with other.connect() as conn:
            await conn.execute(text("CREATE TABLE cross_db_probe (id int)"))
            await conn.execute(text(f"ALTER TABLE cross_db_probe OWNER TO {RECORDER_ROLE}"))
        output = _alembic_expecting_failure(lifecycle_db, "upgrade", REV_0008)
        assert RECORDER_ROLE in output
        assert await _alembic_version(lifecycle_admin_engine) == REV_0007
    finally:
        async with other.connect() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS cross_db_probe"))
        await other.dispose()
        await _run_admin(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "  # noqa: S608
            f"WHERE datname = '{other_db}' AND pid <> pg_backend_pid()"
        )
        await _run_admin(f"DROP DATABASE IF EXISTS {other_db}")


async def test_downgrade_round_trip_toggles_role_presence(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    await _reset_to_0007(lifecycle_db)
    await _drop_recorder()

    run_alembic(lifecycle_db, "upgrade", REV_0008)
    assert await _recorder_present(lifecycle_admin_engine)

    run_alembic(lifecycle_db, "downgrade", REV_0007)
    assert await _alembic_version(lifecycle_admin_engine) == REV_0007
    assert not await _recorder_present(lifecycle_admin_engine)

    run_alembic(lifecycle_db, "upgrade", REV_0008)
    assert await _alembic_version(lifecycle_admin_engine) == REV_0008
    assert await _recorder_present(lifecycle_admin_engine)


async def test_downgrade_aborts_when_role_has_dependency(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    await _reset_to_0007(lifecycle_db)
    await _drop_recorder()
    run_alembic(lifecycle_db, "upgrade", REV_0008)

    lifecycle_url = make_url(TEST_MIGRATION_DATABASE_URL).set(database=lifecycle_db)
    probe = create_async_engine(lifecycle_url, isolation_level="AUTOCOMMIT")
    try:
        async with probe.connect() as conn:
            await conn.execute(text("CREATE TABLE downgrade_probe (id int)"))
            await conn.execute(text(f"ALTER TABLE downgrade_probe OWNER TO {RECORDER_ROLE}"))
        output = _alembic_expecting_failure(lifecycle_db, "downgrade", REV_0007)
        assert RECORDER_ROLE in output
        assert await _alembic_version(lifecycle_admin_engine) == REV_0008
        assert await _recorder_present(lifecycle_admin_engine)
    finally:
        async with probe.connect() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS downgrade_probe"))
        await probe.dispose()


async def test_commit_ambiguity_reconciliation_matrix(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    reconcile = _load_reconciler()

    # Committed success: a real committed upgrade leaves version 0008 and a clean role.
    await _reset_to_0007(lifecycle_db)
    await _drop_recorder()
    run_alembic(lifecycle_db, "upgrade", REV_0008)
    version = await _alembic_version(lifecycle_admin_engine)
    present = await _recorder_present(lifecycle_admin_engine)
    clean = await _dependency_counts(lifecycle_admin_engine) == (0, 0, 0)
    assert reconcile(version_num=version, role_present=present, role_clean=clean) == "committed"

    # Not committed, role absent: safe to retry.
    run_alembic(lifecycle_db, "downgrade", REV_0007)
    await _drop_recorder()
    version = await _alembic_version(lifecycle_admin_engine)
    assert reconcile(version_num=version, role_present=False, role_clean=False) == "retry"

    # Not committed, exact pre-existing role: safe to retry.
    await _ensure_clean_recorder()
    assert reconcile(version_num=REV_0007, role_present=True, role_clean=True) == "retry"

    # Mixed/unexpected: committed version but role gone -> stop; do not retry blindly.
    assert reconcile(version_num=REV_0008, role_present=False, role_clean=False) == "stop"

    # A rolled-back CREATE ROLE transaction really leaves the role absent (not a Python mock).
    await _drop_recorder()
    admin = create_async_engine(TEST_MIGRATION_DATABASE_URL)
    try:
        async with admin.connect() as conn:
            transaction = await conn.begin()
            await conn.execute(text(_CREATE_CLEAN))
            await transaction.rollback()
    finally:
        await admin.dispose()
    assert not await _recorder_present(lifecycle_admin_engine)
