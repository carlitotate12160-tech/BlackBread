"""M1.4c2b0b migration 0009 upgrade/downgrade/re-upgrade lifecycle and moved role-dependency proofs.

Runs against the private throwaway lifecycle database; the cluster-global recorder role's shared
0009 grants are suspended for the module (see ``suspend_shared_authority_head``) so revision-0008
dependency proofs observe a dependency-free role. Proves the ``0008 -> 0009 -> 0008 -> 0009`` round
trip, exact grant/object installation and revocation, the data-present downgrade refusal, and the
fail-closed rejection of a recorder that already owns objects, holds grants, or has a membership
when 0008 (re)establishes its inert identity.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.policy._policy_record_authority_support import (
    RECORDER_ROLE,
    REV_0007,
    REV_0008,
    REV_0009,
    alembic_expecting_failure,
    alembic_version,
    clear_policy_rows_before_base_downgrade,  # noqa: F401 -- session cleanup autouse fixture
    dependency_counts,
    ensure_clean_recorder,
    lifecycle_url,
    open_recorder_txn,
    reset_to,
    run_admin,
    run_alembic_step,
    suspend_shared_authority_head,  # noqa: F401 -- module suspend fixture applied via pytestmark
    table_privilege,
    truncate_policy_rows,
)
from tests.policy._policy_record_builders import (
    decision_event_row,
    decision_row,
    insert_agent_event,
    insert_decision,
    insert_proposal,
    proposal_row,
)
from tests.policy.conftest import seed_engagement

pytestmark = pytest.mark.usefixtures("suspend_shared_authority_head")

PROBE_ROLE = "blackbread_recorder_probe"


async def _column_exists(engine: AsyncEngine, column: str) -> bool:
    async with engine.connect() as conn:
        return bool(
            await conn.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'agent_events' AND column_name = :c)"
                ),
                {"c": column},
            )
        )


async def _seed_proposal_decision(
    engine: AsyncEngine,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    tenant_id = f"tenant-{uuid.uuid4().hex[:12]}"
    engagement_id = uuid.uuid4()
    await seed_engagement(engine, tenant_id, engagement_id)
    proposal = proposal_row(
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        proposal_id=uuid.uuid4(),
        idempotency_key=f"idem-{uuid.uuid4().hex[:10]}",
    )
    decision = decision_row(proposal)
    async with engine.begin() as conn:
        await insert_proposal(conn, proposal)
        await insert_decision(conn, decision)
    return tenant_id, proposal, decision


async def test_upgrade_installs_grants_lineage_and_dependencies(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    reset_to(lifecycle_db, REV_0008)
    run_alembic_step(lifecycle_db, "upgrade", REV_0009)

    assert await alembic_version(lifecycle_admin_engine) == REV_0009
    for table, privilege in (
        ("action_proposals", "SELECT"),
        ("decision_records", "SELECT"),
        ("agent_events", "INSERT"),
    ):
        assert await table_privilege(lifecycle_admin_engine, RECORDER_ROLE, table, privilege)
    assert await _column_exists(lifecycle_admin_engine, "policy_decision_id")
    shdepend, members, settings = await dependency_counts(lifecycle_admin_engine)
    assert shdepend >= 1, "0009 grants must create recorder shared dependencies"
    assert (members, settings) == (0, 0), "0009 adds no membership or role setting"


async def test_empty_downgrade_restores_0008_then_reupgrades(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    reset_to(lifecycle_db, REV_0008)
    run_alembic_step(lifecycle_db, "upgrade", REV_0009)
    run_alembic_step(lifecycle_db, "downgrade", REV_0008)

    assert await alembic_version(lifecycle_admin_engine) == REV_0008
    assert not await table_privilege(
        lifecycle_admin_engine, RECORDER_ROLE, "action_proposals", "SELECT"
    )
    assert not await table_privilege(
        lifecycle_admin_engine, RECORDER_ROLE, "agent_events", "INSERT"
    )
    assert not await _column_exists(lifecycle_admin_engine, "policy_decision_id")
    assert await dependency_counts(lifecycle_admin_engine) == (0, 0, 0)

    # Deterministic re-upgrade re-establishes the authority.
    run_alembic_step(lifecycle_db, "upgrade", REV_0009)
    assert await alembic_version(lifecycle_admin_engine) == REV_0009
    assert await table_privilege(
        lifecycle_admin_engine, RECORDER_ROLE, "action_proposals", "SELECT"
    )


async def test_downgrade_refuses_while_proposals_exist(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    reset_to(lifecycle_db, REV_0009)
    tenant_id = f"tenant-{uuid.uuid4().hex[:12]}"
    engagement_id = uuid.uuid4()
    await seed_engagement(lifecycle_admin_engine, tenant_id, engagement_id)
    proposal = proposal_row(
        tenant_id=tenant_id, engagement_id=engagement_id, proposal_id=uuid.uuid4()
    )
    async with lifecycle_admin_engine.begin() as conn:
        await insert_proposal(conn, proposal)
    try:
        output = alembic_expecting_failure(lifecycle_db, "downgrade", REV_0008)
        assert "action proposals" in output or "in use" in output
        assert await alembic_version(lifecycle_admin_engine) == REV_0009
    finally:
        await truncate_policy_rows(lifecycle_url(lifecycle_db))


async def test_downgrade_refuses_while_decision_events_exist(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    reset_to(lifecycle_db, REV_0009)
    tenant_id, proposal, decision = await _seed_proposal_decision(lifecycle_admin_engine)
    row = decision_event_row(proposal, decision)
    async with lifecycle_admin_engine.connect() as conn:
        transaction = await conn.begin()
        await open_recorder_txn(conn, tenant_id)
        await insert_agent_event(conn, row)
        await transaction.commit()
    try:
        output = alembic_expecting_failure(lifecycle_db, "downgrade", REV_0008)
        assert "decision" in output.lower() or "in use" in output
        assert await alembic_version(lifecycle_admin_engine) == REV_0009
    finally:
        await truncate_policy_rows(lifecycle_url(lifecycle_db))


# --- moved role-dependency rejection cases (0008 re-establishing the inert identity) ---------

_DEPENDENCY_CASES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "owned_table",
        ("CREATE TABLE probe_t (id int)", f"ALTER TABLE probe_t OWNER TO {RECORDER_ROLE}"),
        ("DROP TABLE IF EXISTS probe_t",),
    ),
    (
        "owned_schema",
        (f"CREATE SCHEMA probe_s AUTHORIZATION {RECORDER_ROLE}",),
        ("DROP SCHEMA IF EXISTS probe_s CASCADE",),
    ),
    (
        "table_grant",
        ("CREATE TABLE probe_t (id int)", f"GRANT SELECT ON probe_t TO {RECORDER_ROLE}"),
        ("DROP TABLE IF EXISTS probe_t",),
    ),
    (
        "column_grant",
        (
            "CREATE TABLE probe_t (id int, secret int)",
            f"GRANT SELECT (secret) ON probe_t TO {RECORDER_ROLE}",
        ),
        ("DROP TABLE IF EXISTS probe_t",),
    ),
    (
        "default_acl",
        (f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {RECORDER_ROLE}",),
        (
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "  # noqa: S608 - static DDL, role name only
            f"REVOKE SELECT ON TABLES FROM {RECORDER_ROLE}",
        ),
    ),
    (
        "rls_policy",
        (
            "CREATE TABLE probe_t (id int)",
            f"CREATE POLICY probe_pol ON probe_t FOR SELECT TO {RECORDER_ROLE} USING (true)",
        ),
        ("DROP TABLE IF EXISTS probe_t",),
    ),
)


@pytest.mark.parametrize(
    ("label", "setup", "cleanup"), _DEPENDENCY_CASES, ids=[c[0] for c in _DEPENDENCY_CASES]
)
async def test_upgrade_rejects_recorder_with_direct_dependency(
    lifecycle_db: str,
    lifecycle_admin_engine: AsyncEngine,
    label: str,
    setup: tuple[str, ...],
    cleanup: tuple[str, ...],
) -> None:
    reset_to(lifecycle_db, REV_0007)
    await ensure_clean_recorder()
    probe_url = lifecycle_url(lifecycle_db)
    await run_admin(setup, url=probe_url)
    try:
        output = alembic_expecting_failure(lifecycle_db, "upgrade", REV_0008)
        assert RECORDER_ROLE in output, f"{label}: failure must name the recorder role"
        assert await alembic_version(lifecycle_admin_engine) == REV_0007
    finally:
        await run_admin(cleanup, url=probe_url)
        await ensure_clean_recorder()


_MEMBERSHIP_CASES = (
    ("recorder_is_member", f"GRANT {PROBE_ROLE} TO {RECORDER_ROLE}"),
    ("recorder_has_member", f"GRANT {RECORDER_ROLE} TO {PROBE_ROLE}"),
)


@pytest.mark.parametrize(
    ("label", "grant_sql"), _MEMBERSHIP_CASES, ids=[c[0] for c in _MEMBERSHIP_CASES]
)
async def test_upgrade_rejects_recorder_with_membership(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine, label: str, grant_sql: str
) -> None:
    reset_to(lifecycle_db, REV_0007)
    await ensure_clean_recorder()
    await run_admin((f"CREATE ROLE {PROBE_ROLE} NOLOGIN", grant_sql))
    try:
        output = alembic_expecting_failure(lifecycle_db, "upgrade", REV_0008)
        assert RECORDER_ROLE in output, f"{label}: failure must name the recorder role"
        assert await alembic_version(lifecycle_admin_engine) == REV_0007
    finally:
        await run_admin(f"DROP ROLE IF EXISTS {PROBE_ROLE}")


# --- 0009 authority gate: a recorder altered after 0008 must be refused reserved authority ------

_AUTHORITY_GATE_CASES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "inherit",
        (f"ALTER ROLE {RECORDER_ROLE} INHERIT",),
        (f"ALTER ROLE {RECORDER_ROLE} NOINHERIT",),
    ),
    (
        "password",
        (f"ALTER ROLE {RECORDER_ROLE} PASSWORD 'probe-secret'",),
        (f"ALTER ROLE {RECORDER_ROLE} PASSWORD NULL",),
    ),
    (
        "createdb",
        (f"ALTER ROLE {RECORDER_ROLE} CREATEDB",),
        (f"ALTER ROLE {RECORDER_ROLE} NOCREATEDB",),
    ),
    (
        "role_setting",
        (f"ALTER ROLE {RECORDER_ROLE} SET search_path = public",),
        (f"ALTER ROLE {RECORDER_ROLE} RESET search_path",),
    ),
    (
        "member_of",
        (f"CREATE ROLE {PROBE_ROLE} NOLOGIN", f"GRANT {PROBE_ROLE} TO {RECORDER_ROLE}"),
        (
            f"REVOKE {PROBE_ROLE} FROM {RECORDER_ROLE}",
            f"DROP ROLE IF EXISTS {PROBE_ROLE}",
        ),
    ),
    (
        "has_member",
        (f"CREATE ROLE {PROBE_ROLE} NOLOGIN", f"GRANT {RECORDER_ROLE} TO {PROBE_ROLE}"),
        (
            f"REVOKE {RECORDER_ROLE} FROM {PROBE_ROLE}",
            f"DROP ROLE IF EXISTS {PROBE_ROLE}",
        ),
    ),
    (
        "owned_object",
        (
            "CREATE TABLE probe_auth_t (id int)",
            f"ALTER TABLE probe_auth_t OWNER TO {RECORDER_ROLE}",
        ),
        ("DROP TABLE IF EXISTS probe_auth_t",),
    ),
)


@pytest.mark.parametrize(
    ("label", "setup", "cleanup"), _AUTHORITY_GATE_CASES, ids=[c[0] for c in _AUTHORITY_GATE_CASES]
)
async def test_upgrade_to_authority_rejects_altered_recorder(
    lifecycle_db: str,
    lifecycle_admin_engine: AsyncEngine,
    label: str,
    setup: tuple[str, ...],
    cleanup: tuple[str, ...],
) -> None:
    """0009 must fail closed when the recorder drifted from its inert 0008 shape before grants."""
    reset_to(lifecycle_db, REV_0008)
    await ensure_clean_recorder()
    probe_url = lifecycle_url(lifecycle_db)
    await run_admin(setup, url=probe_url)
    try:
        output = alembic_expecting_failure(lifecycle_db, "upgrade", REV_0009)
        assert RECORDER_ROLE in output, f"{label}: failure must name the recorder role"
        assert await alembic_version(lifecycle_admin_engine) == REV_0008
    finally:
        await run_admin(cleanup, url=probe_url)
        await ensure_clean_recorder()


async def test_upgrade_rejects_dependency_in_second_database(
    lifecycle_db: str, lifecycle_admin_engine: AsyncEngine
) -> None:
    """A cluster-wide pg_shdepend check must detect a recorder dependency in a *second* database."""
    reset_to(lifecycle_db, REV_0007)
    await ensure_clean_recorder()
    other_db = f"blackbread_test_authlc_{uuid.uuid4().hex[:8]}"
    await run_admin(f"CREATE DATABASE {other_db}")
    other = create_async_engine(lifecycle_url(other_db), isolation_level="AUTOCOMMIT")
    try:
        async with other.connect() as conn:
            await conn.execute(text("CREATE TABLE cross_db_probe (id int)"))
            await conn.execute(text(f"ALTER TABLE cross_db_probe OWNER TO {RECORDER_ROLE}"))
        output = alembic_expecting_failure(lifecycle_db, "upgrade", REV_0008)
        assert RECORDER_ROLE in output
        assert await alembic_version(lifecycle_admin_engine) == REV_0007
    finally:
        async with other.connect() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS cross_db_probe"))
        await other.dispose()
        await run_admin(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "  # noqa: S608
            f"WHERE datname = '{other_db}' AND pid <> pg_backend_pid()"
        )
        await run_admin(f"DROP DATABASE IF EXISTS {other_db}")
