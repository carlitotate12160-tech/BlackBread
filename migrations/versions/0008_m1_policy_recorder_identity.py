"""M1.4c2b0a inert PostgreSQL policy-recorder role identity foundation.

Creates or validates exactly one cluster-wide, inert role named ``blackbread_policy_recorder``. This
slice owns *only* the role identity: the role is created NOLOGIN / NOINHERIT / NOSUPERUSER /
NOCREATEDB / NOCREATEROLE / NOREPLICATION / NOBYPASSRLS with ``CONNECTION LIMIT -1`` and a NULL
password, and it receives no grant, ownership, default ACL, RLS policy, membership, or role setting
from this migration.

The role is intentionally not wired to any production entry point. Its safety here is *non-reachability*:
it cannot log in, no application/runtime login is a member of it, and it holds no privilege, so no
ordinary BlackBread identity can ``SET ROLE`` to it. PUBLIC ambient privileges are **not** claimed
absent by this slice — the later M1.4c2b0b writer slice must explicitly define PUBLIC revocation, the
exact grants, RLS, lineage, and the assumption/credential boundary before any use.

Direct dependency is checked through PostgreSQL's cluster-wide ``pg_shdepend`` shared-dependency
authority rather than by enumerating individual object catalogs, so an owned table, schema, routine,
grant, default ACL, or RLS reference in *any* database in the cluster is detected uniformly. Role
attributes, ``pg_db_role_setting`` entries, and ``pg_auth_members`` edges are checked separately.

If the role is absent it is created. If it already exists in exactly the inert, dependency-free shape
this migration owns, it is left unchanged (its OID is preserved). Any other shape aborts fail-closed
without normalising, revoking, reassigning, or dropping anything. Role creation and the Alembic
version advance occur in one PostgreSQL transaction (see ``migrations/env.py``), so an aborted upgrade
leaves both the role and ``alembic_version`` unchanged. A trusted, exclusive migration administrator
is an operational precondition; this slice does not claim protection against a concurrent PostgreSQL
superuser.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "0008_m1_policy_recorder_identity"
down_revision: str | None = "0007_m1_policy_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECORDER_ROLE = "blackbread_policy_recorder"

# The exact inert attribute contract: (human label, RecorderRoleState field, required value).
_INERT_ATTRIBUTES: tuple[tuple[str, str, object], ...] = (
    ("LOGIN", "can_login", False),
    ("INHERIT", "inherits", False),
    ("SUPERUSER", "is_superuser", False),
    ("CREATEDB", "can_create_db", False),
    ("CREATEROLE", "can_create_role", False),
    ("REPLICATION", "can_replicate", False),
    ("BYPASSRLS", "can_bypass_rls", False),
    ("CONNECTION LIMIT", "connection_limit", -1),
    ("PASSWORD", "has_password", False),
    ("VALID UNTIL", "has_validity", False),
)

_CREATE_RECORDER = (
    f"CREATE ROLE {RECORDER_ROLE} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
    "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1 PASSWORD NULL"
)

_ROLE_ATTRIBUTES = sa.text(
    "SELECT oid, rolcanlogin, rolinherit, rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
    "rolbypassrls, rolconnlimit, (rolpassword IS NOT NULL) AS has_password, "
    "(rolvaliduntil IS NOT NULL) AS has_validity FROM pg_authid WHERE rolname = :name"
)
_DIRECT_DEPENDENCIES = sa.text(
    "SELECT count(*) FROM pg_shdepend WHERE refclassid = 'pg_authid'::regclass AND refobjid = :oid"
)
_MEMBERSHIPS = sa.text(
    "SELECT count(*) FROM pg_auth_members WHERE roleid = :oid OR member = :oid OR grantor = :oid"
)
_SETTINGS = sa.text("SELECT count(*) FROM pg_db_role_setting WHERE setrole = :oid")


@dataclass(frozen=True)
class RecorderRoleState:
    """The catalog facts that decide whether the recorder role is the exact inert identity."""

    oid: int
    can_login: bool
    inherits: bool
    is_superuser: bool
    can_create_db: bool
    can_create_role: bool
    can_replicate: bool
    can_bypass_rls: bool
    connection_limit: int
    has_password: bool
    has_validity: bool
    direct_dependencies: int
    memberships: int
    settings: int

    def attribute_violations(self) -> tuple[str, ...]:
        return tuple(
            label
            for label, field, expected in _INERT_ATTRIBUTES
            if getattr(self, field) != expected
        )

    @property
    def is_clean(self) -> bool:
        return (
            not self.attribute_violations()
            and self.direct_dependencies == 0
            and self.memberships == 0
            and self.settings == 0
        )


def _load_recorder_state(bind: Connection) -> RecorderRoleState | None:
    row = bind.execute(_ROLE_ATTRIBUTES, {"name": RECORDER_ROLE}).mappings().one_or_none()
    if row is None:
        return None
    oid = int(row["oid"])
    return RecorderRoleState(
        oid=oid,
        can_login=bool(row["rolcanlogin"]),
        inherits=bool(row["rolinherit"]),
        is_superuser=bool(row["rolsuper"]),
        can_create_db=bool(row["rolcreatedb"]),
        can_create_role=bool(row["rolcreaterole"]),
        can_replicate=bool(row["rolreplication"]),
        can_bypass_rls=bool(row["rolbypassrls"]),
        connection_limit=int(row["rolconnlimit"]),
        has_password=bool(row["has_password"]),
        has_validity=bool(row["has_validity"]),
        direct_dependencies=int(bind.scalar(_DIRECT_DEPENDENCIES, {"oid": oid}) or 0),
        memberships=int(bind.scalar(_MEMBERSHIPS, {"oid": oid}) or 0),
        settings=int(bind.scalar(_SETTINGS, {"oid": oid}) or 0),
    )


def reconcile_recorder_migration_state(
    *, version_num: str | None, role_present: bool, role_clean: bool
) -> str:
    """Classify an ambiguous post-connection-loss state for a migration administrator.

    Returns ``"committed"`` (revision 0008 with the exact clean role: the upgrade committed),
    ``"retry"`` (revision 0007 with the role either absent or exactly pre-existing: not committed,
    safe to retry), or ``"stop"`` (any mixed or unexpected state: do not retry blindly).
    """
    if version_num == revision and role_present and role_clean:
        return "committed"
    if version_num == down_revision and (not role_present or role_clean):
        return "retry"
    return "stop"


def _assert_recorder_clean(bind: Connection) -> None:
    state = _load_recorder_state(bind)
    if state is None or not state.is_clean:
        raise RuntimeError(
            f"{RECORDER_ROLE} must be the exact inert, dependency-free identity after this migration"
        )


def upgrade() -> None:
    bind = op.get_bind()
    state = _load_recorder_state(bind)
    if state is None:
        op.execute(sa.text(_CREATE_RECORDER))
    elif not state.is_clean:
        raise RuntimeError(
            f"existing role {RECORDER_ROLE} is not the exact inert, dependency-free identity this "
            f"migration owns (attribute violations={state.attribute_violations()}, "
            f"direct_dependencies={state.direct_dependencies}, memberships={state.memberships}, "
            f"settings={state.settings}); refusing to normalise it"
        )
    # A clean pre-existing role is left untouched so its OID is preserved.
    _assert_recorder_clean(bind)


def downgrade() -> None:
    bind = op.get_bind()
    state = _load_recorder_state(bind)
    if state is None:
        raise RuntimeError(
            f"{RECORDER_ROLE} is missing; refusing to advance downgrade from "
            "0008 with inconsistent recorder-role state"
        )
    if not state.is_clean:
        raise RuntimeError(
            f"{RECORDER_ROLE} changed or acquired a dependency (attribute "
            f"violations={state.attribute_violations()}, "
            f"direct_dependencies={state.direct_dependencies}, memberships={state.memberships}, "
            f"settings={state.settings}); refusing to drop it during downgrade"
        )
    op.execute(sa.text(f"DROP ROLE {RECORDER_ROLE}"))
