from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

EXPECTED_SCHEMA_REVISION = "0002_m1_ledger"
UNDEFINED_TABLE_SQLSTATE = "42P01"


@dataclass(frozen=True)
class Readiness:
    ready: bool
    database: str
    migrations: str


def _is_undefined_table(error: SQLAlchemyError) -> bool:
    original = getattr(error, "orig", None)
    return getattr(original, "sqlstate", None) == UNDEFINED_TABLE_SQLSTATE


async def check_readiness(engine: AsyncEngine) -> Readiness:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            try:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            except SQLAlchemyError as exc:
                migration_state = "missing" if _is_undefined_table(exc) else "error"
                return Readiness(
                    ready=False,
                    database="available",
                    migrations=migration_state,
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
