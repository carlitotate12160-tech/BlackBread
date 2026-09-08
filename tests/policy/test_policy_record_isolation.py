"""FORCE RLS, missing-context denial, cross-tenant isolation, and runtime write-denial proofs.

Reads and writes use the real login runtime role and the real transaction-local
``blackbread.tenant_id`` binding. Rows are seeded through the admin engine because the runtime role
has no INSERT privilege; ORM-side filtering is never used as the isolation oracle.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.policy._policy_record_builders import (
    decision_row,
    insert_decision,
    insert_proposal,
    proposal_row,
)
from tests.policy.conftest import seed_engagement

WRITE_PRIVILEGES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE")


async def _seed_tenant(admin: AsyncEngine, tenant: str) -> dict[str, Any]:
    engagement_id = uuid.uuid4()
    await seed_engagement(admin, tenant, engagement_id)
    proposal = proposal_row(proposal_id=uuid.uuid4(), tenant_id=tenant, engagement_id=engagement_id)
    async with admin.begin() as conn:
        await insert_proposal(conn, proposal)
        await insert_decision(conn, decision_row(proposal))
    return proposal


async def _count_as_tenant(runtime: AsyncEngine, table: str, bind: str | None, where: str) -> int:
    async with runtime.begin() as conn:
        if bind is not None:
            await conn.execute(
                text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": bind}
            )
        value = await conn.scalar(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :w"),  # noqa: S608
            {"w": where},
        )
    return int(value or 0)


async def test_runtime_role_has_select_only(policy_admin_engine: AsyncEngine) -> None:
    async with policy_admin_engine.begin() as conn:
        for table in ("action_proposals", "decision_records"):
            can_select = await conn.scalar(
                text("SELECT has_table_privilege('blackbread_runtime', :tbl, 'SELECT')"),
                {"tbl": table},
            )
            assert can_select is True, table
            for privilege in WRITE_PRIVILEGES:
                granted = await conn.scalar(
                    text("SELECT has_table_privilege('blackbread_runtime', :tbl, :p)"),
                    {"tbl": table, "p": privilege},
                )
                assert granted is False, f"{table} unexpectedly grants {privilege}"


async def test_tenant_rows_are_isolated_and_context_is_required(
    policy_admin_engine: AsyncEngine, engine: AsyncEngine
) -> None:
    tenant_a = f"tenant-{uuid.uuid4().hex[:12]}"
    tenant_b = f"tenant-{uuid.uuid4().hex[:12]}"
    await _seed_tenant(policy_admin_engine, tenant_a)
    await _seed_tenant(policy_admin_engine, tenant_b)

    # Admin (RLS-bypassing) proves both rows genuinely exist.
    for tenant in (tenant_a, tenant_b):
        async with policy_admin_engine.begin() as conn:
            total = await conn.scalar(
                text("SELECT count(*) FROM action_proposals WHERE tenant_id = :t"), {"t": tenant}
            )
            assert int(total or 0) == 1

    for table in ("action_proposals", "decision_records"):
        # Each tenant sees only its own row.
        assert await _count_as_tenant(engine, table, tenant_a, tenant_a) == 1
        assert await _count_as_tenant(engine, table, tenant_b, tenant_b) == 1
        # A bound tenant cannot recover another tenant's rows even naming them explicitly.
        assert await _count_as_tenant(engine, table, tenant_a, tenant_b) == 0
        assert await _count_as_tenant(engine, table, tenant_b, tenant_a) == 0
        # Missing tenant context reveals nothing.
        assert await _count_as_tenant(engine, table, None, tenant_a) == 0


async def test_runtime_insert_is_denied_by_privilege(
    policy_admin_engine: AsyncEngine, engine: AsyncEngine
) -> None:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    engagement_id = uuid.uuid4()
    await seed_engagement(policy_admin_engine, tenant, engagement_id)
    # An otherwise-valid row: the only reason the write fails is missing privilege.
    valid = proposal_row(proposal_id=uuid.uuid4(), tenant_id=tenant, engagement_id=engagement_id)
    with pytest.raises(ProgrammingError) as excinfo:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
            )
            await insert_proposal(conn, valid)
    assert "permission denied" in str(excinfo.value.orig).lower()
    # Admin confirms nothing was written.
    async with policy_admin_engine.begin() as conn:
        total = await conn.scalar(
            text("SELECT count(*) FROM action_proposals WHERE tenant_id = :t"), {"t": tenant}
        )
        assert int(total or 0) == 0
