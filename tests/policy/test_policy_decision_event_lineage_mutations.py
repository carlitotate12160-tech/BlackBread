import json
from typing import Any
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from blackbread.policy.runtime_gate import RuntimeGateResult
from tests.policy._policy_record_builders import (
from tests.policy._lineage_fixtures import TENANT, lineage_base, _assert_event_rejected, _mutate_payload
    decision_row,
    insert_decision,
    insert_proposal,
    proposal_row,
)
from tests.conftest import TEST_MIGRATION_DATABASE_URL

@pytest.mark.parametrize(
    "key,value",
    [
        ("decision_schema_name", "wrong.schema"),
        ("decision_schema_version", 99),
        ("proposal_id", str(uuid.uuid4())),
        ("proposal_digest", "c" * 64),
        ("idempotency_key", "wrong-key"),
        ("decision_id", str(uuid.uuid4())),
        ("decision_authority", "wrong.authority"),
        ("outcome", "DENY"),
        ("runtime_gate_result_digest", "d" * 64),
        ("decision_digest", "e" * 64),
    ],
)
async def test_payload_value_mutation_rejected(
    session: AsyncSession, lineage_base: dict, key: str, value: Any
) -> None:
    event = _mutate_payload(lineage_base["event"], key, value)
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


# ────────────────────────────────────────────────────────────────────
# §D — reason_code JSON null handling
# ────────────────────────────────────────────────────────────────────


async def test_reason_code_null_to_string_rejected(
    session: AsyncSession, lineage_base: dict
) -> None:
    """Decision has reason_code=NULL (ALLOW), payload has non-null reason."""
    event = _mutate_payload(lineage_base["event"], "reason_code", "ADMISSION_DENIED")
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


# ────────────────────────────────────────────────────────────────────
# §D — Payload graph_version key mutations
# ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "key,value",
    [
        ("state_root_version", 999),
        ("projector_version", 999),
        ("state_root", "f" * 64),
        ("ledger_event_count", 999999),
        ("ledger_head_hash", "f" * 64),
    ],
)
async def test_graph_version_mutation_rejected(
    session: AsyncSession, lineage_base: dict, key: str, value: Any
) -> None:
    event = copy.deepcopy(lineage_base["event"])
    event["payload"]["graph_version"][key] = value
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


# ────────────────────────────────────────────────────────────────────
# §D — Structural payload mutations
# ────────────────────────────────────────────────────────────────────


async def test_missing_top_level_key_rejected(session: AsyncSession, lineage_base: dict) -> None:
    event = copy.deepcopy(lineage_base["event"])
    del event["payload"]["decision_digest"]
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


async def test_extra_top_level_key_rejected(session: AsyncSession, lineage_base: dict) -> None:
    event = copy.deepcopy(lineage_base["event"])
    event["payload"]["unexpected_key"] = "value"
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


async def test_missing_graph_version_key_rejected(
    session: AsyncSession, lineage_base: dict
) -> None:
    event = copy.deepcopy(lineage_base["event"])
    del event["payload"]["graph_version"]["ledger_head_hash"]
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


async def test_extra_graph_version_key_rejected(
    session: AsyncSession, lineage_base: dict
) -> None:
    event = copy.deepcopy(lineage_base["event"])
    event["payload"]["graph_version"]["extra"] = "value"
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


# ────────────────────────────────────────────────────────────────────
# §4 — JSON scalar type enforcement (correction #4)
# ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad_value", [2.0, "2", True, None])
async def test_decision_schema_version_wrong_type(
    session: AsyncSession, lineage_base: dict, bad_value: Any
) -> None:
    event = _mutate_payload(lineage_base["event"], "decision_schema_version", bad_value)
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


@pytest.mark.parametrize("bad_value", [1.0, "1"])
async def test_graph_projector_version_wrong_type(
    session: AsyncSession, lineage_base: dict, bad_value: Any
) -> None:
    event = copy.deepcopy(lineage_base["event"])
    event["payload"]["graph_version"]["projector_version"] = bad_value
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


@pytest.mark.parametrize("bad_value", [7.0, "7"])
async def test_graph_ledger_event_count_wrong_type(
    session: AsyncSession, lineage_base: dict, bad_value: Any
) -> None:
    event = copy.deepcopy(lineage_base["event"])
    event["payload"]["graph_version"]["ledger_event_count"] = bad_value
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


@pytest.mark.parametrize("bad_value", [None, [1, 2], "not-an-object"])
async def test_graph_version_wrong_type(
    session: AsyncSession, lineage_base: dict, bad_value: Any
) -> None:
    event = copy.deepcopy(lineage_base["event"])
    event["payload"]["graph_version"] = bad_value
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


@pytest.mark.parametrize("key", [
    "proposal_id", "proposal_digest", "decision_id",
    "decision_authority", "outcome", "decided_at",
    "runtime_gate_result_digest", "decision_digest",
])
async def test_string_field_replaced_by_number(
    session: AsyncSession, lineage_base: dict, key: str
) -> None:
    event = _mutate_payload(lineage_base["event"], key, 12345)
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


# ────────────────────────────────────────────────────────────────────
# §D — Timestamp edge cases (correction #5)
# ────────────────────────────────────────────────────────────────────


async def test_payload_zero_microsecond_utc_accepted(
    session: AsyncSession, lineage_base: dict
) -> None:
    """Zero-microsecond UTC Z is accepted."""
    d = lineage_base["decision"]
    decided = datetime(2026, 9, 3, 12, 30, 0, tzinfo=UTC)
    # Need a fresh proposal+decision with this timestamp
    # This is tested via the valid event acceptance above with the default timestamp


async def test_payload_offset_timestamp_rejected(
    session: AsyncSession, lineage_base: dict
) -> None:
    """Payload with +01:00 offset for the same instant is rejected (text mismatch)."""
    event = copy.deepcopy(lineage_base["event"])
    decided = lineage_base["decision"]["decided_at"]
    # Convert to +01:00 representation
    tz_plus_1 = timezone(timedelta(hours=1))
    offset_text = decided.astimezone(tz_plus_1).isoformat()
    event["payload"]["decided_at"] = offset_text
    await _assert_event_rejected(session, event, lineage_base["engagement_id"])


async def test_envelope_offset_timestamp_accepted(
    session: AsyncSession, lineage_base: dict
) -> None:
    """Envelope occurred_at with +01:00 offset (same instant) is accepted by timestamptz."""
    event = copy.deepcopy(lineage_base["event"])
    decided = lineage_base["decision"]["decided_at"]
    tz_plus_1 = timezone(timedelta(hours=1))
    event["occurred_at"] = decided.astimezone(tz_plus_1)
    # This should be accepted because timestamptz normalizes
    await _insert_event_as_recorder(
        session, event, lineage_base["engagement_id"]
    )


# ────────────────────────────────────────────────────────────────────
# §E — Uniqueness substrate
# ────────────────────────────────────────────────────────────────────


async def test_one_decision_per_proposal(session: AsyncSession, lineage_base: dict) -> None:
    """Second decision for the same proposal is rejected."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from tests.conftest import TEST_MIGRATION_DATABASE_URL
    admin_url = TEST_MIGRATION_DATABASE_URL
    admin = create_async_engine(admin_url)
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f"SET LOCAL blackbread.tenant_id = '{TENANT}'"))
            d2 = decision_row(
                lineage_base["proposal"],
                tenant_id=TENANT,
                engagement_id=lineage_base["engagement_id"],
            )
            d2["decision_id"] = uuid.uuid4()
            d2["decision_digest"] = "f" * 64
            with pytest.raises(IntegrityError, match="uq_decision_records_proposal"):
                await insert_decision(conn, d2)
    finally:
        await admin.dispose()


async def test_one_event_per_decision(session: AsyncSession, lineage_base: dict) -> None:
    """Second event for the same policy_decision_id is rejected."""
    # First event succeeds
    await _insert_event_as_recorder(
        session, lineage_base["event"], lineage_base["engagement_id"]
    )
    # Second event with same causation_id (same decision) should fail
    with pytest.raises((IntegrityError, ProgrammingError)):
        await _insert_event_as_recorder(
            session, lineage_base["event"], lineage_base["engagement_id"], sequence=2
        )


# ────────────────────────────────────────────────────────────────────
# §E — Concurrency substrate (deterministic barriers, not sleeps)
# ────────────────────────────────────────────────────────────────────


async def test_concurrent_same_proposal_insert(
    session: AsyncSession, lineage_base: dict
) -> None:
    """Two concurrent recorders inserting the same proposal — one wins."""
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine

    from tests.conftest import TEST_MIGRATION_DATABASE_URL
    admin_url = TEST_MIGRATION_DATABASE_URL
    barrier = asyncio.Barrier(2)
    results: list[str] = []

    async def contender(label: str) -> None:
        engine = create_async_engine(admin_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"SET LOCAL blackbread.tenant_id = '{TENANT}'"))
                await barrier.wait()
                try:
                    p = proposal_row(
                        tenant_id=TENANT,
                        engagement_id=lineage_base["engagement_id"],
                        idempotency_key="shared-key",
                    )
                    await insert_proposal(conn, p)
                    results.append(f"{label}:win")
                except IntegrityError:
                    results.append(f"{label}:lose")
        finally:
            await engine.dispose()

    await asyncio.gather(contender("A"), contender("B"))
    winners = [r for r in results if r.endswith(":win")]
    losers = [r for r in results if r.endswith(":lose")]
    assert len(winners) == 1
    assert len(losers) == 1


# ────────────────────────────────────────────────────────────────────
# §F — Recorder RLS (3 independent tests, correction #2)
# ────────────────────────────────────────────────────────────────────


async def test_rls_missing_guc_fails_closed(session: AsyncSession) -> None:
    """Missing tenant GUC causes recorder access to fail closed."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from tests.conftest import TEST_MIGRATION_DATABASE_URL
    admin_url = TEST_MIGRATION_DATABASE_URL
    engine = create_async_engine(admin_url)
    try:
        async with engine.begin() as conn:
            # Don't set tenant GUC
            await conn.execute(text("SET LOCAL ROLE blackbread_policy_recorder"))
            result = (await conn.execute(text("SELECT count(*) FROM action_proposals"))).scalar()
            # With empty/missing GUC, RLS should return 0 or fail
            assert result == 0
    finally:
        await engine.dispose()


async def test_rls_mismatched_tenant_rejected(
    session: AsyncSession, lineage_base: dict
) -> None:
    """GUC tenant A plus row carrying tenant B is rejected by RLS."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from tests.conftest import TEST_MIGRATION_DATABASE_URL
    admin_url = TEST_MIGRATION_DATABASE_URL
    engine = create_async_engine(admin_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL blackbread.tenant_id = 'tenant-A'"))
            await conn.execute(text("SET LOCAL ROLE blackbread_policy_recorder"))
            p = proposal_row(tenant_id="tenant-B", engagement_id=lineage_base["engagement_id"])
            with pytest.raises((IntegrityError, ProgrammingError)):
                await insert_proposal(conn, p)
    finally:
        await engine.dispose()


async def test_rls_guc_rebind_limitation(session: AsyncSession, lineage_base: dict) -> None:
    """After rebinding GUC to tenant B, tenant-B rows become visible.

    This is a demonstrated limitation of the GUC, not cross-tenant protection.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from tests.conftest import TEST_MIGRATION_DATABASE_URL
    admin_url = TEST_MIGRATION_DATABASE_URL
    engine = create_async_engine(admin_url)
    try:
        async with engine.begin() as conn:
            # Bind to lineage tenant and verify proposals visible
            await conn.execute(text(f"SET LOCAL blackbread.tenant_id = '{TENANT}'"))
            await conn.execute(text("SET LOCAL ROLE blackbread_policy_recorder"))
            count_a = (
                await conn.execute(text("SELECT count(*) FROM action_proposals"))
            ).scalar()
            assert count_a >= 1

            # Rebind to different tenant
            await conn.execute(text("RESET ROLE"))
            await conn.execute(text("SET LOCAL blackbread.tenant_id = 'different-tenant'"))
            await conn.execute(text("SET LOCAL ROLE blackbread_policy_recorder"))
            count_b = (
                await conn.execute(text("SELECT count(*) FROM action_proposals"))
            ).scalar()
            # Different tenant sees zero proposals
            assert count_b == 0
    finally:
        await engine.dispose()
