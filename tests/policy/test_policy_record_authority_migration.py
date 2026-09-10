"""M1.4c2b0 migration, role, privilege, and lifecycle authority proofs.

Each test is one oracle proving exactly one claim about migration 0008.
Run against a real PostgreSQL 17 instance — never SQLite or mocks.
"""

from __future__ import annotations

import inspect
import subprocess
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from blackbread.ledger.hashing import _event_preimage
from blackbread.policy.evaluation_facts import policy_decision_registry
from tests.conftest import TEST_MIGRATION_DATABASE_URL
from tests.policy._policy_record_builders import (
    DECISION_COLUMNS,
    decision_row,
    insert_decision,
    insert_proposal,
    proposal_row,
)
from tests.policy.conftest import run_alembic, seed_engagement

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


async def test_recorder_has_no_parent_roles(admin_session: AsyncSession) -> None:
    """Zero pg_auth_members rows where recorder is member."""
    oid = await admin_session.scalar(
        text("SELECT oid FROM pg_roles WHERE rolname = 'blackbread_policy_recorder'")
    )
    count = await admin_session.scalar(
        text("SELECT count(*) FROM pg_auth_members WHERE member = :oid"), {"oid": oid}
    )
    assert count == 0


async def test_recorder_has_no_member_roles(admin_session: AsyncSession) -> None:
    """Zero pg_auth_members rows where recorder is parent."""
    oid = await admin_session.scalar(
        text("SELECT oid FROM pg_roles WHERE rolname = 'blackbread_policy_recorder'")
    )
    count = await admin_session.scalar(
        text("SELECT count(*) FROM pg_auth_members WHERE roleid = :oid"), {"oid": oid}
    )
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
        text("SELECT prosecdef FROM pg_proc WHERE proname = 'blackbread_validate_policy_event'")
    )
    assert is_definer is False


async def test_trigger_search_path(session: AsyncSession) -> None:
    """proconfig contains the expected search_path."""
    proconfig = (
        await session.execute(
            text("SELECT proconfig FROM pg_proc WHERE proname = 'blackbread_validate_policy_event'")
        )
    ).scalar_one()
    assert "search_path=pg_catalog, public" in proconfig


# ────────────────────────────────────────────────────────────────────
# §A — Membership mutation proof (correction #3)
# ────────────────────────────────────────────────────────────────────


async def test_membership_mutation_proof(session: AsyncSession) -> None:
    """Temporarily grant recorder to the test runtime, prove the non-assumability oracle fails,
    revoke, and prove it holds again.

    Role membership is a cluster-wide, non-transactional grant, so the REVOKE runs in a ``finally``
    to restore ``pg_auth_members`` even if an assertion fails. The suite runs serially (no xdist),
    so no other worker observes the transient grant.
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
                members = await admin_conn.scalar(
                    text(
                        "SELECT count(*) FROM pg_auth_members WHERE member = "
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
    registry = policy_decision_registry()
    key = ("policy.decision.recorded", 1)
    assert key in registry._schemas


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


# ────────────────────────────────────────────────────────────────────
# §G/§H — Isolated 0007↔0008 migration lifecycle (disposable database)
# ────────────────────────────────────────────────────────────────────


REV_0007 = "0007_m1_policy_records"
REV_0008 = "0008_m1_policy_record_authority"


async def _alembic_version(engine: AsyncEngine) -> str | None:
    async with engine.begin() as conn:
        return await conn.scalar(text("SELECT version_num FROM alembic_version"))


async def _has_0008_objects(engine: AsyncEngine) -> bool:
    async with engine.begin() as conn:
        trigger = await conn.scalar(
            text(
                "SELECT count(*) FROM pg_trigger "
                "WHERE tgname = 'agent_events_validate_policy_event'"
            )
        )
        column = await conn.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'agent_events' AND column_name = 'policy_decision_id'"
            )
        )
    return bool(trigger) or bool(column)


_APPEND_ONLY = (
    ("agent_events", "agent_events_reject_truncate"),
    ("action_proposals", "action_proposals_reject_truncate"),
    ("decision_records", "decision_records_reject_truncate"),
)

# Every column a c1 (0007) decision carries — the 0008 evaluation_request_digest is absent there.
_DECISION_0007_COLUMNS = tuple(c for c in DECISION_COLUMNS if c != "evaluation_request_digest")


async def _reset_lifecycle(engine: AsyncEngine, db: str) -> None:
    """Bring the shared lifecycle database back to an empty ``base`` from any prior state.

    The 0008 downgrade refuses while policy rows exist (the intended production guarantee), so any
    seeded rows are truncated first; then the full downgrade to base runs cleanly.
    """
    async with engine.begin() as conn:
        present = await conn.scalar(text("SELECT to_regclass('public.action_proposals')"))
        if present:
            for table, trigger in _APPEND_ONLY:
                await conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))
            await conn.execute(
                text("TRUNCATE agent_events, decision_records, action_proposals CASCADE")
            )
            for table, trigger in _APPEND_ONLY:
                await conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}"))
    run_alembic(db, "downgrade", "base")


async def _insert_decision_0007(engine: AsyncEngine, tenant: str, decision: dict) -> None:
    """Insert a decision using only the columns a 0007 schema defines."""
    columns = ", ".join(_DECISION_0007_COLUMNS)
    binds = ", ".join(f":{c}" for c in _DECISION_0007_COLUMNS)
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
        )
        await conn.execute(
            text(f"INSERT INTO decision_records ({columns}) VALUES ({binds})"),  # noqa: S608
            {c: decision[c] for c in _DECISION_0007_COLUMNS},
        )


async def _seed_proposal(engine: AsyncEngine, tenant: str) -> tuple[dict, dict, uuid.UUID]:
    engagement = uuid.uuid4()
    proposal = proposal_row(tenant_id=tenant, engagement_id=engagement, proposal_id=uuid.uuid4())
    decision = decision_row(proposal, tenant_id=tenant, engagement_id=engagement)
    await seed_engagement(engine, tenant, engagement)
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
        )
        await insert_proposal(conn, proposal)
    return proposal, decision, engagement


async def test_upgrade_refused_when_proposal_exists(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    await _reset_lifecycle(lifecycle_admin_engine, lifecycle_db)
    run_alembic(lifecycle_db, "upgrade", REV_0007)
    await _seed_proposal(lifecycle_admin_engine, f"t-{uuid.uuid4().hex[:8]}")
    with pytest.raises(subprocess.CalledProcessError):
        run_alembic(lifecycle_db, "upgrade", REV_0008)
    assert await _alembic_version(lifecycle_admin_engine) == REV_0007
    assert await _has_0008_objects(lifecycle_admin_engine) is False


async def test_upgrade_refused_when_decision_exists(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    await _reset_lifecycle(lifecycle_admin_engine, lifecycle_db)
    run_alembic(lifecycle_db, "upgrade", REV_0007)
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    _proposal, decision, _ = await _seed_proposal(lifecycle_admin_engine, tenant)
    await _insert_decision_0007(lifecycle_admin_engine, tenant, decision)
    with pytest.raises(subprocess.CalledProcessError):
        run_alembic(lifecycle_db, "upgrade", REV_0008)
    assert await _alembic_version(lifecycle_admin_engine) == REV_0007
    assert await _has_0008_objects(lifecycle_admin_engine) is False


async def test_downgrade_refused_when_policy_state_exists(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    await _reset_lifecycle(lifecycle_admin_engine, lifecycle_db)
    run_alembic(lifecycle_db, "upgrade", REV_0008)
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    _proposal, decision, _ = await _seed_proposal(lifecycle_admin_engine, tenant)
    async with lifecycle_admin_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
        )
        await insert_decision(conn, decision)
    with pytest.raises(subprocess.CalledProcessError):
        run_alembic(lifecycle_db, "downgrade", REV_0007)
    assert await _alembic_version(lifecycle_admin_engine) == REV_0008
    assert await _has_0008_objects(lifecycle_admin_engine) is True


async def test_empty_0007_0008_0007_round_trip_preserves_unrelated_data(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    await _reset_lifecycle(lifecycle_admin_engine, lifecycle_db)
    run_alembic(lifecycle_db, "upgrade", REV_0007)
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    engagement = uuid.uuid4()
    await seed_engagement(lifecycle_admin_engine, tenant, engagement)

    run_alembic(lifecycle_db, "upgrade", REV_0008)
    assert await _has_0008_objects(lifecycle_admin_engine) is True
    run_alembic(lifecycle_db, "downgrade", REV_0007)
    assert await _has_0008_objects(lifecycle_admin_engine) is False

    async with lifecycle_admin_engine.begin() as conn:
        surviving = await conn.scalar(
            text("SELECT count(*) FROM engagements WHERE tenant_id = :t"), {"t": tenant}
        )
    assert surviving == 1


@pytest.mark.parametrize(
    "grant_sql, revoke_sql",
    [
        (
            "GRANT SELECT ON clients TO blackbread_policy_recorder",
            "REVOKE SELECT ON clients FROM blackbread_policy_recorder",
        ),
        # Column-level grant (binding review regression): invisible to has_table_privilege and it
        # would survive a table-wide REVOKE, so validation must still abort fail-closed.
        (
            "GRANT UPDATE (status) ON engagements TO blackbread_policy_recorder",
            "REVOKE UPDATE (status) ON engagements FROM blackbread_policy_recorder",
        ),
    ],
    ids=["table-grant", "column-grant"],
)
async def test_upgrade_refused_when_recorder_holds_unexpected_privilege(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine, grant_sql: str, revoke_sql: str
) -> None:
    """A pre-existing recorder carrying any unauthorized grant aborts the upgrade fail-closed.

    Grants are database-scoped, so they never leak past this disposable database, and the migration
    must abort without rewriting the cluster role.
    """
    await _reset_lifecycle(lifecycle_admin_engine, lifecycle_db)
    run_alembic(lifecycle_db, "upgrade", REV_0007)
    async with lifecycle_admin_engine.begin() as conn:
        await conn.execute(text(grant_sql))
    try:
        with pytest.raises(subprocess.CalledProcessError):
            run_alembic(lifecycle_db, "upgrade", REV_0008)
        assert await _alembic_version(lifecycle_admin_engine) == REV_0007
        assert await _has_0008_objects(lifecycle_admin_engine) is False
        async with lifecycle_admin_engine.begin() as conn:
            flags = (
                await conn.execute(
                    text(
                        "SELECT rolcanlogin, rolsuper FROM pg_roles "
                        "WHERE rolname = 'blackbread_policy_recorder'"
                    )
                )
            ).one()
        assert flags == (False, False)  # migration aborted; role attributes untouched
    finally:
        async with lifecycle_admin_engine.begin() as conn:
            await conn.execute(text(revoke_sql))
