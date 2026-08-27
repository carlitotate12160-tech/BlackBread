from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from blackbread.health import check_readiness


@pytest.mark.asyncio
async def test_readiness_reports_missing_migration() -> None:
    connection = AsyncMock()
    connection.scalar.return_value = None
    context = AsyncMock()
    context.__aenter__.return_value = connection
    engine = MagicMock()
    engine.connect.return_value = context

    readiness = await check_readiness(engine)

    assert readiness.ready is False
    assert readiness.database == "available"
    assert readiness.migrations == "missing"


@pytest.mark.asyncio
async def test_readiness_handles_database_errors() -> None:
    context = AsyncMock()
    context.__aenter__.side_effect = OperationalError("SELECT 1", {}, Exception("offline"))
    engine = MagicMock()
    engine.connect.return_value = context

    readiness = await check_readiness(engine)

    assert readiness.ready is False
    assert readiness.database == "unavailable"
