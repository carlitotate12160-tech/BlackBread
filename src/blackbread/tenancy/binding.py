from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from blackbread.tenancy.context import TENANT_GUC, TenantContext
from blackbread.tenancy.errors import TenantContextError

TenantBinder = AsyncSession | AsyncConnection

_SET_TENANT = text("SELECT set_config(:name, :value, true)")
_CURRENT_TENANT = text("SELECT current_setting(:name, true)")


async def bind_tenant_context(binder: TenantBinder, context: TenantContext) -> None:
    """Bind the tenant context to the binder's active transaction, immutably.

    Uses a transaction-local GUC (``set_config(..., is_local => true)``) so the
    context is cleared automatically on commit, rollback, and pooled-connection
    return; it is never established as session-global state. Binding is immutable
    within a transaction: an unset context is bound, an identical context is an
    idempotent no-op, and any attempt to rebind to a different tenant fails closed.
    """

    existing = (await binder.execute(_CURRENT_TENANT, {"name": TENANT_GUC})).scalar_one()
    if existing not in (None, ""):
        if existing == context.tenant_id:
            return
        raise TenantContextError("tenant context is already bound to a different tenant")
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
