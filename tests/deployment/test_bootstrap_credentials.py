"""Fresh-volume bootstrap proofs for the database credential bootstrap.

Proof map:
  C   a fresh volume bootstraps from supplied credentials; a non-supplied
      credential fails; the runtime login cannot perform migration-owner
      operations
  I   a password containing reserved DSN characters (: @ / ? # %) is preserved
      verbatim through init, Settings component mode, URL construction, and a
      live authentication

All credentials are synthetic per-run values; no real or repository-known secret
is used, printed, or asserted.
"""

from __future__ import annotations

import asyncpg
import pytest
from sqlalchemy import text

from blackbread.config import Settings
from blackbread.database import create_engine
from tests.deployment.credential_support import (
    CONTAINER_TIMEOUT,
    OLD_MIGRATION,
    OLD_RUNTIME,
    SPECIAL_PASSWORD,
    can_authenticate,
    connect,
    host_port,
    init_runtime,
    postgres_container,
    psql,
    synthetic_password,
    wait_ready,
)

pytestmark = pytest.mark.timeout(CONTAINER_TIMEOUT)


async def test_fresh_volume_bootstraps_from_supplied_credentials() -> None:
    migration_password = synthetic_password()
    runtime_password = synthetic_password()
    with postgres_container(migration_password) as container_id:
        port = host_port(container_id)
        await wait_ready(port, migration_password)
        init_runtime(container_id, runtime_password)

        assert await can_authenticate(port, "blackbread_migration", migration_password)
        assert await can_authenticate(port, "blackbread_app", runtime_password)
        assert not await can_authenticate(port, "blackbread_migration", OLD_MIGRATION)
        assert not await can_authenticate(port, "blackbread_app", OLD_RUNTIME)

        psql(container_id, "CREATE TABLE sentinel (id int PRIMARY KEY, note text)")
        await _assert_no_migration_authority(port, runtime_password)


async def _assert_no_migration_authority(port: int, runtime_password: str) -> None:
    connection = await connect(port, "blackbread_app", runtime_password)
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


async def test_reserved_character_password_authenticates_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A password holding every reserved DSN character authenticates end to end.

    The value is stored raw by init (server-side password is never
    percent-encoded) and reaches the driver through the component-mode
    Settings -> sqlalchemy.engine.URL.create -> engine path, proving no raw
    string interpolation can silently alter it.
    """
    migration_password = synthetic_password()
    with postgres_container(migration_password) as container_id:
        port = host_port(container_id)
        await wait_ready(port, migration_password)
        init_runtime(container_id, SPECIAL_PASSWORD)

        # Direct driver authentication proves the server-side value is verbatim.
        assert await can_authenticate(port, "blackbread_app", SPECIAL_PASSWORD)

        # The application path: components -> URL.create -> engine must preserve
        # the password exactly and authenticate against the live server.
        # Ambient BLACKBREAD_DATABASE_URL would make this configuration ambiguous.
        monkeypatch.delenv("BLACKBREAD_DATABASE_URL", raising=False)
        settings = Settings(
            _env_file=None,
            artifact_key="synthetic",
            db_user="blackbread_app",
            db_password=SPECIAL_PASSWORD,
            db_host="127.0.0.1",
            db_port=port,
            db_name="blackbread",
        )
        engine = create_engine(settings)
        try:
            assert engine.url.password == SPECIAL_PASSWORD
            async with engine.connect() as connection:
                assert (await connection.execute(text("SELECT 1"))).scalar() == 1
        finally:
            await engine.dispose()
