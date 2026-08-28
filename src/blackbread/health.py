from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

EXPECTED_SCHEMA_REVISION = "0002_m1_ledger"


@dataclass(frozen=True)
class Readiness:
    ready: bool
    database: str
    migrations: str


async def check_readiness(engine: AsyncEngine) -> Readiness:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            try:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            except SQLAlchemyError:
                return Readiness(
                    ready=False,
                    database="available",
                    migrations="missing",
                )
    except SQLAlchemyError:
        return Readiness(ready=False, database="unavailable", migrations="unknown")

    if not revision:
        return Readiness(ready=False, database="available", migrations="missing")
    if revision != EXPECTED_SCHEMA_REVISION:
        return Readiness(
            ready=False,
            database="available",
            migrations=str(revision),
        )
    return Readiness(ready=True, database="available", migrations=str(revision))
