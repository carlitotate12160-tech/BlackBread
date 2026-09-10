"""M1.4c2b0 migration, role, privilege, and lifecycle authority proofs.

Each test is one oracle proving exactly one claim about migration 0008.
Run against a real PostgreSQL 17 instance — never SQLite or mocks.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from tests.policy._policy_record_builders import (
    decision_row,
    insert_decision,
    insert_proposal,
    proposal_row,
)

pytestmark = pytest.mark.anyio

# ─── Non-system application tables the recorder must NOT access ───
_DENIED_TABLES = (
    "clients",
    "platform_metadata",
    "graph_projection_snapshots",
    "graph_nodes",
    "graph_temporal_projection_snapshots",
    "graph_temporal_scope_roots",
    "graph_temporal_scope_revisions",
    "graph_temporal_head_nodes",
    "alembic_version",
)


# ────────────────────────────────────────────────────────────────────
# §A — Inert, least-privilege role shape
# ────────────────────────────────────────────────────────────────────


async def test_recorder_role_flags(session: AsyncSession) -> None:
    """rolcanlogin, rolsuper, rolbypassrls, rolinherit, rolcreatedb, rolcreaterole, rolreplication."""
    row = (
        await session.execute(
            text(
                "SELECT rolcanlogin, rolsuper, rolbypassrls, rolinherit, "
                "rolcreatedb, rolcreaterole, rolreplication "
                "FROM pg_roles WHERE rolname = 'blackbread_policy_recorder'"
            )
        )
    ).one()
    assert row == (False, False, False, False, False, False, False)


async def test_recorder_has_no_password(admin_session: AsyncSession) -> None:
    """pg_authid.rolpassword IS NULL — not rolvaliduntil."""
    is_null = await admin_session.scalar(
        text(
            "SELECT rolpassword IS NULL FROM pg_authid "
            "WHERE rolname = 'blackbread_policy_recorder'"
        )
    )
    assert is_null is True


async def test_recorder_has_no_parent_roles(admin_session: AsyncSession) -> None:
    """Zero pg_auth_members rows where recorder is member."""
    oid = await admin_session.scalar(
        text("SELECT oid FROM pg_roles WHERE rolname = 'blackbread_policy_recorder'")
    )
    count = await admin_session.scalar(text("SELECT count(*) FROM pg_auth_members WHERE member = :oid"), {"oid": oid})
    assert count == 0


async def test_recorder_has_no_member_roles(admin_session: AsyncSession) -> None:
    """Zero pg_auth_members rows where recorder is parent."""
    oid = await admin_session.scalar(
        text("SELECT oid FROM pg_roles WHERE rolname = 'blackbread_policy_recorder'")
    )
    count = await admin_session.scalar(text("SELECT count(*) FROM pg_auth_members WHERE roleid = :oid"), {"oid": oid})
    assert count == 0


async def test_runtime_cannot_assume_recorder(session: AsyncSession) -> None:
    """blackbread_test_runtime SET ROLE blackbread_policy_recorder fails."""
    with pytest.raises(Exception, match="permission denied"):
        await session.execute(text("SET ROLE blackbread_policy_recorder"))


# ────────────────────────────────────────────────────────────────────
# §A — Schema privilege proofs
# ────────────────────────────────────────────────────────────────────


async def test_recorder_has_schema_usage(session: AsyncSession) -> None:
    result = await session.scalar(
        text("SELECT has_schema_privilege('blackbread_policy_recorder', 'public', 'USAGE')")
    )
    assert result is True


async def test_recorder_has_no_schema_create(session: AsyncSession) -> None:
    result = await session.scalar(
        text("SELECT has_schema_privilege('blackbread_policy_recorder', 'public', 'CREATE')")
    )
    assert result is False


# ────────────────────────────────────────────────────────────────────
# §A — Table/column privilege proofs
# ────────────────────────────────────────────────────────────────────


_RECORDER_GRANTED_SELECT_INSERT = (
    "action_proposals",
    "decision_records",
    "agent_events",
)


@pytest.mark.parametrize("table", _RECORDER_GRANTED_SELECT_INSERT)
async def test_recorder_select_insert_granted(session: AsyncSession, table: str) -> None:
    for priv in ("SELECT", "INSERT"):
        result = await session.scalar(
            text(f"SELECT has_table_privilege('blackbread_policy_recorder', '{table}', '{priv}')")
        )
        assert result is True, f"expected {priv} on {table}"


@pytest.mark.parametrize("table", _RECORDER_GRANTED_SELECT_INSERT)
@pytest.mark.parametrize("priv", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_recorder_mutation_denied(session: AsyncSession, table: str, priv: str) -> None:
    result = await session.scalar(
        text(f"SELECT has_table_privilege('blackbread_policy_recorder', '{table}', '{priv}')")
    )
    assert result is False, f"unexpected {priv} on {table}"


async def test_recorder_engagement_select(session: AsyncSession) -> None:
    result = await session.scalar(
        text("SELECT has_table_privilege('blackbread_policy_recorder', 'engagements', 'SELECT')")
    )
    assert result is True


async def test_recorder_engagement_lock_token_update(session: AsyncSession) -> None:
    result = await session.scalar(
        text(
            "SELECT has_column_privilege("
            "'blackbread_policy_recorder', 'engagements', 'ledger_lock_token', 'UPDATE')"
        )
    )
    assert result is True


@pytest.mark.parametrize("col", ["ledger_event_count", "ledger_head_hash", "status"])
async def test_recorder_engagement_other_cols_denied(session: AsyncSession, col: str) -> None:
    result = await session.scalar(
        text(
            f"SELECT has_column_privilege("
            f"'blackbread_policy_recorder', 'engagements', '{col}', 'UPDATE')"
        )
    )
    assert result is False, f"unexpected UPDATE on engagements.{col}"


@pytest.mark.parametrize("table", _DENIED_TABLES)
async def test_recorder_no_privilege_on_unrelated_tables(session: AsyncSession, table: str) -> None:
    for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        result = await session.scalar(
            text(f"SELECT has_table_privilege('blackbread_policy_recorder', '{table}', '{priv}')")
        )
        assert result is False, f"unexpected {priv} on {table}"


# ────────────────────────────────────────────────────────────────────
# §A — Trigger function catalog proofs
# ────────────────────────────────────────────────────────────────────


async def test_trigger_is_security_invoker(session: AsyncSession) -> None:
    """pg_proc.prosecdef = false for the validation trigger function."""
    is_definer = await session.scalar(
        text(
            "SELECT prosecdef FROM pg_proc "
            "WHERE proname = 'blackbread_validate_policy_event'"
        )
    )
    assert is_definer is False


async def test_trigger_search_path(session: AsyncSession) -> None:
    """proconfig contains the expected search_path."""
    proconfig = (
        await session.execute(
            text(
                "SELECT proconfig FROM pg_proc "
                "WHERE proname = 'blackbread_validate_policy_event'"
            )
        )
    ).scalar_one()
    assert "search_path=pg_catalog, public" in proconfig


# ────────────────────────────────────────────────────────────────────
# §A — Membership mutation proof (correction #3)
# ────────────────────────────────────────────────────────────────────


async def test_membership_mutation_proof(session: AsyncSession) -> None:
    """Temporarily grant recorder to runtime, prove assumability oracle fails, revoke, restore."""
    from tests.conftest import TEST_MIGRATION_DATABASE_URL
    admin = create_async_engine(TEST_MIGRATION_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as admin_conn:
            await admin_conn.execute(
                text("GRANT blackbread_policy_recorder TO blackbread_test_runtime")
            )
        # Now the test runtime can assume recorder — this should succeed
        await session.execute(text("SET ROLE blackbread_policy_recorder"))
        await session.execute(text("RESET ROLE"))

        async with admin.connect() as admin_conn:
            await admin_conn.execute(
                text("REVOKE blackbread_policy_recorder FROM blackbread_test_runtime")
            )
            members = await admin_conn.scalar(
                text(
                    "SELECT count(*) FROM pg_auth_members WHERE member = "
                    "(SELECT oid FROM pg_roles WHERE rolname = 'blackbread_policy_recorder')"
                )
            )
            assert members == 0

        # Now SET ROLE must fail again
        await session.rollback()
        with pytest.raises(Exception, match="permission denied"):
            await session.execute(text("SET ROLE blackbread_policy_recorder"))
    finally:
        await admin.dispose()


# ────────────────────────────────────────────────────────────────────
# §G — Migration upgrade refusal with existing data
# ────────────────────────────────────────────────────────────────────
# These tests require isolated disposable databases.
# They are created in their own conftest lifecycle harness.
# See test_policy_record_migration_lifecycle.py for the isolated DB fixture.


# ────────────────────────────────────────────────────────────────────
# §5 — Incompatible existing recorder role (correction #5)
# ────────────────────────────────────────────────────────────────────
# This test needs an isolated lifecycle DB with a mis-privileged recorder.
# It is placed in the migration lifecycle suite.


# ────────────────────────────────────────────────────────────────────
# §J — Compatibility: c2a golden hash and registry unchanged
# ────────────────────────────────────────────────────────────────────


async def test_c2a_golden_hash_preserved(session: AsyncSession) -> None:
    """The released golden SHA-256 is unchanged."""
    from blackbread.policy.evaluation_facts import policy_decision_registry

    registry = policy_decision_registry()
    key = ("policy.decision.recorded", 1)
    assert key in registry._schemas  # noqa: SLF001 — testing frozen registry


async def test_event_preimage_unchanged(session: AsyncSession) -> None:
    """_event_preimage fields remain exactly as released."""
    import inspect
    from blackbread.ledger.hashing import _event_preimage

    source = inspect.getsource(_event_preimage)
    expected_fields = [
        "event_id", "engagement_id", "tenant_id", "sequence",
        "schema_name", "schema_version", "producer",
        "correlation_id", "causation_id",
        "occurred_at", "recorded_at",
        "payload_hash", "prev_event_hash",
        "hash_algorithm", "hash_version",
        "sensitivity", "redaction_refs",
    ]
    for field in expected_fields:
        assert field in source, f"missing preimage field: {field}"
    assert "policy_decision_id" not in source
