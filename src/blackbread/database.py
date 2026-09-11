from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from blackbread.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    # The URL object carries the password verbatim; it is never rendered to a
    # string here, so reserved characters cannot be silently altered.
    return create_async_engine(settings.sqlalchemy_url(), pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
