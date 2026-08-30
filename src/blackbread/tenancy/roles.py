from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

RUNTIME_ROLE = "blackbread_runtime"

_ROLE_FLAGS = text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :name")
_PARENT_ROLE = text(
    "SELECT parent.rolname "
    "FROM pg_auth_members AS membership "
    "JOIN pg_roles AS child ON child.oid = membership.member "
    "JOIN pg_roles AS parent ON parent.oid = membership.roleid "
    "WHERE child.rolname = :name "
    "LIMIT 1"
)


@dataclass(frozen=True, slots=True)
class RuntimeRoleFacts:
    """The role attributes needed to decide whether a runtime role isolates tenants."""

    role_name: str
    exists: bool
    can_bypass_rls: bool
    has_parent_role: bool


def check_runtime_role_isolatable(facts: RuntimeRoleFacts) -> None:
    """Fail closed unless the role exists and cannot escape row-level security.

    Pure policy decision over already-loaded facts. A missing role, a superuser or
    ``BYPASSRLS`` holder, or membership in any parent role (which the runtime role
    could ``SET ROLE`` to and bypass RLS) is rejected.
    """

    if not facts.exists:
        raise RuntimeError(f"required role {facts.role_name} does not exist")
    if facts.can_bypass_rls:
        raise RuntimeError(f"role {facts.role_name} must not be able to bypass row-level security")
    if facts.has_parent_role:
        raise RuntimeError(f"role {facts.role_name} must not inherit or assume another role")


def _load_runtime_role_facts(connection: Connection, role_name: str) -> RuntimeRoleFacts:
    row = connection.execute(_ROLE_FLAGS, {"name": role_name}).mappings().one_or_none()
    if row is None:
        return RuntimeRoleFacts(
            role_name, exists=False, can_bypass_rls=False, has_parent_role=False
        )
    parent = connection.execute(_PARENT_ROLE, {"name": role_name}).scalar()
    return RuntimeRoleFacts(
        role_name=role_name,
        exists=True,
        can_bypass_rls=bool(row["rolsuper"] or row["rolbypassrls"]),
        has_parent_role=parent is not None,
    )


def require_isolatable_runtime_role(
    connection: Connection,
    *,
    role_name: str = RUNTIME_ROLE,
) -> None:
    """Load the runtime role's facts and enforce the isolation policy, fail-closed."""

    check_runtime_role_isolatable(_load_runtime_role_facts(connection, role_name))
