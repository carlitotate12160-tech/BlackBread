"""M1.4c2b0 migration, role, privilege, and lifecycle authority proofs.

Each test is one oracle proving exactly one claim about migration 0008.
Run against a real PostgreSQL 17 instance — never SQLite or mocks.
"""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from blackbread.ledger.hashing import _event_preimage
from blackbread.policy.evaluation_facts import policy_decision_registry
from tests.conftest import TEST_MIGRATION_DATABASE_URL

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
    """Exact recorder role flags: no login, super, bypassrls, inherit, createdb/role, repl."""
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
            "SELECT rolpassword IS NULL FROM pg_authid WHERE rolname = 'blackbread_policy_recorder'"
        )
    )
    assert is_null is True


@pytest.mark.parametrize("direction", ["member", "roleid"])
async def test_recorder_has_no_role_memberships(
    admin_session: AsyncSession, direction: str
) -> None:
    """Zero pg_auth_members rows in either direction: no parent roles and no member roles."""
    oid = await admin_session.scalar(
        text("SELECT oid FROM pg_roles WHERE rolname = 'blackbread_policy_recorder'")
    )
    count = await admin_session.scalar(
        text(f"SELECT count(*) FROM pg_auth_members WHERE {direction} = :oid"),  # noqa: S608
        {"oid": oid},
    )
    assert count == 0


async def test_runtime_cannot_assume_recorder(session: AsyncSession) -> None:
    """blackbread_test_runtime SET ROLE blackbread_policy_recorder fails."""
    with pytest.raises(Exception, match="permission denied"):
        await session.execute(text("SET ROLE blackbread_policy_recorder"))


# ────────────────────────────────────────────────────────────────────
# §A — Schema, table and column privilege proofs
# ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("privilege, expected", [("USAGE", True), ("CREATE", False)])
async def test_recorder_schema_privileges(
    session: AsyncSession, privilege: str, expected: bool
) -> None:
    """USAGE on schema public is granted; CREATE never is."""
    result = await session.scalar(
        text("SELECT has_schema_privilege('blackbread_policy_recorder', 'public', :p)"),
        {"p": privilege},
    )
    assert result is expected


@pytest.mark.parametrize("table", ["action_proposals", "decision_records", "agent_events"])
@pytest.mark.parametrize(
    "privilege, expected",
    [
        ("SELECT", True),
        ("INSERT", True),
        ("UPDATE", False),
        ("DELETE", False),
        ("TRUNCATE", False),
    ],
)
async def test_recorder_table_privileges(
    session: AsyncSession, table: str, privilege: str, expected: bool
) -> None:
    """Exactly SELECT+INSERT on the policy tables; never UPDATE, DELETE or TRUNCATE."""
    result = await session.scalar(
        text("SELECT has_table_privilege('blackbread_policy_recorder', :t, :p)"),
        {"t": table, "p": privilege},
    )
    assert result is expected, f"{privilege} on {table}"


async def test_recorder_engagement_select(session: AsyncSession) -> None:
    """The ledger anchor is readable so the recorder can lock it."""
    result = await session.scalar(
        text("SELECT has_table_privilege('blackbread_policy_recorder', 'engagements', 'SELECT')")
    )
    assert result is True


@pytest.mark.parametrize(
    "column, expected",
    [
        ("ledger_lock_token", True),
        ("ledger_event_count", False),
        ("ledger_head_hash", False),
        ("status", False),
    ],
)
async def test_recorder_engagement_column_updates(
    session: AsyncSession, column: str, expected: bool
) -> None:
    """ledger_lock_token is the only engagements column the recorder may ever update."""
    result = await session.scalar(
        text(
            "SELECT has_column_privilege('blackbread_policy_recorder', 'engagements', :c, 'UPDATE')"
        ),
        {"c": column},
    )
    assert result is expected, f"UPDATE on engagements.{column}"


@pytest.mark.parametrize("table", _DENIED_TABLES)
async def test_recorder_no_privilege_on_unrelated_tables(session: AsyncSession, table: str) -> None:
    """No effective privilege of any kind on application tables outside the grant list."""
    for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        result = await session.scalar(
            text("SELECT has_table_privilege('blackbread_policy_recorder', :t, :p)"),
            {"t": table, "p": priv},
        )
        assert result is False, f"unexpected {priv} on {table}"


# ────────────────────────────────────────────────────────────────────
# §A — Trigger function catalog proofs
# ────────────────────────────────────────────────────────────────────


async def test_trigger_function_catalog_shape(session: AsyncSession) -> None:
    """The validation function is SECURITY INVOKER, path-pinned, and not callable by PUBLIC.

    PUBLIC's EXECUTE cannot be probed with ``has_function_privilege('PUBLIC', ...)``: PostgreSQL
    has no role named PUBLIC and that call errors. The ACL is inspected instead, where PUBLIC is
    grantee OID 0; a NULL ``proacl`` means the built-in default, which *does* grant EXECUTE to
    PUBLIC, so it is rejected rather than treated as an empty grant list.
    """
    row = (
        await session.execute(
            text(
                "SELECT prosecdef, proconfig, "
                "  proacl IS NOT NULL AND NOT EXISTS ("
                "    SELECT 1 FROM aclexplode(proacl) AS a "
                "    WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE') AS public_revoked "
                "FROM pg_proc WHERE proname = 'blackbread_validate_policy_event'"
            )
        )
    ).one()
    assert row.prosecdef is False, "trigger function must be SECURITY INVOKER"
    assert "search_path=pg_catalog, public" in row.proconfig
    assert row.public_revoked is True, "PUBLIC must hold no EXECUTE on the trigger function"


# ────────────────────────────────────────────────────────────────────
# §A — Membership mutation proof
# ────────────────────────────────────────────────────────────────────


async def test_membership_mutation_proof(session: AsyncSession) -> None:
    """Grant recorder to the test runtime, prove non-assumability fails, revoke, prove it holds.

    Membership is a cluster-wide, non-transactional grant, so the REVOKE runs in a ``finally`` to
    restore ``pg_auth_members`` even if an assertion fails. The suite runs serially (no xdist).
    """
    admin = create_async_engine(TEST_MIGRATION_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as admin_conn:
            await admin_conn.execute(
                text("GRANT blackbread_policy_recorder TO blackbread_test_runtime")
            )
        try:
            # With the grant in place the runtime login can now assume the recorder.
            await session.execute(text("SET ROLE blackbread_policy_recorder"))
            await session.execute(text("RESET ROLE"))
            await session.rollback()
        finally:
            async with admin.connect() as admin_conn:
                await admin_conn.execute(
                    text("REVOKE blackbread_policy_recorder FROM blackbread_test_runtime")
                )
                # roleid, not member: the grant made the recorder the *granted role*, so the
                # members-of-recorder direction is the one that must return to zero.
                members = await admin_conn.scalar(
                    text(
                        "SELECT count(*) FROM pg_auth_members WHERE roleid = "
                        "(SELECT oid FROM pg_roles WHERE rolname = 'blackbread_policy_recorder')"
                    )
                )
        assert members == 0

        # With membership restored to zero the runtime can no longer assume the recorder.
        await session.rollback()
        with pytest.raises(Exception, match="permission denied"):
            await session.execute(text("SET ROLE blackbread_policy_recorder"))
    finally:
        await admin.dispose()


# ────────────────────────────────────────────────────────────────────
# §J — Compatibility: released c2a registry and preimage unchanged
# ────────────────────────────────────────────────────────────────────


async def test_policy_decision_registry_unchanged(session: AsyncSession) -> None:
    """The frozen c2a registry still resolves the released schema key.

    The golden SHA-256 vector itself is asserted by the preserved c2a suite
    (tests/policy/test_policy_decision_recorded_event.py), which this slice does not modify.
    """
    assert ("policy.decision.recorded", 1) in policy_decision_registry()._schemas


async def test_event_preimage_unchanged(session: AsyncSession) -> None:
    """_event_preimage fields remain exactly as released."""
    source = inspect.getsource(_event_preimage)
    expected_fields = (  # noqa: SIM905 — compact split kept intentionally
        "event_id engagement_id tenant_id sequence schema_name schema_version producer "
        "correlation_id causation_id occurred_at recorded_at payload_hash prev_event_hash "
        "hash_algorithm hash_version sensitivity redaction_refs"
    ).split()
    for field in expected_fields:
        assert field in source, f"missing preimage field: {field}"
    assert "policy_decision_id" not in source
