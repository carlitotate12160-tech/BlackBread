from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

EXPECTED_SCHEMA_REVISION = "0006_m1_temporal_scope_graph"
UNDEFINED_TABLE_SQLSTATE = "42P01"


@dataclass(frozen=True)
class Readiness:
    ready: bool
    database: str
    migrations: str


def _is_undefined_table(error: SQLAlchemyError) -> bool:
    original = getattr(error, "orig", None)
    return getattr(original, "sqlstate", None) == UNDEFINED_TABLE_SQLSTATE


def _is_connection_failure(error: SQLAlchemyError) -> bool:
    return bool(getattr(error, "connection_invalidated", False))


async def check_readiness(engine: AsyncEngine) -> Readiness:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            try:
                result = await connection.scalars(text("SELECT version_num FROM alembic_version"))
                revisions = {str(revision) for revision in result.all()}
            except SQLAlchemyError as exc:
                if _is_connection_failure(exc):
                    return Readiness(
                        ready=False,
                        database="unavailable",
                        migrations="unknown",
                    )
                migration_state = "missing" if _is_undefined_table(exc) else "error"
                return Readiness(
                    ready=False,
                    database="available",
                    migrations=migration_state,
                )
    except SQLAlchemyError:
        return Readiness(ready=False, database="unavailable", migrations="unknown")

    if not revisions:
        return Readiness(ready=False, database="available", migrations="missing")
    expected = {EXPECTED_SCHEMA_REVISION}
    if revisions != expected:
        return Readiness(
            ready=False,
            database="available",
            migrations=",".join(sorted(revisions)),
        )
    return Readiness(
        ready=True,
        database="available",
        migrations=EXPECTED_SCHEMA_REVISION,
    )
