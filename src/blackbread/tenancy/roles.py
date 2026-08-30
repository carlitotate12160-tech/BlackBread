from sqlalchemy import text
from sqlalchemy.engine import Connection

RUNTIME_ROLE = "blackbread_runtime"


def require_isolatable_runtime_role(
    connection: Connection,
    *,
    role_name: str = RUNTIME_ROLE,
) -> None:
    """Fail closed unless ``role_name`` exists and cannot bypass row-level security.

    A missing role, a superuser, or a role holding ``BYPASSRLS`` would silently
    read or write across every tenant, so the migration refuses to proceed.
    """

    row = (
        connection.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :name"),
            {"name": role_name},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise RuntimeError(f"required role {role_name} does not exist")
    if row["rolsuper"] or row["rolbypassrls"]:
        raise RuntimeError(f"role {role_name} must not be able to bypass row-level security")
