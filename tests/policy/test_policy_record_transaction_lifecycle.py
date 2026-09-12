"""M1.4c2b1 migration 0010 upgrade/downgrade/re-upgrade lifecycle and baseline-drift proofs.

Runs against the private throwaway lifecycle database; the cluster-global recorder role's shared
0009/0010 dependencies are suspended for the module (``suspend_shared_authority_head``) so a
``downgrade base`` may drop and recreate the role. Proves the ``0009 -> 0010 -> 0009 -> 0010`` round
trip installs and removes exactly the routine (dormant: PUBLIC EXECUTE revoked, no grant to any
login role), the additional recorder INSERT grants, and the one-decision-per-proposal uniqueness,
and that migration 0010 refuses to expand authority on a recorder that has drifted from its exact
revision-0009 baseline (an attribute change or an unexpected grant), leaving Alembic at 0009 without
silently normalising the role.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.policy._policy_record_authority_support import (
    RECORDER_ROLE,
    REV_0009,
    REV_0010,
    ROUTINE,
    RUNTIME_ROLE,
    alembic_expecting_failure,
    alembic_version,
    lifecycle_url,
    reset_to,
    run_admin,
    run_alembic_step,
    suspend_shared_authority_head,  # noqa: F401 -- module suspend fixture applied via pytestmark
    table_privilege,
)

pytestmark = pytest.mark.usefixtures("suspend_shared_authority_head")

RECORD_TABLES = ("action_proposals", "decision_records")


async def _routine_present(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
        return bool(
            await conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = :n)"), {"n": ROUTINE}
            )
        )


async def _uniqueness_present(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
        return bool(
            await conn.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_constraint "
                    "WHERE conname = 'uq_decision_records_proposal')"
                )
            )
        )


async def _routine_owner_secdef(engine: AsyncEngine) -> tuple[str | None, bool | None]:
    async with engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT pg_get_userbyid(proowner) AS owner, prosecdef "
                        "FROM pg_proc WHERE proname = :n"
                    ),
                    {"n": ROUTINE},
                )
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return None, None
    return row["owner"], row["prosecdef"]


async def test_round_trip_0009_0010_0009_0010(
    lifecycle_db: str, lifecycle_admin_engine: Any
) -> None:
    reset_to(lifecycle_db, REV_0009)
    assert not await _routine_present(lifecycle_admin_engine)
    assert not await _uniqueness_present(lifecycle_admin_engine)

    run_alembic_step(lifecycle_db, "upgrade", REV_0010)
    assert await alembic_version(lifecycle_admin_engine) == REV_0010
    assert await _routine_owner_secdef(lifecycle_admin_engine) == (RECORDER_ROLE, True)
    assert await _uniqueness_present(lifecycle_admin_engine)
    for table in RECORD_TABLES:
        assert await table_privilege(lifecycle_admin_engine, RECORDER_ROLE, table, "INSERT")
    runtime_exec = None
    async with lifecycle_admin_engine.connect() as conn:
        runtime_exec = await conn.scalar(
            text(
                "SELECT has_function_privilege(:r, oid, 'EXECUTE') FROM pg_proc WHERE proname = :n"
            ),
            {"r": RUNTIME_ROLE, "n": ROUTINE},
        )
        public_exec = await conn.scalar(
            text(
                "SELECT has_function_privilege('public', oid, 'EXECUTE') "
                "FROM pg_proc WHERE proname = :n"
            ),
            {"n": ROUTINE},
        )
        granted = await conn.scalar(
            text(
                "SELECT count(*) FROM information_schema.routine_privileges "
                "WHERE routine_schema = 'public' AND routine_name = :n AND grantee <> :owner"
            ),
            {"n": ROUTINE, "owner": RECORDER_ROLE},
        )
    # Dormant substrate: no login role may execute the routine, and no non-owner grantee holds any
    # routine privilege (PostgreSQL keeps only the owner's implicit self-grant).
    assert runtime_exec is False
    assert public_exec is False
    assert granted == 0

    run_alembic_step(lifecycle_db, "downgrade", REV_0009)
    assert await alembic_version(lifecycle_admin_engine) == REV_0009
    assert not await _routine_present(lifecycle_admin_engine)
    assert not await _uniqueness_present(lifecycle_admin_engine)
    for table in RECORD_TABLES:
        assert not await table_privilege(lifecycle_admin_engine, RECORDER_ROLE, table, "INSERT")
        assert await table_privilege(lifecycle_admin_engine, RECORDER_ROLE, table, "SELECT")

    run_alembic_step(lifecycle_db, "upgrade", REV_0010)
    assert await alembic_version(lifecycle_admin_engine) == REV_0010
    assert await _routine_present(lifecycle_admin_engine)
    assert await _uniqueness_present(lifecycle_admin_engine)


async def test_upgrade_rejects_drifted_recorder_attribute(
    lifecycle_db: str, lifecycle_admin_engine: Any
) -> None:
    reset_to(lifecycle_db, REV_0009)
    await run_admin(f"ALTER ROLE {RECORDER_ROLE} LOGIN")
    try:
        output = alembic_expecting_failure(lifecycle_db, "upgrade", REV_0010)
        assert RECORDER_ROLE in output, "failure must name the recorder role"
        assert await alembic_version(lifecycle_admin_engine) == REV_0009
        assert not await _routine_present(lifecycle_admin_engine)
    finally:
        await run_admin(f"ALTER ROLE {RECORDER_ROLE} NOLOGIN")


async def test_upgrade_rejects_unexpected_recorder_grant(
    lifecycle_db: str, lifecycle_admin_engine: Any
) -> None:
    reset_to(lifecycle_db, REV_0009)
    url = lifecycle_url(lifecycle_db)
    # An out-of-band UPDATE grant is not part of the exact revision-0009 baseline.
    await run_admin(f"GRANT UPDATE ON TABLE action_proposals TO {RECORDER_ROLE}", url=url)
    try:
        output = alembic_expecting_failure(lifecycle_db, "upgrade", REV_0010)
        assert RECORDER_ROLE in output, "failure must name the recorder role"
        assert await alembic_version(lifecycle_admin_engine) == REV_0009
        assert not await _routine_present(lifecycle_admin_engine)
    finally:
        await run_admin(f"REVOKE UPDATE ON TABLE action_proposals FROM {RECORDER_ROLE}", url=url)
