"""Append-only immutability proofs for action_proposals and decision_records (M1.4c1).

UPDATE, DELETE, and TRUNCATE are attempted through the privileged admin connection that holds full
write authority, so a rejection proves the immutable-record trigger, not a mere privilege gap. Each
proof re-reads the row and asserts it is byte-for-byte unchanged at the database-column level.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.policy._policy_record_builders import (
    decision_row,
    insert_decision,
    insert_proposal,
    proposal_row,
)
from tests.policy.conftest import seed_engagement


async def _seed_records(admin: AsyncEngine) -> tuple[str, dict[str, Any], dict[str, Any]]:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    engagement_id = uuid.uuid4()
    await seed_engagement(admin, tenant, engagement_id)
    proposal = proposal_row(proposal_id=uuid.uuid4(), tenant_id=tenant, engagement_id=engagement_id)
    decision = decision_row(proposal)
    async with admin.begin() as conn:
        await insert_proposal(conn, proposal)
        await insert_decision(conn, decision)
    return tenant, proposal, decision


async def _snapshot(admin: AsyncEngine, table: str, key: str, value: uuid.UUID) -> dict[str, Any]:
    async with admin.begin() as conn:
        result = await conn.execute(
            text(f"SELECT * FROM {table} WHERE {key} = :v"),  # noqa: S608
            {"v": value},
        )
        return dict(result.mappings().one())


@pytest.mark.parametrize(
    ("table", "key"),
    [("action_proposals", "proposal_id"), ("decision_records", "decision_id")],
)
async def test_update_is_rejected(policy_admin_engine: AsyncEngine, table: str, key: str) -> None:
    _tenant, proposal, decision = await _seed_records(policy_admin_engine)
    key_value = proposal[key] if table == "action_proposals" else decision[key]
    before = await _snapshot(policy_admin_engine, table, key, key_value)
    with pytest.raises(DBAPIError) as excinfo:
        async with policy_admin_engine.begin() as conn:
            await conn.execute(
                text(f"UPDATE {table} SET tenant_id = 'mutated' WHERE {key} = :v"),  # noqa: S608
                {"v": key_value},
            )
    assert "append-only" in str(excinfo.value.orig)
    assert await _snapshot(policy_admin_engine, table, key, key_value) == before


@pytest.mark.parametrize(
    ("table", "key"),
    [("action_proposals", "proposal_id"), ("decision_records", "decision_id")],
)
async def test_delete_is_rejected(policy_admin_engine: AsyncEngine, table: str, key: str) -> None:
    _tenant, proposal, decision = await _seed_records(policy_admin_engine)
    key_value = proposal[key] if table == "action_proposals" else decision[key]
    before = await _snapshot(policy_admin_engine, table, key, key_value)
    with pytest.raises(DBAPIError) as excinfo:
        async with policy_admin_engine.begin() as conn:
            await conn.execute(
                text(f"DELETE FROM {table} WHERE {key} = :v"),  # noqa: S608
                {"v": key_value},
            )
    assert "append-only" in str(excinfo.value.orig)
    assert await _snapshot(policy_admin_engine, table, key, key_value) == before


@pytest.mark.parametrize("table", ["decision_records", "action_proposals"])
async def test_truncate_is_rejected(policy_admin_engine: AsyncEngine, table: str) -> None:
    tenant, _proposal, _decision = await _seed_records(policy_admin_engine)
    # CASCADE satisfies the FK-reference guard, so the trigger is what rejects truncation.
    with pytest.raises(DBAPIError) as excinfo:
        async with policy_admin_engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {table} CASCADE"))
    assert "append-only" in str(excinfo.value.orig)
    async with policy_admin_engine.begin() as conn:
        total = await conn.scalar(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),  # noqa: S608
            {"t": tenant},
        )
        assert int(total or 0) == 1
