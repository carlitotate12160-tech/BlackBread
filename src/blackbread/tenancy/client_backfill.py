from collections.abc import Iterable, Sequence
from uuid import UUID


class AmbiguousClientTenantError(RuntimeError):
    """Raised when a client's tenant ownership cannot be resolved deterministically."""


def resolve_client_tenants(
    pairs: Sequence[tuple[UUID, str]],
    *,
    orphan_client_ids: Iterable[UUID] = (),
) -> dict[UUID, str]:
    """Resolve one tenant per client, failing closed on ambiguous ownership.

    ``pairs`` are observed ``(client_id, tenant_id)`` links. A client bound to
    exactly one distinct tenant is assigned deterministically; a client bound to
    zero tenants (``orphan_client_ids``) or to multiple distinct tenants is
    ambiguous and never guessed.
    """

    tenants_by_client: dict[UUID, set[str]] = {}
    for client_id, tenant_id in pairs:
        tenants_by_client.setdefault(client_id, set()).add(tenant_id)
    ambiguous = {client_id for client_id, tenants in tenants_by_client.items() if len(tenants) != 1}
    ambiguous.update(orphan_client_ids)
    if ambiguous:
        listed = ", ".join(str(client_id) for client_id in sorted(ambiguous, key=str))
        raise AmbiguousClientTenantError(
            f"cannot deterministically assign tenant ownership for clients: {listed}"
        )
    return {client_id: next(iter(tenants)) for client_id, tenants in tenants_by_client.items()}
