"""M1.4c2b0a recorder-role identity lifecycle, rejection, downgrade, and reconciliation proofs.

Runs against the private throwaway lifecycle database; it never mutates the shared or Oracle
production database irreversibly. Because the recorder role is cluster-global and M1.4c2b0b (0009)
grants it authority on the shared database, this module runs while those shared grants are suspended
(``suspend_shared_authority_head``) so the revision-0008 proofs observe -- and may drop and recreate
-- a dependency-free role; head is always restored in ``finally``.

Proves create-from-absent and the exact committed shape; clean pre-existing continuity with an
unchanged OID; the attribute/identity rejection matrix leaves Alembic at 0007 without silently
normalising the role; the downgrade round trip and its dependency-guarded and missing-role aborts;
and the commit-ambiguity reconciliation matrix over real committed and rolled-back transactions. The
role-dependency and membership rejection matrices moved to
``test_policy_record_authority_lifecycle.py`` with the 0009 authority they now share.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import TEST_MIGRATION_DATABASE_URL
from tests.policy._policy_record_authority_support import (
    _CREATE_CLEAN,
    RECORDER_ROLE,
    REV_0007,
    REV_0008,
    alembic_expecting_failure,
    alembic_version,
    dependency_counts,
    drop_recorder,
    ensure_clean_recorder,
    lifecycle_url,
    recorder_oid,
    recorder_present,
    reset_to,
    run_admin,
    run_alembic_step,
    suspend_shared_authority_head,  # noqa: F401 -- module suspend fixture applied via pytestmark
)
from tests.policy.conftest import ROOT

pytestmark = pytest.mark.usefixtures("suspend_shared_authority_head")

_MIGRATION_FILE = ROOT / "migrations" / "versions" / "0008_m1_policy_recorder_identity.py"


def _load_reconciler() -> Any:
    """Import migration 0008 by path to exercise its pure commit-ambiguity classifier."""
    spec = importlib.util.spec_from_file_location("_m0008_identity", _MIGRATION_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.reconcile_recorder_migration_state


async def test_upgrade_creates_recorder_from_absent(
    lifecycle_db: str, lifecycle_admin_engine: Any
) -> None:
    reset_to(lifecycle_db, REV_0007)
    await drop_recorder()
    assert not await recorder_present(lifecycle_admin_engine)

    run_alembic_step(lifecycle_db, "upgrade", REV_0008)

    assert await alembic_version(lifecycle_admin_engine) == REV_0008
    assert await recorder_present(lifecycle_admin_engine)
    assert await dependency_counts(lifecycle_admin_engine) == (0, 0, 0)


async def test_clean_pre_existing_role_preserved_with_same_oid(
    lifecycle_db: str, lifecycle_admin_engine: Any
) -> None:
    reset_to(lifecycle_db, REV_0007)
    await ensure_clean_recorder()
    oid_before = await recorder_oid(lifecycle_admin_engine)

    run_alembic_step(lifecycle_db, "upgrade", REV_0008)

    assert await alembic_version(lifecycle_admin_engine) == REV_0008
    assert await recorder_oid(lifecycle_admin_engine) == oid_before, "role was dropped/recreated"


# label -> ``ALTER ROLE`` fragment that breaks the exact inert shape. Cleanup recreates the role (no
# ``NO VALID UNTIL`` clause exists), restoring the exact inert identity uniformly for every case.
_ATTRIBUTE_CASES: tuple[tuple[str, str], ...] = (
    ("login", "LOGIN"),
    ("inherit", "INHERIT"),
    ("superuser", "SUPERUSER"),
    ("createdb", "CREATEDB"),
    ("createrole", "CREATEROLE"),
    ("replication", "REPLICATION"),
    ("bypassrls", "BYPASSRLS"),
    ("connlimit", "CONNECTION LIMIT 5"),
    ("password", "PASSWORD 'not-inert'"),
    ("validity", "VALID UNTIL '2030-01-01'"),
    ("role_setting", "SET search_path = public"),
)


@pytest.mark.parametrize(
    ("label", "break_frag"), _ATTRIBUTE_CASES, ids=[case[0] for case in _ATTRIBUTE_CASES]
)
async def test_upgrade_rejects_non_inert_role(
    lifecycle_db: str, lifecycle_admin_engine: Any, label: str, break_frag: str
) -> None:
    reset_to(lifecycle_db, REV_0007)
    await ensure_clean_recorder()
    oid_before = await recorder_oid(lifecycle_admin_engine)
    await run_admin(f"ALTER ROLE {RECORDER_ROLE} {break_frag}")
    try:
        output = alembic_expecting_failure(lifecycle_db, "upgrade", REV_0008)
        assert RECORDER_ROLE in output, f"{label}: failure must name the recorder role"
        assert await alembic_version(lifecycle_admin_engine) == REV_0007
        # No silent normalisation: the role is still present and the same object.
        assert await recorder_oid(lifecycle_admin_engine) == oid_before
    finally:
        await ensure_clean_recorder()


async def test_downgrade_round_trip_toggles_role_presence(
    lifecycle_db: str, lifecycle_admin_engine: Any
) -> None:
    reset_to(lifecycle_db, REV_0007)
    await drop_recorder()

    run_alembic_step(lifecycle_db, "upgrade", REV_0008)
    assert await recorder_present(lifecycle_admin_engine)

    run_alembic_step(lifecycle_db, "downgrade", REV_0007)
    assert await alembic_version(lifecycle_admin_engine) == REV_0007
    assert not await recorder_present(lifecycle_admin_engine)

    run_alembic_step(lifecycle_db, "upgrade", REV_0008)
    assert await alembic_version(lifecycle_admin_engine) == REV_0008
    assert await recorder_present(lifecycle_admin_engine)


async def test_downgrade_aborts_when_role_has_dependency(
    lifecycle_db: str, lifecycle_admin_engine: Any
) -> None:
    reset_to(lifecycle_db, REV_0007)
    await drop_recorder()
    run_alembic_step(lifecycle_db, "upgrade", REV_0008)

    probe_url = lifecycle_url(lifecycle_db)
    await run_admin(
        (
            "CREATE TABLE downgrade_probe (id int)",
            f"ALTER TABLE downgrade_probe OWNER TO {RECORDER_ROLE}",
        ),
        url=probe_url,
    )
    try:
        output = alembic_expecting_failure(lifecycle_db, "downgrade", REV_0007)
        assert RECORDER_ROLE in output
        assert await alembic_version(lifecycle_admin_engine) == REV_0008
        assert await recorder_present(lifecycle_admin_engine)
    finally:
        await run_admin("DROP TABLE IF EXISTS downgrade_probe", url=probe_url)


async def test_downgrade_aborts_when_recorder_role_is_missing(
    lifecycle_db: str, lifecycle_admin_engine: Any
) -> None:
    """A missing recorder role during downgrade must abort at 0008, not silently advance to 0007."""
    reset_to(lifecycle_db, REV_0007)
    await drop_recorder()
    run_alembic_step(lifecycle_db, "upgrade", REV_0008)
    assert await recorder_present(lifecycle_admin_engine)

    # A privileged actor deletes the recorder out-of-band between the upgrade and the downgrade.
    await drop_recorder()
    assert not await recorder_present(lifecycle_admin_engine)

    output = alembic_expecting_failure(lifecycle_db, "downgrade", REV_0007)
    assert RECORDER_ROLE in output, "failure must name the recorder role"
    assert "missing" in output.lower(), "failure must report the missing recorder-role state"
    assert await alembic_version(lifecycle_admin_engine) == REV_0008
    assert not await recorder_present(lifecycle_admin_engine)
    # Restore the exact clean role so ordering and module teardown are not poisoned.
    await ensure_clean_recorder()


async def test_commit_ambiguity_reconciliation_matrix(
    lifecycle_db: str, lifecycle_admin_engine: Any
) -> None:
    reconcile = _load_reconciler()

    # Committed success: a real committed upgrade leaves version 0008 and a clean role.
    reset_to(lifecycle_db, REV_0007)
    await drop_recorder()
    run_alembic_step(lifecycle_db, "upgrade", REV_0008)
    version = await alembic_version(lifecycle_admin_engine)
    present = await recorder_present(lifecycle_admin_engine)
    clean = await dependency_counts(lifecycle_admin_engine) == (0, 0, 0)
    assert reconcile(version_num=version, role_present=present, role_clean=clean) == "committed"

    # Not committed, role absent or exactly pre-existing: safe to retry.
    run_alembic_step(lifecycle_db, "downgrade", REV_0007)
    await drop_recorder()
    version = await alembic_version(lifecycle_admin_engine)
    assert reconcile(version_num=version, role_present=False, role_clean=False) == "retry"
    await ensure_clean_recorder()
    assert reconcile(version_num=REV_0007, role_present=True, role_clean=True) == "retry"

    # Mixed/unexpected: committed version but role gone -> stop; do not retry blindly.
    assert reconcile(version_num=REV_0008, role_present=False, role_clean=False) == "stop"

    # A rolled-back CREATE ROLE transaction really leaves the role absent (not a Python mock).
    await drop_recorder()
    admin = create_async_engine(TEST_MIGRATION_DATABASE_URL)
    try:
        async with admin.connect() as conn:
            transaction = await conn.begin()
            await conn.execute(text(_CREATE_CLEAN))
            await transaction.rollback()
    finally:
        await admin.dispose()
    assert not await recorder_present(lifecycle_admin_engine)
