from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from blackbread.tenancy.context import TENANT_GUC, TenantContext

TenantBinder = AsyncSession | AsyncConnection

_SET_TENANT = text("SELECT set_config(:name, :value, true)")


async def bind_tenant_context(binder: TenantBinder, context: TenantContext) -> None:
    """Bind the tenant context to the binder's active transaction.

    Uses a transaction-local GUC (``set_config(..., is_local => true)``) so the
    context is cleared automatically on commit, rollback, and pooled-connection
    return. It is never established as session-global state.
    """

    await binder.execute(_SET_TENANT, {"name": TENANT_GUC, "value": context.tenant_id})


@asynccontextmanager
async def tenant_transaction(
    session: AsyncSession,
    context: TenantContext,
) -> AsyncIterator[AsyncSession]:
    """Open a transaction bound to ``context`` and clear it on exit.

    The transaction commits on clean exit and rolls back on error; either way the
    transaction-local tenant GUC is discarded when the transaction ends.
    """

    async with session.begin():
        await bind_tenant_context(session, context)
        yield session
