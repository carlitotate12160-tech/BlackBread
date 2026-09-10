"""M1.4c2b0 payload, JSON-type, timestamp, uniqueness, concurrency, and RLS lineage proofs.

Each payload mutation changes one field of a coherent policy event and asserts the trigger rejects
it, attributing the rejection to the intended invariant. JSON scalar-type counterexamples prove the
trigger enforces the strict released c2a schema even where jsonb would treat values as numerically
equal. Run against real PostgreSQL 17.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from blackbread.ledger.hashing import canonical_timestamp
from tests.policy._policy_record_builders import (
    decision_row,
    insert_decision,
    insert_proposal,
    policy_event_row,
    proposal_row,
)
from tests.policy.conftest import (
    LINEAGE_TENANT,
    assert_recorder_insert_rejected,
    insert_event_as_recorder,
    reset_policy_state,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
async def _clean_policy_state(policy_admin_engine):
    """Leave the policy tables empty after each test in this module."""
    yield
    await reset_policy_state(policy_admin_engine)


# Both messages are the trigger's own: a structural/value divergence or the canonical-integer
# guard. Attributing to either (never to a foreign constraint) proves the trigger did the work.
_PAYLOAD_MATCH = "payload does not match the stored decision lineage|canonical decimal text"


def _payload_event(base: dict, mutate) -> dict[str, Any]:
    event = copy.deepcopy(base["event"])
    mutate(event["payload"])
    return event


# ── Payload value mutations (top-level keys) ─────────────────────────────────


@pytest.mark.parametrize(
    "key, value",
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
    policy_admin_engine: AsyncEngine, lineage_base: dict, key: str, value: Any
) -> None:
    event = _payload_event(lineage_base, lambda p: p.__setitem__(key, value))
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


@pytest.mark.parametrize(
    "key, value",
    [
        ("state_root_version", 999),
        ("projector_version", 999),
        ("state_root", "f" * 64),
        ("ledger_event_count", 999999),
        ("ledger_head_hash", "f" * 64),
    ],
)
async def test_graph_version_value_mutation_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict, key: str, value: Any
) -> None:
    event = _payload_event(lineage_base, lambda p: p["graph_version"].__setitem__(key, value))
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


# ── Structural payload mutations ─────────────────────────────────────────────


async def test_empty_payload_rejected(policy_admin_engine: AsyncEngine, lineage_base: dict) -> None:
    await assert_recorder_insert_rejected(
        policy_admin_engine, _payload_event(lineage_base, lambda p: p.clear()), match=_PAYLOAD_MATCH
    )


async def test_empty_graph_version_object_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    event = _payload_event(lineage_base, lambda p: p.__setitem__("graph_version", {}))
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


async def test_missing_top_level_key_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    event = _payload_event(lineage_base, lambda p: p.pop("decision_digest"))
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


async def test_extra_top_level_key_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    event = _payload_event(lineage_base, lambda p: p.__setitem__("extra", "x"))
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


async def test_missing_graph_version_key_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    event = _payload_event(lineage_base, lambda p: p["graph_version"].pop("ledger_head_hash"))
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


async def test_extra_graph_version_key_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    event = _payload_event(lineage_base, lambda p: p["graph_version"].__setitem__("extra", "x"))
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


# ── JSON scalar-type enforcement (correction #4) ─────────────────────────────


@pytest.mark.parametrize("bad", [2.0, "2", True, None])
async def test_decision_schema_version_scalar_type_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict, bad: Any
) -> None:
    event = _payload_event(lineage_base, lambda p: p.__setitem__("decision_schema_version", bad))
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


@pytest.mark.parametrize("bad", [1.0, "1"])
async def test_projector_version_scalar_type_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict, bad: Any
) -> None:
    event = _payload_event(
        lineage_base, lambda p: p["graph_version"].__setitem__("projector_version", bad)
    )
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


@pytest.mark.parametrize("bad", [7.0, "7"])
async def test_ledger_event_count_scalar_type_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict, bad: Any
) -> None:
    event = _payload_event(
        lineage_base, lambda p: p["graph_version"].__setitem__("ledger_event_count", bad)
    )
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


@pytest.mark.parametrize("bad", [None, [1, 2], "not-an-object"])
async def test_graph_version_not_object_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict, bad: Any
) -> None:
    event = _payload_event(lineage_base, lambda p: p.__setitem__("graph_version", bad))
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


@pytest.mark.parametrize(
    "key",
    [
        "proposal_id",
        "proposal_digest",
        "decision_id",
        "decision_authority",
        "outcome",
        "decided_at",
        "runtime_gate_result_digest",
        "decision_digest",
    ],
)
async def test_string_field_replaced_by_number_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict, key: str
) -> None:
    event = _payload_event(lineage_base, lambda p: p.__setitem__(key, 12345))
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


# ── reason_code JSON null handling ───────────────────────────────────────────


async def test_reason_code_string_when_decision_null_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    """Decision is ALLOW (reason_code NULL); payload carrying a string reason is rejected."""
    event = _payload_event(lineage_base, lambda p: p.__setitem__("reason_code", "ADMISSION_DENIED"))
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


async def test_reason_code_null_matches_null_decision_accepted(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    """The baseline ALLOW decision has reason_code NULL and payload JSON null; it is accepted."""
    assert lineage_base["event"]["payload"]["reason_code"] is None
    await insert_event_as_recorder(policy_admin_engine, lineage_base["event"])


async def test_reason_code_string_matches_deny_decision_accepted(
    policy_admin_engine: AsyncEngine,
) -> None:
    """A DENY decision with a reason accepts a payload whose reason_code is that exact string."""
    tenant = "reason-code-tenant"
    engagement = uuid.uuid4()
    proposal = proposal_row(tenant_id=tenant, engagement_id=engagement, proposal_id=uuid.uuid4())
    decision = decision_row(
        proposal,
        tenant_id=tenant,
        engagement_id=engagement,
        build_outcome="DENY",
        build_reason="ADMISSION_DENIED",
    )
    async with policy_admin_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
        )
        await conn.execute(
            text(
                "INSERT INTO clients (id, name, tenant_id) VALUES (:i, 'c', :t) "
                "ON CONFLICT DO NOTHING"
            ),
            {"i": uuid.uuid4(), "t": tenant},
        )
    async with policy_admin_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
        )
        client = (
            await conn.execute(text("SELECT id FROM clients WHERE tenant_id = :t"), {"t": tenant})
        ).scalar()
        await conn.execute(
            text("INSERT INTO engagements (id, client_id, tenant_id) VALUES (:i, :c, :t)"),
            {"i": engagement, "c": client, "t": tenant},
        )
    async with policy_admin_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
        )
        await insert_proposal(conn, proposal)
        await insert_decision(conn, decision)
    event = policy_event_row(proposal, decision)
    assert event["payload"]["reason_code"] == "ADMISSION_DENIED"
    await insert_event_as_recorder(policy_admin_engine, event, tenant=tenant)


# ── Timestamp canonicalization ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "microsecond",
    [0, 123456, 123000],
    ids=["zero-microsecond", "nonzero-microsecond", "trailing-zero-microsecond"],
)
async def test_canonical_decided_at_accepted(
    policy_admin_engine: AsyncEngine, microsecond: int
) -> None:
    """The trigger's rendering must equal datetime.isoformat() for each microsecond shape."""
    tenant = f"ts-tenant-{microsecond}"
    engagement = uuid.uuid4()
    decided = datetime(2026, 9, 3, 12, 30, 45, microsecond, tzinfo=UTC)
    proposal = proposal_row(tenant_id=tenant, engagement_id=engagement)
    decision = decision_row(
        proposal, tenant_id=tenant, engagement_id=engagement, decided_at=decided
    )
    async with policy_admin_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
        )
        await conn.execute(
            text("INSERT INTO clients (id, name, tenant_id) VALUES (:i, 'c', :t)"),
            {"i": uuid.uuid4(), "t": tenant},
        )
    async with policy_admin_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
        )
        client = (
            await conn.execute(text("SELECT id FROM clients WHERE tenant_id = :t"), {"t": tenant})
        ).scalar()
        await conn.execute(
            text("INSERT INTO engagements (id, client_id, tenant_id) VALUES (:i, :c, :t)"),
            {"i": engagement, "c": client, "t": tenant},
        )
        await insert_proposal(conn, proposal)
        await insert_decision(conn, decision)
    event = policy_event_row(proposal, decision)
    assert event["payload"]["decided_at"] == canonical_timestamp(decided)
    await insert_event_as_recorder(policy_admin_engine, event, tenant=tenant)


async def test_payload_decided_at_offset_text_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    """Same instant rendered as +01:00 differs textually from the canonical Z form."""
    decided = lineage_base["decision"]["decided_at"]
    offset_text = decided.astimezone(timezone(timedelta(hours=1))).isoformat()
    event = _payload_event(lineage_base, lambda p: p.__setitem__("decided_at", offset_text))
    await assert_recorder_insert_rejected(policy_admin_engine, event, match=_PAYLOAD_MATCH)


# ── Uniqueness substrate ─────────────────────────────────────────────────────


async def test_one_decision_per_proposal(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    second = decision_row(
        lineage_base["proposal"],
        tenant_id=LINEAGE_TENANT,
        engagement_id=lineage_base["engagement_id"],
    )
    second["decision_id"] = uuid.uuid4()
    second["decision_digest"] = "f" * 64
    async with policy_admin_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": LINEAGE_TENANT}
        )
        with pytest.raises(IntegrityError, match="uq_decision_records_proposal"):
            await insert_decision(conn, second)


async def test_one_event_per_decision(policy_admin_engine: AsyncEngine, lineage_base: dict) -> None:
    await insert_event_as_recorder(policy_admin_engine, lineage_base["event"])
    with pytest.raises((IntegrityError, ProgrammingError), match="ix_agent_events_policy_decision"):
        await insert_event_as_recorder(policy_admin_engine, lineage_base["event"], sequence=2)


async def test_concurrent_same_proposal_one_winner(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    """Two recorders racing the same proposal key: exactly one commits, deterministically."""
    url = policy_admin_engine.url
    barrier = asyncio.Barrier(2)
    outcomes: list[str] = []

    async def contender(label: str) -> None:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('blackbread.tenant_id', :t, true)"),
                    {"t": LINEAGE_TENANT},
                )
                proposal = proposal_row(
                    tenant_id=LINEAGE_TENANT,
                    engagement_id=lineage_base["engagement_id"],
                    idempotency_key="race-key",
                )
                proposal["proposal_digest"] = "a" * 64
                await barrier.wait()
                try:
                    await insert_proposal(conn, proposal)
                    outcomes.append(f"{label}:win")
                except IntegrityError:
                    outcomes.append(f"{label}:lose")
        finally:
            await engine.dispose()

    await asyncio.gather(contender("A"), contender("B"))
    assert sorted(o.split(":")[1] for o in outcomes) == ["lose", "win"]


# ── Recorder RLS (correction: GUC is a selector, not authenticated identity) ──


async def test_rls_missing_guc_hides_rows(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    async with policy_admin_engine.begin() as conn:
        await conn.execute(text("SET LOCAL ROLE blackbread_policy_recorder"))
        count = (await conn.execute(text("SELECT count(*) FROM action_proposals"))).scalar()
    assert count == 0


async def test_rls_mismatched_tenant_insert_rejected(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    async with policy_admin_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": "tenant-A"}
        )
        await conn.execute(text("SET LOCAL ROLE blackbread_policy_recorder"))
        proposal = proposal_row(tenant_id="tenant-B", engagement_id=lineage_base["engagement_id"])
        with pytest.raises((IntegrityError, ProgrammingError)):
            await insert_proposal(conn, proposal)


async def test_rls_guc_rebind_is_not_tenant_authentication(
    policy_admin_engine: AsyncEngine, lineage_base: dict
) -> None:
    """Rebinding the GUC changes which tenant the recorder sees: the GUC is a selector only."""
    async with policy_admin_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": LINEAGE_TENANT}
        )
        await conn.execute(text("SET LOCAL ROLE blackbread_policy_recorder"))
        seen = (await conn.execute(text("SELECT count(*) FROM action_proposals"))).scalar()
        assert seen >= 1
        await conn.execute(text("RESET ROLE"))
        await conn.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": "elsewhere"}
        )
        await conn.execute(text("SET LOCAL ROLE blackbread_policy_recorder"))
        other = (await conn.execute(text("SELECT count(*) FROM action_proposals"))).scalar()
        assert other == 0
