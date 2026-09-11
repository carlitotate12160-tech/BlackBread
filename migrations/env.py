import asyncio
from importlib import import_module
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from blackbread.config import get_settings
from blackbread.models.base import Base

MODEL_MODULES = (
    "blackbread.models.core",
    "blackbread.ledger.event",
    "blackbread.models.policy_records",
)
for model_module in MODEL_MODULES:
    import_module(model_module)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
# The URL object is passed through directly: the password is never rendered into
# the alembic ini or any string, so reserved characters cannot be altered.
DATABASE_URL = get_settings().sqlalchemy_url()
target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(DATABASE_URL, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
