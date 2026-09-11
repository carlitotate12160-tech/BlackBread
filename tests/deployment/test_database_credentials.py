"""Real-PostgreSQL and Compose proofs for the database credential bootstrap.

These tests use disposable, loopback-only PostgreSQL containers (no mocks for
authentication, the role catalog, or transactional rotation) and the actual
canonical Compose file and reconciliation script. All credentials are synthetic
per-run values or the removed repository defaults (which must fail); no real
secret is used, printed, or asserted by value; removed defaults are never embedded here.

Proof map:
  A/B  canonical Compose validation fails closed on a missing or empty credential
  C    a fresh volume bootstraps from supplied credentials; a non-supplied credential fails;
       the runtime login cannot perform migration-owner operations
  D    an existing volume rotates via the reconciliation command; new credentials
       work, old fail, and role attributes, grants, memberships, recorder state,
       migration revision, and sentinel data are preserved
  E    a forced second-role failure rolls the first password change back (atomic)
  F    an active non-self migration/runtime session refuses reconciliation
  G    api receives runtime authority, migrate receives migration authority, and
       the recorder stays NOLOGIN, credential-free, and without membership
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import subprocess
from collections.abc import Iterator, Mapping
from pathlib import Path

import asyncpg
import pytest
import yaml

ROOT = Path(__file__).parents[2]
COMPOSE = ROOT / "compose.yaml"
INIT_SCRIPT = ROOT / "deploy" / "postgres" / "init-runtime.sh"
RECONCILE_SCRIPT = ROOT / "deploy" / "postgres" / "reconcile-credentials.sh"
IMAGE = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["database"]["image"]

# Synthetic pre-rotation credentials standing in for whatever a pre-existing volume or a
# repository-derived guess might hold. They are asserted to fail after bootstrap/rotation;
# no real or repository-known credential is placed in the repository (proof H: synthetic only).
OLD_MIGRATION = "old_" + secrets.token_hex(8)
OLD_RUNTIME = "old_" + secrets.token_hex(8)

CONTAINER_TIMEOUT = 300
pytestmark = pytest.mark.timeout(CONTAINER_TIMEOUT)

# Static docker/psql fragments shared by the helpers below.
_DB_ENV = ["-e", "POSTGRES_USER=blackbread_migration", "-e", "POSTGRES_DB=blackbread"]
_PSQL = ["psql", "-v", "ON_ERROR_STOP=1", "--no-psqlrc", "-tAqc"]
_PSQL_CONN = ["-U", "blackbread_migration", "-d", "blackbread"]


def _synthetic_password() -> str:
    """A unique, synthetic credential that never appears in the repository."""
    return "syn_" + secrets.token_hex(16)


def _run(args: list[str], *, env: Mapping[str, str] | None = None, check: bool = True):
    return subprocess.run(
        args,
        env=dict(env) if env is not None else None,
        check=check,
        capture_output=True,
        text=True,
        timeout=CONTAINER_TIMEOUT,
    )


@contextlib.contextmanager
def postgres_container(migration_password: str) -> Iterator[str]:
    """Start a disposable, loopback-only PostgreSQL container and remove it after."""
    env = os.environ.copy()
    env["POSTGRES_PASSWORD"] = migration_password
    # POSTGRES_PASSWORD value travels via env, never in argv.
    run_args = ["docker", "run", "-d", "--rm", *_DB_ENV, "-e", "POSTGRES_PASSWORD"]
    started = _run([*run_args, "-p", "127.0.0.1::5432", IMAGE], env=env)
    container_id = started.stdout.strip()
    try:
        yield container_id
    finally:
        _run(["docker", "rm", "-f", container_id], check=False)


def _host_port(container_id: str) -> int:
    mapping = _run(["docker", "port", container_id, "5432/tcp"]).stdout.strip()
    return int(mapping.splitlines()[0].rsplit(":", 1)[1])


async def _connect(port: int, role: str, password: str, *, connect_timeout: int = 10):
    return await asyncpg.connect(
        host="127.0.0.1",
        port=port,
        user=role,
        password=password,
        database="blackbread",
        timeout=connect_timeout,
    )


def _exec_script(container_id: str, script: Path, values: Mapping[str, str], *, check: bool):
    """Copy a deploy script into the container and run it with named env inputs."""
    target = f"/tmp/{script.name}"  # noqa: S108 - container path, not a host temp file
    _run(["docker", "cp", str(script), f"{container_id}:{target}"])
    # Normalize CRLF -> LF so a Windows working-tree checkout runs identically to the
    # LF-committed script used on the Linux deployment target.
    _run(["docker", "exec", container_id, "sed", "-i", "s/\\r$//", target])
    env = os.environ.copy()
    env.update(values)
    args = ["docker", "exec"]
    for name in values:  # pass names only; values travel in env, never in argv
        args += ["-e", name]
    args += [container_id, "bash", target]
    return _run(args, env=env, check=check)


def _init_runtime(container_id: str, runtime_password: str) -> None:
    _exec_script(
        container_id,
        INIT_SCRIPT,
        {
            "POSTGRES_USER": "blackbread_migration",
            "POSTGRES_DB": "blackbread",
            "BLACKBREAD_RUNTIME_DB_PASSWORD": runtime_password,
        },
        check=True,
    )


def _reconcile(container_id: str, migration_password: str, runtime_password: str, *, check: bool):
    return _exec_script(
        container_id,
        RECONCILE_SCRIPT,
        {
            "POSTGRES_USER": "blackbread_migration",
            "POSTGRES_DB": "blackbread",
            "POSTGRES_MIGRATION_PASSWORD": migration_password,
            "BLACKBREAD_RUNTIME_DB_PASSWORD": runtime_password,
        },
        check=check,
    )


def _psql(container_id: str, sql: str) -> str:
    """Run SQL as the superuser over the trusted local socket; return one value."""
    result = _run(["docker", "exec", container_id, *_PSQL, sql, *_PSQL_CONN])
    return result.stdout.strip()


async def _wait_ready(port: int, password: str) -> None:
    """Poll until the final server accepts a superuser login (deterministic gate)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 90
    last: Exception | None = None
    while loop.time() < deadline:
        try:
            connection = await _connect(port, "blackbread_migration", password, connect_timeout=5)
            await connection.close()
            return
        except (OSError, asyncpg.PostgresError) as exc:  # not-yet-ready during init/restart
            last = exc
            await asyncio.sleep(0.5)  # readiness backoff, not a timing proof
    raise RuntimeError(f"database did not become ready on port {port}: {last!r}")


async def _can_authenticate(port: int, role: str, password: str) -> bool:
    try:
        connection = await _connect(port, role, password)
    except (asyncpg.InvalidPasswordError, asyncpg.InvalidAuthorizationSpecificationError):
        return False
    await connection.close()
    return True


def _seed_existing_state(container_id: str) -> None:
    """Create the recorder role, a runtime grant, sentinel data, and a revision row."""
    _psql(
        container_id,
        "CREATE ROLE blackbread_policy_recorder NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
        "NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1 PASSWORD NULL; "
        "CREATE TABLE sentinel (id int PRIMARY KEY, note text); "
        "INSERT INTO sentinel VALUES (1, 'keep-me'); "
        "GRANT SELECT ON sentinel TO blackbread_runtime; "
        "CREATE TABLE alembic_version (version_num varchar(32) NOT NULL); "
        "INSERT INTO alembic_version VALUES ('0008_m1_policy_recorder_identity');",
    )


def _preserved_state(container_id: str) -> str:
    """Capture everything reconciliation must leave unchanged (not the passwords)."""
    return _psql(
        container_id,
        "SELECT "
        "(SELECT id || ':' || note FROM sentinel), "
        "(SELECT version_num FROM alembic_version), "
        "(SELECT rolcanlogin::text || rolinherit || rolsuper || rolbypassrls || rolconnlimit "
        " || (rolpassword IS NOT NULL) FROM pg_authid "
        " WHERE rolname = 'blackbread_policy_recorder'), "
        "(SELECT count(*) FROM pg_auth_members m JOIN pg_authid r ON r.oid = m.roleid "
        " WHERE r.rolname = 'blackbread_policy_recorder'), "
        "(SELECT count(*) FROM pg_auth_members m "
        " JOIN pg_roles parent ON parent.oid = m.roleid "
        " JOIN pg_roles member ON member.oid = m.member "
        " WHERE parent.rolname = 'blackbread_runtime' AND member.rolname = 'blackbread_app'), "
        "has_table_privilege('blackbread_runtime', 'sentinel', 'SELECT'), "
        "(SELECT rolcanlogin::text || rolsuper FROM pg_authid WHERE rolname = 'blackbread_app'), "
        "(SELECT rolsuper::text FROM pg_authid WHERE rolname = 'blackbread_migration')",
    )


def _compose_env(**overrides: str | None) -> dict[str, str]:
    env = os.environ.copy()
    base = {
        "BLACKBREAD_ARTIFACT_KEY": "synthetic-key",
        "POSTGRES_MIGRATION_PASSWORD": _synthetic_password(),
        "BLACKBREAD_RUNTIME_DB_PASSWORD": _synthetic_password(),
    }
    for name, value in {**base, **overrides}.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return env


def _compose_config(env: Mapping[str, str]):
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "config", "--quiet"],
        cwd=ROOT,
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
        timeout=CONTAINER_TIMEOUT,
    )


@pytest.mark.parametrize(
    ("override", "expected_variable"),
    [
        ({"POSTGRES_MIGRATION_PASSWORD": None}, "POSTGRES_MIGRATION_PASSWORD"),
        ({"POSTGRES_MIGRATION_PASSWORD": ""}, "POSTGRES_MIGRATION_PASSWORD"),
        ({"BLACKBREAD_RUNTIME_DB_PASSWORD": None}, "BLACKBREAD_RUNTIME_DB_PASSWORD"),
        ({"BLACKBREAD_RUNTIME_DB_PASSWORD": ""}, "BLACKBREAD_RUNTIME_DB_PASSWORD"),
    ],
)
def test_compose_fails_closed_on_missing_or_empty_credential(
    override: dict[str, str | None], expected_variable: str
) -> None:
    result = _compose_config(_compose_env(**override))
    assert result.returncode != 0
    assert expected_variable in result.stderr


def test_compose_accepts_supplied_credentials_without_rendering_them() -> None:
    result = _compose_config(_compose_env())
    assert result.returncode == 0
    # --quiet validates without emitting rendered configuration containing credentials.
    assert result.stdout.strip() == ""


def test_compose_grants_runtime_to_api_and_migration_to_migrate() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    api_url = services["api"]["environment"]["BLACKBREAD_DATABASE_URL"]
    migrate_url = services["migrate"]["environment"]["BLACKBREAD_DATABASE_URL"]
    assert api_url.startswith("postgresql+asyncpg://blackbread_app:")
    assert migrate_url.startswith("postgresql+asyncpg://blackbread_migration:")
    # No literal password fallback survives; empty or missing values fail closed.
    for url in (api_url, migrate_url):
        assert ":-" not in url
        assert ":?" in url


async def test_fresh_volume_bootstraps_from_supplied_credentials() -> None:
    migration_password = _synthetic_password()
    runtime_password = _synthetic_password()
    with postgres_container(migration_password) as container_id:
        port = _host_port(container_id)
        await _wait_ready(port, migration_password)
        _init_runtime(container_id, runtime_password)

        assert await _can_authenticate(port, "blackbread_migration", migration_password)
        assert await _can_authenticate(port, "blackbread_app", runtime_password)
        assert not await _can_authenticate(port, "blackbread_migration", OLD_MIGRATION)
        assert not await _can_authenticate(port, "blackbread_app", OLD_RUNTIME)

        _psql(container_id, "CREATE TABLE sentinel (id int PRIMARY KEY, note text)")
        await _assert_no_migration_authority(port, runtime_password)


async def _assert_no_migration_authority(port: int, runtime_password: str) -> None:
    connection = await _connect(port, "blackbread_app", runtime_password)
    try:
        for statement in (
            "CREATE TABLE forbidden (id int)",
            "INSERT INTO sentinel VALUES (1, 'x')",
            "DROP TABLE sentinel",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(statement)
    finally:
        await connection.close()


async def test_existing_volume_reconciliation_rotates_and_preserves() -> None:
    new_migration = _synthetic_password()
    new_runtime = _synthetic_password()
    with postgres_container(OLD_MIGRATION) as container_id:
        port = _host_port(container_id)
        await _wait_ready(port, OLD_MIGRATION)
        _init_runtime(container_id, OLD_RUNTIME)
        _seed_existing_state(container_id)
        before = _preserved_state(container_id)

        _reconcile(container_id, new_migration, new_runtime, check=True)

        assert await _can_authenticate(port, "blackbread_migration", new_migration)
        assert await _can_authenticate(port, "blackbread_app", new_runtime)
        assert not await _can_authenticate(port, "blackbread_migration", OLD_MIGRATION)
        assert not await _can_authenticate(port, "blackbread_app", OLD_RUNTIME)

        assert _preserved_state(container_id) == before
        _assert_authority_separation(container_id)


def _assert_authority_separation(container_id: str) -> None:
    facts = _psql(
        container_id,
        "SELECT "
        "(SELECT rolcanlogin::text || (rolpassword IS NOT NULL)::text FROM pg_authid "
        " WHERE rolname = 'blackbread_policy_recorder'), "
        "(SELECT count(*) FROM pg_auth_members m JOIN pg_authid r ON r.oid = m.roleid "
        " WHERE r.rolname = 'blackbread_policy_recorder'), "
        "(SELECT rolcanlogin::text || rolsuper::text FROM pg_authid "
        " WHERE rolname = 'blackbread_app'), "
        "(SELECT rolsuper::text FROM pg_authid WHERE rolname = 'blackbread_migration')",
    )
    # recorder NOLOGIN and credential-free | recorder memberships |
    # app is a runtime login, never superuser | migration retains superuser authority
    assert facts == "falsefalse|0|truefalse|true"


async def test_reconciliation_rolls_back_first_change_when_second_role_missing() -> None:
    original_migration = _synthetic_password()
    original_runtime = _synthetic_password()
    new_migration = _synthetic_password()
    new_runtime = _synthetic_password()
    with postgres_container(original_migration) as container_id:
        port = _host_port(container_id)
        await _wait_ready(port, original_migration)
        _init_runtime(container_id, original_runtime)
        # Force the second rotation (blackbread_app) to fail deterministically.
        _psql(container_id, "DROP ROLE blackbread_app")

        result = _reconcile(container_id, new_migration, new_runtime, check=False)
        assert result.returncode != 0

        # The first rotation must have rolled back: old works, new never took effect.
        assert await _can_authenticate(port, "blackbread_migration", original_migration)
        assert not await _can_authenticate(port, "blackbread_migration", new_migration)


async def test_active_runtime_session_refuses_reconciliation() -> None:
    original_migration = _synthetic_password()
    original_runtime = _synthetic_password()
    new_migration = _synthetic_password()
    new_runtime = _synthetic_password()
    with postgres_container(original_migration) as container_id:
        port = _host_port(container_id)
        await _wait_ready(port, original_migration)
        _init_runtime(container_id, original_runtime)

        holder = await _connect(port, "blackbread_app", original_runtime)
        try:
            # Deterministic oracle: the session is present before reconciliation runs.
            active = _psql(
                container_id,
                "SELECT count(*) FROM pg_stat_activity WHERE usename = 'blackbread_app'",
            )
            assert int(active) >= 1

            result = _reconcile(container_id, new_migration, new_runtime, check=False)
            assert result.returncode != 0
            assert "active" in (result.stderr + result.stdout).lower()

            # No password changed: originals still authenticate, new values do not.
            assert await _can_authenticate(port, "blackbread_migration", original_migration)
            assert not await _can_authenticate(port, "blackbread_migration", new_migration)
        finally:
            await holder.close()
