from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from blackbread.health import EXPECTED_SCHEMA_REVISION, check_readiness


class UndefinedTableError(Exception):
    sqlstate = "42P01"


def _engine_with_revisions(*revisions: str) -> MagicMock:
    result = MagicMock()
    result.all.return_value = list(revisions)
    connection = AsyncMock()
    connection.scalars.return_value = result
    context = AsyncMock()
    context.__aenter__.return_value = connection
    engine = MagicMock()
    engine.connect.return_value = context
    return engine


@pytest.mark.asyncio
async def test_readiness_reports_missing_migration() -> None:
    readiness = await check_readiness(_engine_with_revisions())

    assert readiness.ready is False
    assert readiness.database == "available"
    assert readiness.migrations == "missing"


@pytest.mark.asyncio
async def test_readiness_accepts_only_current_migration_head() -> None:
    readiness = await check_readiness(_engine_with_revisions(EXPECTED_SCHEMA_REVISION))

    assert readiness.ready is True
    assert readiness.migrations == EXPECTED_SCHEMA_REVISION


@pytest.mark.asyncio
async def test_readiness_rejects_outdated_migration() -> None:
    readiness = await check_readiness(_engine_with_revisions("0001_m0_bootstrap"))

    assert readiness.ready is False
    assert readiness.database == "available"
    assert readiness.migrations == "0001_m0_bootstrap"


@pytest.mark.asyncio
async def test_readiness_rejects_extra_migration_heads() -> None:
    readiness = await check_readiness(
        _engine_with_revisions(EXPECTED_SCHEMA_REVISION, "unexpected_head")
    )

    assert readiness.ready is False
    assert readiness.database == "available"
    assert readiness.migrations == f"{EXPECTED_SCHEMA_REVISION},unexpected_head"


@pytest.mark.asyncio
async def test_readiness_reports_missing_migration_table() -> None:
    connection = AsyncMock()
    connection.scalars.side_effect = ProgrammingError(
        "SELECT version_num",
        {},
        UndefinedTableError(),
    )
    context = AsyncMock()
    context.__aenter__.return_value = connection
    engine = MagicMock()
    engine.connect.return_value = context

    readiness = await check_readiness(engine)

    assert readiness.ready is False
    assert readiness.database == "available"
    assert readiness.migrations == "missing"


@pytest.mark.asyncio
async def test_readiness_distinguishes_migration_query_errors() -> None:
    connection = AsyncMock()
    connection.scalars.side_effect = OperationalError(
        "SELECT version_num",
        {},
        Exception("permission denied"),
    )
    context = AsyncMock()
    context.__aenter__.return_value = connection
    engine = MagicMock()
    engine.connect.return_value = context

    readiness = await check_readiness(engine)

    assert readiness.ready is False
    assert readiness.database == "available"
    assert readiness.migrations == "error"


@pytest.mark.asyncio
async def test_readiness_reports_invalidated_migration_connection() -> None:
    connection = AsyncMock()
    connection.scalars.side_effect = OperationalError(
        "SELECT version_num",
        {},
        Exception("connection lost"),
        connection_invalidated=True,
    )
    context = AsyncMock()
    context.__aenter__.return_value = connection
    engine = MagicMock()
    engine.connect.return_value = context

    readiness = await check_readiness(engine)

    assert readiness.ready is False
    assert readiness.database == "unavailable"
    assert readiness.migrations == "unknown"


@pytest.mark.asyncio
async def test_readiness_handles_database_errors() -> None:
    context = AsyncMock()
    context.__aenter__.side_effect = OperationalError("SELECT 1", {}, Exception("offline"))
    engine = MagicMock()
    engine.connect.return_value = context

    readiness = await check_readiness(engine)

    assert readiness.ready is False
    assert readiness.database == "unavailable"
