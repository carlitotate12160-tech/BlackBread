"""Existing-volume credential reconciliation proofs.

Proof map:
  D    an existing volume rotates via the reconciliation command; new credentials
       work, old fail, and role attributes, grants, memberships, recorder state,
       migration revision, and sentinel data are preserved
  E    a missing rotated role aborts before any password change and LOGIN state
       is restored (controlled failure)
  F    an active non-self migration/runtime session refuses reconciliation and
       LOGIN state is restored
  J    maintenance boundary: once the committed NOLOGIN boundary is active, no
       new session for a rotated role can be established with the old credential;
       rotation then restores LOGIN atomically (TOCTOU eliminated)
  K    the advisory lock serializes reconciliation: a held lock makes the script
       refuse without touching anything
  L    crash recovery: a boundary left active (interrupted run) does not strand
       the roles — a re-run completes the rotation
  M    the maintenance identity is local-socket-only: LOGIN but with no usable
       TCP password
  N    competing-run restore isolation: while a session owns the advisory lock
       with the committed NOLOGIN boundary active, the actual script run as a
       competing process must refuse and NEVER restore LOGIN; restoration only
       happens under serialized ownership
  O    the documented manual crash-recovery restore owns the reconciliation
       advisory lock in the same session as its ALTER ROLE statements

All credentials are synthetic per-run values; no real or repository-known secret
is used, printed, or asserted.
"""

from __future__ import annotations

import re

import pytest

from tests.deployment.credential_support import (
    ADVISORY_LOCK_KEY,
    CONTAINER_TIMEOUT,
    MAINT_ROLE,
    OLD_MIGRATION,
    OLD_RUNTIME,
    ROOT,
    can_authenticate,
    connect,
    host_port,
    init_runtime,
    postgres_container,
    preserved_state,
    psql,
    reconcile,
    seed_existing_state,
    synthetic_password,
    wait_ready,
)

pytestmark = pytest.mark.timeout(CONTAINER_TIMEOUT)


async def test_existing_volume_reconciliation_rotates_and_preserves() -> None:
    new_migration = synthetic_password()
    new_runtime = synthetic_password()
    with postgres_container(OLD_MIGRATION) as container_id:
        port = host_port(container_id)
        await wait_ready(port, OLD_MIGRATION)
        init_runtime(container_id, OLD_RUNTIME)
        seed_existing_state(container_id)
        before = preserved_state(container_id)

        reconcile(container_id, new_migration, new_runtime, check=True)

        assert await can_authenticate(port, "blackbread_migration", new_migration)
        assert await can_authenticate(port, "blackbread_app", new_runtime)
        assert not await can_authenticate(port, "blackbread_migration", OLD_MIGRATION)
        assert not await can_authenticate(port, "blackbread_app", OLD_RUNTIME)

        assert preserved_state(container_id) == before
        _assert_authority_separation(container_id)


def _assert_authority_separation(container_id: str) -> None:
    facts = psql(
        container_id,
        "SELECT "
        "(SELECT rolcanlogin::text || (rolpassword IS NOT NULL)::text FROM pg_authid "
        " WHERE rolname = 'blackbread_policy_recorder'), "
        "(SELECT count(*) FROM pg_auth_members m JOIN pg_authid r ON r.oid = m.roleid "
        " WHERE r.rolname = 'blackbread_policy_recorder'), "
        "(SELECT rolcanlogin::text || rolsuper::text FROM pg_authid "
        " WHERE rolname = 'blackbread_app'), "
        "(SELECT rolsuper::text FROM pg_authid WHERE rolname = 'blackbread_migration'), "
        # maintenance identity: LOGIN for the trusted local socket, but no stored
        # password — it can never authenticate over TCP.
        "(SELECT rolcanlogin::text || rolsuper::text || (rolpassword IS NULL)::text "
        " FROM pg_authid WHERE rolname = 'blackbread_maint')",
    )
    # recorder NOLOGIN and credential-free | recorder memberships |
    # app is a runtime login, never superuser | migration retains superuser authority |
    # maint is a local-socket-only superuser with no usable TCP password
    assert facts == "falsefalse|0|truefalse|true|truetruetrue"


async def test_reconciliation_aborts_before_any_change_when_role_missing() -> None:
    original_migration = synthetic_password()
    original_runtime = synthetic_password()
    new_migration = synthetic_password()
    new_runtime = synthetic_password()
    with postgres_container(original_migration) as container_id:
        port = host_port(container_id)
        await wait_ready(port, original_migration)
        init_runtime(container_id, original_runtime)
        # Force the boundary to fail deterministically: blackbread_app is absent.
        psql(container_id, "DROP ROLE blackbread_app")

        result = reconcile(container_id, new_migration, new_runtime, check=False)
        assert result.returncode != 0

        # Nothing rotated and the boundary was released: old works, LOGIN restored.
        assert await can_authenticate(port, "blackbread_migration", original_migration)
        assert not await can_authenticate(port, "blackbread_migration", new_migration)
        assert (
            psql(
                container_id,
                "SELECT rolcanlogin::text FROM pg_authid WHERE rolname = 'blackbread_migration'",
            )
            == "true"
        )


async def test_active_runtime_session_refuses_reconciliation() -> None:
    original_migration = synthetic_password()
    original_runtime = synthetic_password()
    new_migration = synthetic_password()
    new_runtime = synthetic_password()
    with postgres_container(original_migration) as container_id:
        port = host_port(container_id)
        await wait_ready(port, original_migration)
        init_runtime(container_id, original_runtime)

        holder = await connect(port, "blackbread_app", original_runtime)
        try:
            # Deterministic oracle: the session is present before reconciliation runs.
            active = psql(
                container_id,
                "SELECT count(*) FROM pg_stat_activity WHERE usename = 'blackbread_app'",
            )
            assert int(active) >= 1

            result = reconcile(container_id, new_migration, new_runtime, check=False)
            assert result.returncode != 0
            assert "active" in (result.stderr + result.stdout).lower()

            # No password changed and the boundary was released on refusal:
            # originals still authenticate, new values do not, LOGIN is restored.
            assert await can_authenticate(port, "blackbread_app", original_runtime)
            assert await can_authenticate(port, "blackbread_migration", original_migration)
            assert not await can_authenticate(port, "blackbread_migration", new_migration)
            assert (
                psql(
                    container_id,
                    "SELECT rolcanlogin::text FROM pg_authid "
                    "WHERE rolname IN ('blackbread_migration', 'blackbread_app') "
                    "ORDER BY rolname",
                )
                == "true\ntrue"
            )
        finally:
            await holder.close()


async def test_boundary_blocks_new_sessions_with_old_credential() -> None:
    """After the committed NOLOGIN boundary, no old-credential login can appear.

    The driver replays the script's phase order inside ONE database session, so
    the advisory lock is genuinely held and the login attempts provably happen
    inside the committed boundary window — not by racing it. The real
    maintenance identity has no usable TCP password by design, so a test-only
    superuser drives the replay; credentials are bound through PostgreSQL
    format(%L), never interpolated into test SQL text.
    """
    new_migration = synthetic_password()
    new_runtime = synthetic_password()
    driver_password = synthetic_password()
    with postgres_container(OLD_MIGRATION) as container_id:
        port = host_port(container_id)
        await wait_ready(port, OLD_MIGRATION)
        init_runtime(container_id, OLD_RUNTIME)

        bootstrap = await connect(port, "blackbread_migration", OLD_MIGRATION)
        try:
            driver_ddl = await bootstrap.fetchval(
                "SELECT format('CREATE ROLE boundary_driver SUPERUSER LOGIN "
                "PASSWORD %L', $1::text)",
                driver_password,
            )
            await bootstrap.execute(driver_ddl)
        finally:
            await bootstrap.close()

        driver = await connect(port, "boundary_driver", driver_password)
        try:
            # Script phase 1: advisory lock, then the committed NOLOGIN boundary.
            assert await driver.fetchval("SELECT pg_try_advisory_lock($1)", ADVISORY_LOCK_KEY)
            await driver.execute("ALTER ROLE blackbread_migration NOLOGIN")
            await driver.execute("ALTER ROLE blackbread_app NOLOGIN")

            # Invariant: while the boundary holds, the old credential cannot open
            # a session for either rotated role — the check-to-ALTER race is gone.
            assert not await can_authenticate(port, "blackbread_app", OLD_RUNTIME)
            assert not await can_authenticate(port, "blackbread_migration", OLD_MIGRATION)

            # Script phase 2: rotate both passwords and restore LOGIN atomically.
            rotate = [
                await driver.fetchval(
                    "SELECT format('ALTER ROLE blackbread_migration WITH LOGIN "
                    "PASSWORD %L', $1::text)",
                    new_migration,
                ),
                await driver.fetchval(
                    "SELECT format('ALTER ROLE blackbread_app WITH LOGIN PASSWORD %L', $1::text)",
                    new_runtime,
                ),
            ]
            async with driver.transaction():
                for statement in rotate:
                    await driver.execute(statement)
            await driver.execute("SELECT pg_advisory_unlock($1)", ADVISORY_LOCK_KEY)
        finally:
            await driver.close()

        assert await can_authenticate(port, "blackbread_migration", new_migration)
        assert await can_authenticate(port, "blackbread_app", new_runtime)


async def test_advisory_lock_serializes_reconciliation() -> None:
    """A held advisory lock makes the script refuse without rotating anything."""
    original_migration = synthetic_password()
    original_runtime = synthetic_password()
    new_migration = synthetic_password()
    new_runtime = synthetic_password()
    with postgres_container(original_migration) as container_id:
        port = host_port(container_id)
        await wait_ready(port, original_migration)
        init_runtime(container_id, original_runtime)

        # Deterministic barrier: a foreign session holds the reconciliation lock.
        locker = await connect(port, "blackbread_migration", original_migration)
        try:
            assert await locker.fetchval("SELECT pg_try_advisory_lock($1)", ADVISORY_LOCK_KEY)
            held = await locker.fetchval(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                "AND granted AND objid = $1",
                ADVISORY_LOCK_KEY,
            )
            assert int(held) == 1

            result = reconcile(container_id, new_migration, new_runtime, check=False)
            assert result.returncode != 0
            assert "lock" in (result.stderr + result.stdout).lower()

            # Nothing changed while the lock was held.
            assert await can_authenticate(port, "blackbread_migration", original_migration)
        finally:
            await locker.close()

        # Once the lock is released, reconciliation proceeds normally.
        reconcile(container_id, new_migration, new_runtime, check=True)
        assert await can_authenticate(port, "blackbread_app", new_runtime)


async def test_rerun_completes_rotation_after_interrupted_boundary() -> None:
    """A boundary left active by an interrupted run must not strand the roles.

    Simulates the crash state (both roles NOLOGIN) and proves the documented
    recovery path: re-running the script completes the rotation and restores
    LOGIN, because the maintenance identity is not among the rotated roles.
    """
    original_migration = synthetic_password()
    original_runtime = synthetic_password()
    new_migration = synthetic_password()
    new_runtime = synthetic_password()
    with postgres_container(original_migration) as container_id:
        port = host_port(container_id)
        await wait_ready(port, original_migration)
        init_runtime(container_id, original_runtime)
        # First run creates the maintenance identity, then we simulate the crash
        # state by leaving both rotated roles NOLOGIN.
        reconcile(container_id, original_migration, original_runtime, check=True)
        psql(
            container_id,
            "ALTER ROLE blackbread_migration NOLOGIN; ALTER ROLE blackbread_app NOLOGIN",
            role=MAINT_ROLE,
        )
        assert not await can_authenticate(port, "blackbread_app", original_runtime)

        result = reconcile(container_id, new_migration, new_runtime, check=False)
        assert result.returncode == 0
        assert await can_authenticate(port, "blackbread_migration", new_migration)
        assert await can_authenticate(port, "blackbread_app", new_runtime)


async def test_competing_reconcile_never_restores_inside_owned_boundary() -> None:
    """While the lock is owned, a competing reconcile can never restore LOGIN.

    Deterministic barrier: session A holds the advisory lock with the committed
    NOLOGIN boundary active (verified via pg_locks); process B is the actual
    reconcile script. B's try-lock fails under A's ownership, so it must refuse
    and exit WITHOUT mutating either rotated role — the committed boundary
    stays intact. The owner then completes controlled restoration under its own
    serialized ownership and releases; only then do the old credentials work.
    """
    new_migration = synthetic_password()
    new_runtime = synthetic_password()
    driver_password = synthetic_password()
    with postgres_container(OLD_MIGRATION) as container_id:
        port = host_port(container_id)
        await wait_ready(port, OLD_MIGRATION)
        init_runtime(container_id, OLD_RUNTIME)
        # The maintenance identity must already exist so B's phase-0 probe
        # passes and B provably reaches the lock acquisition.
        psql(container_id, "CREATE ROLE blackbread_maint SUPERUSER LOGIN")
        bootstrap = await connect(port, "blackbread_migration", OLD_MIGRATION)
        try:
            driver_ddl = await bootstrap.fetchval(
                "SELECT format('CREATE ROLE boundary_driver SUPERUSER LOGIN "
                "PASSWORD %L', $1::text)",
                driver_password,
            )
            await bootstrap.execute(driver_ddl)
        finally:
            await bootstrap.close()

        owner = await connect(port, "boundary_driver", driver_password)
        try:
            # A owns the serialized boundary: lock granted + committed NOLOGIN.
            assert await owner.fetchval("SELECT pg_try_advisory_lock($1)", ADVISORY_LOCK_KEY)
            await owner.execute("ALTER ROLE blackbread_migration NOLOGIN")
            await owner.execute("ALTER ROLE blackbread_app NOLOGIN")
            # Deterministic barrier: the advisory lock is granted to A's session.
            held = await owner.fetchval(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                "AND granted AND objid = $1",
                ADVISORY_LOCK_KEY,
            )
            assert int(held) == 1

            # Process B: the actual script, run to completion while A owns the
            # boundary. subprocess.run returns only after B has fully exited.
            result = reconcile(container_id, new_migration, new_runtime, check=False)
            assert result.returncode != 0
            assert "lock" in (result.stderr + result.stdout).lower()

            # B exited and NEVER mutated: the committed boundary is still intact,
            # so the old credentials still cannot open a session for either role.
            assert not await can_authenticate(port, "blackbread_app", OLD_RUNTIME)
            assert not await can_authenticate(port, "blackbread_migration", OLD_MIGRATION)

            # Controlled restoration by the owner under its own serialized
            # ownership, then release of the lock.
            await owner.execute("ALTER ROLE blackbread_migration LOGIN")
            await owner.execute("ALTER ROLE blackbread_app LOGIN")
            await owner.execute("SELECT pg_advisory_unlock($1)", ADVISORY_LOCK_KEY)
        finally:
            await owner.close()

        # Passwords were never rotated, and LOGIN is restored only after the
        # serialized owner completed the restoration.
        assert await can_authenticate(port, "blackbread_app", OLD_RUNTIME)
        assert await can_authenticate(port, "blackbread_migration", OLD_MIGRATION)


async def test_maintenance_identity_has_no_usable_tcp_password() -> None:
    """The maintenance role is LOGIN for the local socket only: no TCP auth."""
    migration_password = synthetic_password()
    runtime_password = synthetic_password()
    with postgres_container(migration_password) as container_id:
        port = host_port(container_id)
        await wait_ready(port, migration_password)
        init_runtime(container_id, runtime_password)
        reconcile(container_id, migration_password, runtime_password, check=True)

        # LOGIN + superuser, but rolpassword IS NULL -> every TCP password auth fails.
        assert not await can_authenticate(port, MAINT_ROLE, synthetic_password())
        assert (
            psql(
                container_id,
                "SELECT rolsuper::text || '|' || (rolpassword IS NULL)::text "
                "FROM pg_authid WHERE rolname = 'blackbread_maint'",
            )
            == "true|true"
        )


def test_documented_manual_restore_owns_reconciliation_lock() -> None:
    """README's manual LOGIN restore must own advisory lock 727274.

    The crash-recovery block restores LOGIN without rotating; the lock, both
    ALTER ROLE statements, and the unlock must run in one psql session so a
    manual restore can never reopen LOGIN inside another owner's committed
    NOLOGIN boundary.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    blocks = re.findall(r"```bash\n(.*?)```", readme, re.DOTALL)
    restore = next(b for b in blocks if "ALTER ROLE" in b and "LOGIN" in b)
    lock = f"pg_advisory_lock({ADVISORY_LOCK_KEY})"
    unlock = f"pg_advisory_unlock({ADVISORY_LOCK_KEY})"
    assert lock in restore, "manual restore never acquires the reconciliation lock"
    assert restore.index(lock) < restore.index("ALTER ROLE")
    for role in ("blackbread_migration", "blackbread_app"):
        assert f"ALTER ROLE {role} LOGIN" in restore
    assert restore.rindex("ALTER ROLE") < restore.index(unlock)
    assert "--no-psqlrc" in restore and "ON_ERROR_STOP=1" in restore
    # One psql invocation carries lock, restoration, and unlock: a single session.
    assert len(re.findall(r"\bpsql\b", restore)) == 1
