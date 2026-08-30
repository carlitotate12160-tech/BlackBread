from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from blackbread.tenancy.roles import require_isolatable_runtime_role

revision: str = "0003_m1_tenant_rls"
down_revision: str | None = "0002_m1_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_GUC = "blackbread.tenant_id"
PROTECTED_TABLES = ("engagements", "agent_events")
TENANT_PREDICATE = f"tenant_id = current_setting('{TENANT_GUC}', true)"


def upgrade() -> None:
    require_isolatable_runtime_role(op.get_bind())
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
