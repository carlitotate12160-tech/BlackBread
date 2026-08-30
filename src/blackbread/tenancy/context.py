from dataclasses import dataclass

from blackbread.tenancy.errors import TenantContextError

TENANT_GUC = "blackbread.tenant_id"
MAX_TENANT_ID_LENGTH = 100


def _validated_tenant_id(value: str) -> str:
    if not isinstance(value, str):
        raise TenantContextError("tenant_id must be a string")
    if not value.strip():
        raise TenantContextError("tenant_id must be a non-blank string")
    if len(value) > MAX_TENANT_ID_LENGTH:
        raise TenantContextError(f"tenant_id exceeds {MAX_TENANT_ID_LENGTH} characters")
    if "\x00" in value:
        raise TenantContextError("tenant_id contains a NUL character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise TenantContextError("tenant_id contains invalid Unicode") from exc
    return value


@dataclass(frozen=True, slots=True)
class TenantContext:
    """A validated tenant identity bound to a single PostgreSQL transaction."""

    tenant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _validated_tenant_id(self.tenant_id))
