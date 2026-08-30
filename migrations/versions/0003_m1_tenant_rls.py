from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_m1_tenant_rls"
down_revision: str | None = "0002_m1_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_GUC = "blackbread.tenant_id"
PROTECTED_TABLES = ("engagements", "agent_events")
TENANT_PREDICATE = f"tenant_id = current_setting('{TENANT_GUC}', true)"


def _require_runtime_role() -> None:
    connection = op.get_bind()
    role = (
        connection.execute(
            sa.text(
                """
                SELECT rolsuper, rolbypassrls
                FROM pg_roles
                WHERE rolname = 'blackbread_runtime'
                """
            )
        )
        .mappings()
        .one_or_none()
    )
    if role is None:
        raise RuntimeError("required role blackbread_runtime does not exist")
    if role["rolsuper"] or role["rolbypassrls"]:
        raise RuntimeError("blackbread_runtime must not be able to bypass row-level security")


def upgrade() -> None:
    _require_runtime_role()
    for table in PROTECTED_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                f"CREATE POLICY tenant_isolation ON {table} "
                f"FOR ALL USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
            )
        )


def downgrade() -> None:
    for table in PROTECTED_TABLES:
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
