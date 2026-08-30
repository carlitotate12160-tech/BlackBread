import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from blackbread.tenancy.roles import require_isolatable_runtime_role


def _check(connection: Connection, role_name: str) -> None:
    require_isolatable_runtime_role(connection, role_name=role_name)


async def test_missing_runtime_role_is_rejected(admin_session: AsyncSession) -> None:
    missing = f"probe_missing_{uuid.uuid4().hex[:8]}"
    connection = await admin_session.connection()
    with pytest.raises(RuntimeError, match="does not exist"):
        await connection.run_sync(_check, missing)
    await admin_session.rollback()


async def test_superuser_runtime_role_is_rejected(admin_session: AsyncSession) -> None:
    probe = f"probe_super_{uuid.uuid4().hex[:8]}"
    await admin_session.execute(text(f"CREATE ROLE {probe} SUPERUSER NOLOGIN"))
    connection = await admin_session.connection()
    try:
        with pytest.raises(RuntimeError, match="bypass"):
            await connection.run_sync(_check, probe)
    finally:
        await admin_session.rollback()


async def test_bypassrls_runtime_role_is_rejected(admin_session: AsyncSession) -> None:
    probe = f"probe_bypass_{uuid.uuid4().hex[:8]}"
    await admin_session.execute(text(f"CREATE ROLE {probe} BYPASSRLS NOLOGIN"))
    connection = await admin_session.connection()
    try:
        with pytest.raises(RuntimeError, match="bypass"):
            await connection.run_sync(_check, probe)
    finally:
        await admin_session.rollback()


async def test_isolatable_runtime_role_passes(admin_session: AsyncSession) -> None:
    probe = f"probe_ok_{uuid.uuid4().hex[:8]}"
    await admin_session.execute(text(f"CREATE ROLE {probe} NOLOGIN NOSUPERUSER NOBYPASSRLS"))
    connection = await admin_session.connection()
    try:
        await connection.run_sync(_check, probe)
    finally:
        await admin_session.rollback()


async def test_runtime_login_is_not_superuser_and_lacks_bypassrls(session: AsyncSession) -> None:
    row = (
        await session.execute(
            text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
        )
    ).one()
    assert row.rolsuper is False
    assert row.rolbypassrls is False


async def test_runtime_login_cannot_assume_migration_authority(session: AsyncSession) -> None:
    with pytest.raises((ProgrammingError, DBAPIError)):
        await session.execute(text("SET ROLE postgres"))
    await session.rollback()
