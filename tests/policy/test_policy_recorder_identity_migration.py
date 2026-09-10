"""M1.4c2b0a committed inert recorder-role identity and non-assumability proofs.

Observes the ``blackbread_policy_recorder`` role produced by ``alembic upgrade head`` on the shared
migrated test database (revision ``0008_m1_policy_recorder_identity``). Proves the exact inert
``pg_authid`` shape, the absence of any grant, direct ``pg_shdepend`` dependency,
``pg_auth_members`` membership, or ``pg_db_role_setting`` configuration, and that ordinary
BlackBread login/runtime identities cannot ``SET ROLE`` to it.

A temporary-mutation proof shows the non-assumability oracle is genuinely sensitive: granting
recorder membership to the test runtime makes ``SET ROLE`` succeed. The grant is committed
transiently (the separate ``runtime_login_engine`` login session must observe it), then reverted in
``finally``; a module-scoped finalizer additionally sweeps any residual membership so an interrupted
run cannot leave it behind. The suite runs serially (no ``pytest -n``), so no concurrent test
observes the transient grant. ``blackbread_app`` does not exist in the loopback test cluster
(``deploy/postgres/init-runtime.sh`` creates it only on a deployed cluster); its non-assumability is
proven on the Oracle ARM64 cluster and recorded in the pull request.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import TEST_DATABASE_URL, TEST_MIGRATION_DATABASE_URL

RECORDER_ROLE = "blackbread_policy_recorder"
RUNTIME_ROLE = "blackbread_runtime"
TEST_LOGIN_ROLE = "blackbread_test_runtime"
# 0007 revokes PUBLIC on these two tables, so a false ``has_table_privilege`` here reflects a direct
# grant to the recorder rather than an ambient PUBLIC privilege the slice does not claim absent.
REVOKED_PUBLIC_TABLES = ("action_proposals", "decision_records")
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

_ATTRIBUTES = text(
    "SELECT oid, rolcanlogin, rolinherit, rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
    "rolbypassrls, rolconnlimit, (rolpassword IS NULL) AS pw_null, "
    "(rolvaliduntil IS NULL) AS valid_null FROM pg_authid WHERE rolname = :name"
)
# Best-effort sweep of the transient sensitivity-test membership; a DO block so it is a no-op when
# either role is absent (REVOKE on a non-existent role would otherwise error).
_SWEEP_MEMBERSHIP = text(
    "DO $$ BEGIN "
    "IF EXISTS (SELECT 1 FROM pg_authid WHERE rolname = 'blackbread_policy_recorder') "
    "AND EXISTS (SELECT 1 FROM pg_authid WHERE rolname = 'blackbread_test_runtime') "
    "THEN EXECUTE 'REVOKE blackbread_policy_recorder FROM blackbread_test_runtime'; "
    "END IF; END $$"
)


@pytest.fixture(scope="module", autouse=True)
def sweep_recorder_membership_after_module() -> Iterator[None]:
    """Revoke any residual recorder membership left by an interrupted sensitivity test."""
    yield

    async def _sweep() -> None:
        admin = create_async_engine(TEST_MIGRATION_DATABASE_URL, isolation_level="AUTOCOMMIT")
        try:
            async with admin.connect() as conn:
                await conn.execute(_SWEEP_MEMBERSHIP)
        finally:
            await admin.dispose()

    asyncio.run(_sweep())


@pytest_asyncio.fixture
async def runtime_login_engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    """A real login session as ``blackbread_test_runtime`` (a member of ``blackbread_runtime``)."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _recorder_oid(engine: AsyncEngine) -> int | None:
    async with engine.connect() as conn:
        return await conn.scalar(
            text("SELECT oid FROM pg_authid WHERE rolname = :name"), {"name": RECORDER_ROLE}
        )


async def test_committed_recorder_role_has_exact_inert_shape(
    policy_admin_engine: AsyncEngine,
) -> None:
    async with policy_admin_engine.connect() as conn:
        row = (await conn.execute(_ATTRIBUTES, {"name": RECORDER_ROLE})).mappings().one_or_none()

    assert row is not None, "recorder role must exist after upgrade to head"
    assert row["rolcanlogin"] is False
    assert row["rolinherit"] is False
    assert row["rolsuper"] is False
    assert row["rolcreatedb"] is False
    assert row["rolcreaterole"] is False
    assert row["rolreplication"] is False
    assert row["rolbypassrls"] is False
    assert row["rolconnlimit"] == -1
    assert row["pw_null"] is True
    assert row["valid_null"] is True


async def test_committed_recorder_role_has_no_dependency_membership_or_setting(
    policy_admin_engine: AsyncEngine,
) -> None:
    oid = await _recorder_oid(policy_admin_engine)
    assert oid is not None
    async with policy_admin_engine.connect() as conn:
        shdepend = await conn.scalar(
            text(
                "SELECT count(*) FROM pg_shdepend "
                "WHERE refclassid = 'pg_authid'::regclass AND refobjid = :oid"
            ),
            {"oid": oid},
        )
        members = await conn.scalar(
            text(
                "SELECT count(*) FROM pg_auth_members "
                "WHERE roleid = :oid OR member = :oid OR grantor = :oid"
            ),
            {"oid": oid},
        )
        settings = await conn.scalar(
            text("SELECT count(*) FROM pg_db_role_setting WHERE setrole = :oid"), {"oid": oid}
        )

    assert shdepend == 0, "recorder must have zero direct cluster-wide shared dependencies"
    assert members == 0, "recorder must have no role membership edge in any direction"
    assert settings == 0, "recorder must have no role-specific configuration"


async def test_committed_recorder_role_holds_no_direct_table_grant(
    policy_admin_engine: AsyncEngine,
) -> None:
    async with policy_admin_engine.connect() as conn:
        for table in REVOKED_PUBLIC_TABLES:
            for privilege in TABLE_PRIVILEGES:
                granted = await conn.scalar(
                    text("SELECT has_table_privilege(:r, :t, :p)"),
                    {"r": RECORDER_ROLE, "t": table, "p": privilege},
                )
                assert granted is False, f"recorder must not hold {privilege} on {table}"


async def test_test_runtime_login_cannot_set_role_to_recorder(
    runtime_login_engine: AsyncEngine,
) -> None:
    async with runtime_login_engine.connect() as conn:
        with pytest.raises(ProgrammingError):
            await conn.execute(text(f"SET ROLE {RECORDER_ROLE}"))


async def test_runtime_role_session_cannot_set_role_to_recorder(
    runtime_login_engine: AsyncEngine,
) -> None:
    async with runtime_login_engine.connect() as conn:
        # The login role is a member of blackbread_runtime, so it may assume the runtime role, but
        # from there the recorder remains unreachable (no membership edge exists).
        await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
        with pytest.raises(ProgrammingError):
            await conn.execute(text(f"SET ROLE {RECORDER_ROLE}"))


async def test_setrole_failure_leaves_recorder_membership_absent(
    policy_admin_engine: AsyncEngine, runtime_login_engine: AsyncEngine
) -> None:
    async with runtime_login_engine.connect() as conn:
        with pytest.raises(ProgrammingError):
            await conn.execute(text(f"SET ROLE {RECORDER_ROLE}"))

    oid = await _recorder_oid(policy_admin_engine)
    async with policy_admin_engine.connect() as conn:
        members = await conn.scalar(
            text("SELECT count(*) FROM pg_auth_members WHERE roleid = :oid OR member = :oid"),
            {"oid": oid},
        )
    assert members == 0


async def test_non_assumability_oracle_is_sensitive_to_membership(
    policy_admin_engine: AsyncEngine, runtime_login_engine: AsyncEngine
) -> None:
    """Adversarial sensitivity check: with recorder membership granted the SET ROLE succeeds, so a
    passing non-assumability oracle above is meaningful. The grant is committed transiently so the
    separate ``runtime_login_engine`` login session observes it, then reverted in ``finally``; the
    module finalizer sweeps any residue if this test is interrupted before the revoke."""
    async with policy_admin_engine.begin() as conn:
        await conn.execute(text(f"GRANT {RECORDER_ROLE} TO {TEST_LOGIN_ROLE}"))
    try:
        async with runtime_login_engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RECORDER_ROLE}"))
            current = await conn.scalar(text("SELECT current_user"))
        assert current == RECORDER_ROLE, "granting membership must make SET ROLE succeed"
    finally:
        async with policy_admin_engine.begin() as conn:
            await conn.execute(text(f"REVOKE {RECORDER_ROLE} FROM {TEST_LOGIN_ROLE}"))

    async with runtime_login_engine.connect() as conn:
        with pytest.raises(ProgrammingError):
            await conn.execute(text(f"SET ROLE {RECORDER_ROLE}"))
