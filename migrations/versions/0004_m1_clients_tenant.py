from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from blackbread.tenancy.client_backfill import resolve_client_tenants
from blackbread.tenancy.roles import require_isolatable_runtime_role

revision: str = "0004_m1_clients_tenant"
down_revision: str | None = "0003_m1_tenant_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_GUC = "blackbread.tenant_id"
TENANT_PREDICATE = f"tenant_id = current_setting('{TENANT_GUC}', true)"


def _backfill_client_tenants() -> None:
    connection = op.get_bind()
    pairs = [
        (row.client_id, row.tenant_id)
        for row in connection.execute(
            sa.text("SELECT DISTINCT client_id, tenant_id FROM engagements")
        )
    ]
    orphans = [
        row.id
        for row in connection.execute(
            sa.text(
                "SELECT c.id FROM clients AS c "
                "LEFT JOIN engagements AS e ON e.client_id = c.id "
                "WHERE e.client_id IS NULL"
            )
        )
    ]
    assignments = resolve_client_tenants(pairs, orphan_client_ids=orphans)
    for client_id, tenant_id in assignments.items():
        connection.execute(
            sa.text("UPDATE clients SET tenant_id = :tenant WHERE id = :id"),
            {"tenant": tenant_id, "id": client_id},
        )


def upgrade() -> None:
    require_isolatable_runtime_role(op.get_bind())
    op.add_column("clients", sa.Column("tenant_id", sa.String(length=100), nullable=True))
    _backfill_client_tenants()
    op.alter_column("clients", "tenant_id", nullable=False)
    op.create_check_constraint(
        "ck_clients_tenant_not_blank",
        "clients",
        "char_length(btrim(tenant_id)) > 0",
    )
    op.create_unique_constraint("uq_clients_id_tenant_id", "clients", ["id", "tenant_id"])
    op.create_index("ix_clients_tenant_id", "clients", ["tenant_id"])

    op.drop_constraint("engagements_client_id_fkey", "engagements", type_="foreignkey")
    op.create_foreign_key(
        "fk_engagements_client_tenant",
        "engagements",
        "clients",
        ["client_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )

    op.execute(sa.text("ALTER TABLE clients ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE clients FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            "CREATE POLICY tenant_isolation ON clients "
            f"FOR ALL USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON clients"))
    op.execute(sa.text("ALTER TABLE clients NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE clients DISABLE ROW LEVEL SECURITY"))

    op.drop_constraint("fk_engagements_client_tenant", "engagements", type_="foreignkey")
    op.create_foreign_key(
        "engagements_client_id_fkey",
        "engagements",
        "clients",
        ["client_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_index("ix_clients_tenant_id", table_name="clients")
    op.drop_constraint("uq_clients_id_tenant_id", "clients", type_="unique")
    op.drop_constraint("ck_clients_tenant_not_blank", "clients", type_="check")
    op.drop_column("clients", "tenant_id")
