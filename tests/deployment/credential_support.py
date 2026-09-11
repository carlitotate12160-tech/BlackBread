"""Shared helpers for disposable-PostgreSQL credential proofs.

These helpers back the deployment test modules. They use disposable,
loopback-only PostgreSQL containers (no mocks for authentication, the role
catalog, or transactional rotation) and the actual canonical Compose file and
deploy scripts. All credentials are synthetic per-run values; no real or
repository-known secret is used, printed, or asserted.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import subprocess
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path

import asyncpg
import yaml

ROOT = Path(__file__).parents[2]
COMPOSE = ROOT / "compose.yaml"
INIT_SCRIPT = ROOT / "deploy" / "postgres" / "init-runtime.sh"
RECONCILE_SCRIPT = ROOT / "deploy" / "postgres" / "reconcile-credentials.sh"
IMAGE = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["database"]["image"]

# These two constants must match deploy/postgres/reconcile-credentials.sh: the
# maintenance identity is the local-socket-only superuser with no usable TCP
# password, and the advisory-lock key serializes reconciliation runs.
MAINT_ROLE = "blackbread_maint"
ADVISORY_LOCK_KEY = 727274

# Synthetic pre-rotation credentials standing in for whatever a pre-existing volume or a
# repository-derived guess might hold. They are asserted to fail after bootstrap/rotation;
# no real or repository-known credential is placed in the repository.
OLD_MIGRATION = "old_" + secrets.token_hex(8)
OLD_RUNTIME = "old_" + secrets.token_hex(8)

# Reserved DSN characters a deployment password may legitimately contain. The
# credential must survive verbatim through Settings, URL construction, and
# PostgreSQL authentication without any percent-encoding of the server-side value.
SPECIAL_PASSWORD = "syn" + secrets.token_hex(4) + ":P@ss/w?rd#%!"

CONTAINER_TIMEOUT = 300

# Static docker/psql fragments shared by the helpers below.
_DB_ENV = ["-e", "POSTGRES_USER=blackbread_migration", "-e", "POSTGRES_DB=blackbread"]
_PSQL = ["psql", "-v", "ON_ERROR_STOP=1", "--no-psqlrc", "-tAqc"]
_PSQL_CONN = ["-U", "blackbread_migration", "-d", "blackbread"]


def synthetic_password() -> str:
    """A unique, synthetic credential that never appears in the repository."""
    return "syn_" + secrets.token_hex(16)


def _run(
    args: list[str], *, env: Mapping[str, str] | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
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


def host_port(container_id: str) -> int:
    mapping = _run(["docker", "port", container_id, "5432/tcp"]).stdout.strip()
    return int(mapping.splitlines()[0].rsplit(":", 1)[1])


async def connect(
    port: int, role: str, password: str, *, connect_timeout: int = 10
) -> asyncpg.Connection:
    return await asyncpg.connect(
        host="127.0.0.1",
        port=port,
        user=role,
        password=password,
        database="blackbread",
        timeout=connect_timeout,
    )


def exec_script(
    container_id: str, script: Path, values: Mapping[str, str], *, check: bool
) -> subprocess.CompletedProcess[str]:
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


def init_runtime(container_id: str, runtime_password: str) -> None:
    exec_script(
        container_id,
        INIT_SCRIPT,
        {
            "POSTGRES_USER": "blackbread_migration",
            "POSTGRES_DB": "blackbread",
            "BLACKBREAD_RUNTIME_DB_PASSWORD": runtime_password,
        },
        check=True,
    )


def reconcile(
    container_id: str, migration_password: str, runtime_password: str, *, check: bool
) -> subprocess.CompletedProcess[str]:
    return exec_script(
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


def psql(container_id: str, sql: str, *, user: str = "blackbread_migration") -> str:
    """Run SQL as the given role over the trusted local socket; return one value."""
    result = _run(["docker", "exec", container_id, *_PSQL, sql, "-U", user, "-d", "blackbread"])
    return result.stdout.strip()


async def wait_ready(port: int, password: str) -> None:
    """Poll until the final server accepts a superuser login (deterministic gate)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 90
    last: Exception | None = None
    while loop.time() < deadline:
        try:
            connection = await connect(port, "blackbread_migration", password, connect_timeout=5)
            await connection.close()
            return
        except (OSError, asyncpg.PostgresError) as exc:  # not-yet-ready during init/restart
            last = exc
            await asyncio.sleep(0.5)  # readiness backoff, not a timing proof
    raise RuntimeError(f"database did not become ready on port {port}: {last!r}")


async def can_authenticate(port: int, role: str, password: str) -> bool:
    try:
        connection = await connect(port, role, password)
    except (asyncpg.InvalidPasswordError, asyncpg.InvalidAuthorizationSpecificationError):
        return False
    await connection.close()
    return True


def seed_existing_state(container_id: str) -> None:
    """Create the recorder role, a runtime grant, sentinel data, and a revision row."""
    psql(
        container_id,
        "CREATE ROLE blackbread_policy_recorder NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
        "NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1 PASSWORD NULL; "
        "CREATE TABLE sentinel (id int PRIMARY KEY, note text); "
        "INSERT INTO sentinel VALUES (1, 'keep-me'); "
        "GRANT SELECT ON sentinel TO blackbread_runtime; "
        "CREATE TABLE alembic_version (version_num varchar(32) NOT NULL); "
        "INSERT INTO alembic_version VALUES ('0008_m1_policy_recorder_identity');",
    )


def preserved_state(container_id: str) -> str:
    """Capture everything reconciliation must leave unchanged (not the passwords)."""
    return psql(
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


def compose_env(**overrides: str | None) -> dict[str, str]:
    env = os.environ.copy()
    base = {
        "BLACKBREAD_ARTIFACT_KEY": "synthetic-key",
        "POSTGRES_MIGRATION_PASSWORD": synthetic_password(),
        "BLACKBREAD_RUNTIME_DB_PASSWORD": synthetic_password(),
    }
    for name, value in {**base, **overrides}.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return env


def compose_config(env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    # `docker compose config` auto-loads ROOT/.env; point --env-file at an empty file so the
    # proof depends only on the supplied process environment, never on a developer's local .env.
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as empty_env:
        empty_env_path = empty_env.name
    try:
        return subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                empty_env_path,
                "-f",
                str(COMPOSE),
                "config",
                "--quiet",
            ],
            cwd=ROOT,
            env=dict(env),
            check=False,
            capture_output=True,
            text=True,
            timeout=CONTAINER_TIMEOUT,
        )
    finally:
        os.unlink(empty_env_path)
