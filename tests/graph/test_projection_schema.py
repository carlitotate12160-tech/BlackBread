import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from blackbread.graph.replay import rebuild_scope_projection
from blackbread.models.core import Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context


async def test_projection_tables_force_tenant_row_level_security(
    session: AsyncSession,
) -> None:
    rows = (
        await session.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('graph_projection_snapshots', 'graph_nodes')"
            )
        )
    ).all()

    assert {row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in rows} == {
        "graph_nodes": (True, True),
        "graph_projection_snapshots": (True, True),
    }


async def test_runtime_role_has_minimum_projection_privileges(session: AsyncSession) -> None:
    row = (
        await session.execute(
            text(
                """
                SELECT
                    has_table_privilege(current_user, 'graph_nodes', 'SELECT') AS nodes_select,
                    has_table_privilege(current_user, 'graph_nodes', 'INSERT') AS nodes_insert,
                    has_table_privilege(current_user, 'graph_nodes', 'DELETE') AS nodes_delete,
                    has_table_privilege(current_user, 'graph_nodes', 'UPDATE') AS nodes_update,
                    has_table_privilege(current_user, 'graph_nodes', 'TRUNCATE') AS nodes_truncate,
                    has_table_privilege(
                        current_user, 'graph_projection_snapshots', 'SELECT'
                    ) AS snapshots_select,
                    has_table_privilege(
                        current_user, 'graph_projection_snapshots', 'INSERT'
                    ) AS snapshots_insert,
                    has_table_privilege(
                        current_user, 'graph_projection_snapshots', 'DELETE'
                    ) AS snapshots_delete,
                    has_table_privilege(
                        current_user, 'graph_projection_snapshots', 'TRUNCATE'
                    ) AS snapshots_truncate,
                    has_column_privilege(
                        current_user,
                        'graph_projection_snapshots',
                        'verified_event_count',
                        'UPDATE'
                    ) AS snapshots_update_count,
                    has_column_privilege(
                        current_user,
                        'graph_projection_snapshots',
                        'tenant_id',
                        'UPDATE'
                    ) AS snapshots_update_tenant
                """
            )
        )
    ).one()

    assert row.nodes_select is True
    assert row.nodes_insert is True
    assert row.nodes_delete is True
    assert row.nodes_update is False
    assert row.nodes_truncate is False
    assert row.snapshots_select is True
    assert row.snapshots_insert is True
    assert row.snapshots_delete is False
    assert row.snapshots_truncate is False
    assert row.snapshots_update_count is True
    assert row.snapshots_update_tenant is False


async def test_missing_tenant_context_cannot_read_projection_rows(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    await graph_events.append(session, engagement, graph_events.attestation())
    await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    await session.execute(text("SELECT 1"))
    assert (await session.execute(text("SELECT count(*) FROM graph_nodes"))).scalar_one() == 0
    assert (
        await session.execute(text("SELECT count(*) FROM graph_projection_snapshots"))
    ).scalar_one() == 0


async def test_database_enforces_unique_scope_identity_within_engagement(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    await graph_events.append(session, engagement, graph_events.attestation())
    await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    with pytest.raises(IntegrityError, match="uq_graph_nodes_scope_identity"):
        await admin_session.execute(
            text(
                "INSERT INTO graph_nodes "
                "SELECT tenant_id, engagement_id, graph_version, repeat('f', 64), node_family, "
                "scope_kind, canonical_value, authority, manifest_hash, valid_from, valid_until, "
                "source_sequence, source_event_hash, source_schema_name, "
                "source_schema_version FROM graph_nodes "
                "WHERE engagement_id = :engagement"
            ),
            {"engagement": engagement.id},
        )
    await admin_session.rollback()


async def test_bound_tenant_reads_only_its_projection_rows(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    await graph_events.append(session, engagement, graph_events.attestation())
    await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    await bind_tenant_context(session, TenantContext(engagement.tenant_id))
    assert (await session.execute(text("SELECT count(*) FROM graph_nodes"))).scalar_one() == 1
