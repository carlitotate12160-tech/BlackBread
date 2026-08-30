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
    read or write across every tenant. Membership in any parent role is rejected
    too, because the runtime role could ``SET ROLE`` to a parent that bypasses RLS,
    so the migration refuses to proceed.
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
    parent = connection.execute(
        text(
            "SELECT parent.rolname "
            "FROM pg_auth_members AS membership "
            "JOIN pg_roles AS child ON child.oid = membership.member "
            "JOIN pg_roles AS parent ON parent.oid = membership.roleid "
            "WHERE child.rolname = :name "
            "LIMIT 1"
        ),
        {"name": role_name},
    ).scalar()
    if parent is not None:
        raise RuntimeError(f"role {role_name} must not inherit or assume another role")
