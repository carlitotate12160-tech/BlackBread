"""M1.4c2b1b replay event-integrity regression on real PostgreSQL 17 (PR90-EVENT-REPLAY-001).

An exact retry reconstructs the durable decision *and* must re-verify the complete durable policy
event: append-time triggers do not re-run on replay, so a privileged corruption of the persisted
row (altered payload, stale/forged payload or event hash, broken predecessor) must fail closed with
`PolicyRecordingIntegrityError` instead of returning a receipt. Verification is event-local: an
unrelated later-chain corruption must not reject an otherwise-valid policy receipt, and no replay
path reevaluates. No SQLite, no mocked database/hash verifier, no sleeps; deliberate corruption is
seeded only via the administrative trigger-disable pattern with guaranteed re-enable.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from blackbread.ledger.event import AgentEvent
from blackbread.ledger.hashing import GENESIS_PREV_HASH, compute_event_hash, compute_payload_hash
from blackbread.policy import recording
from blackbread.policy.recording import (
    PolicyRecordingIntegrityError,
    PolicyRecordReceipt,
    record_policy_decision,
)
from blackbread.policy.recording_store import POLICY_EVENT_SCHEMA
from blackbread.tenancy import TenantContext
from tests.conductor._builders import make_proposal
from tests.conftest import TEST_MIGRATION_DATABASE_URL
from tests.policy._runtime_builders import runtime_case
from tests.policy.conftest import seed_engagement, seed_ledger_event

DECIDED_AT = datetime(2026, 9, 3, 12, 5, 0, tzinfo=UTC)
TENANT = "tenant-a"
ENGAGEMENT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
MUTATION_TRIGGER = "agent_events_reject_mutation"

_APPEND_ONLY = (
    ("agent_events", "agent_events_reject_mutation"),
    ("agent_events", "agent_events_reject_truncate"),
    ("action_proposals", "action_proposals_reject_mutation"),
    ("action_proposals", "action_proposals_reject_truncate"),
    ("decision_records", "decision_records_reject_mutation"),
    ("decision_records", "decision_records_reject_truncate"),
)


async def _truncate(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table, trigger in _APPEND_ONLY:
            await conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))
        await conn.execute(
            text(
                "TRUNCATE decision_records, action_proposals, "
                "graph_projection_snapshots, agent_events, engagements, clients CASCADE"
            )
        )
        for table, trigger in _APPEND_ONLY:
            await conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}"))


@dataclass(frozen=True)
class Bench:
    engine: AsyncEngine
    factory: async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture
async def admin_engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_MIGRATION_DATABASE_URL, pool_pre_ping=True)
    try:
        await _truncate(engine)
        yield engine
    finally:
        await _truncate(engine)
        await engine.dispose()


@pytest_asyncio.fixture
async def bench(admin_engine: AsyncEngine) -> Bench:
    await seed_engagement(admin_engine, TENANT, ENGAGEMENT_ID)
    return Bench(admin_engine, async_sessionmaker(admin_engine, expire_on_commit=False))


def _inputs(**overrides: Any) -> dict[str, Any]:
    proposal = make_proposal(tenant_id=TENANT, engagement_id=ENGAGEMENT_ID, **overrides)
    case = runtime_case(proposal=proposal, evaluated_at=DECIDED_AT)
    keys = ("policy", "identity", "capability", "manifest", "runtime")
    return {"proposal": proposal, **{k: case[k] for k in keys}}


async def _submit(bench: Bench, inputs: dict[str, Any]) -> PolicyRecordReceipt:
    return await record_policy_decision(
        bench.factory,
        inputs["proposal"],
        tenant=TenantContext(TENANT),
        policy=inputs["policy"],
        identity=inputs["identity"],
        capability=inputs["capability"],
        manifest=inputs["manifest"],
        runtime=inputs["runtime"],
    )


async def _record_valid(
    bench: Bench, monkeypatch: pytest.MonkeyPatch, **overrides: Any
) -> PolicyRecordReceipt:
    monkeypatch.setattr(recording, "_utcnow", lambda: DECIDED_AT)
    return await _submit(bench, _inputs(**overrides))


def _block_reeval(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Install a spy so any reevaluation during replay is detected; returns the call log."""
    calls: list[int] = []

    def spy(*_a: Any, **_k: Any) -> Any:
        calls.append(1)
        raise AssertionError("replay must not reevaluate")

    monkeypatch.setattr(recording, "evaluate_persistence_facts", spy)
    return calls


async def _load_policy_event(engine: AsyncEngine, decision_id: uuid.UUID) -> AgentEvent:
    async with engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text("SELECT * FROM agent_events WHERE schema_name = :s AND causation_id = :c"),
                    {"s": POLICY_EVENT_SCHEMA, "c": decision_id},
                )
            )
            .mappings()
            .one()
        )
    return AgentEvent(**dict(row))


async def _corrupt_event(decision_id: uuid.UUID, sets: dict[str, Any]) -> None:
    """Mutate the durable policy event with the mutation-reject trigger disabled, then restored."""
    engine = create_async_engine(TEST_MIGRATION_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"ALTER TABLE agent_events DISABLE TRIGGER {MUTATION_TRIGGER}"))
            try:
                assignments = ", ".join(
                    f"payload = CAST(:{k} AS jsonb)" if k == "payload" else f"{k} = :{k}"
                    for k in sets
                )
                params = {k: (json.dumps(v) if k == "payload" else v) for k, v in sets.items()}
                await conn.execute(
                    text(
                        f"UPDATE agent_events SET {assignments} "  # noqa: S608 -- keys are literals
                        "WHERE schema_name = :s AND causation_id = :c"
                    ),
                    {**params, "s": POLICY_EVENT_SCHEMA, "c": decision_id},
                )
            finally:
                await conn.execute(
                    text(f"ALTER TABLE agent_events ENABLE TRIGGER {MUTATION_TRIGGER}")
                )
    finally:
        await engine.dispose()


async def test_valid_replay_returns_original_receipt(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await _record_valid(bench, monkeypatch)
    _block_reeval(monkeypatch)
    replay = await _submit(bench, _inputs())
    assert replay.replayed is True
    assert replay.decision == first.decision
    assert (replay.event_id, replay.event_sequence, replay.event_hash) == (
        first.event_id,
        first.event_sequence,
        first.event_hash,
    )


async def test_replay_rejects_semantic_payload_tamper(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = await _record_valid(bench, monkeypatch)
    event = await _load_policy_event(bench.engine, receipt.decision.decision_id)
    # A payload that no longer represents the durable decision, with self-consistent hashes.
    tampered = {**event.payload, "outcome": "DENY", "reason_code": "ENGAGEMENT_STOPPED"}
    payload_hash = compute_payload_hash(tampered)
    event.payload, event.payload_hash = tampered, payload_hash
    calls = _block_reeval(monkeypatch)
    await _corrupt_event(
        receipt.decision.decision_id,
        {
            "payload": tampered,
            "payload_hash": payload_hash,
            "event_hash": compute_event_hash(event),
        },
    )
    with pytest.raises(PolicyRecordingIntegrityError):
        await _submit(bench, _inputs())
    assert calls == []


@pytest.mark.parametrize("column", ["payload_hash", "event_hash"])
async def test_replay_rejects_corrupt_hash(
    bench: Bench, monkeypatch: pytest.MonkeyPatch, column: str
) -> None:
    receipt = await _record_valid(bench, monkeypatch)
    calls = _block_reeval(monkeypatch)
    await _corrupt_event(receipt.decision.decision_id, {column: "f" * 64})
    with pytest.raises(PolicyRecordingIntegrityError):
        await _submit(bench, _inputs())
    assert calls == []


async def test_replay_rejects_broken_predecessor(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = await _record_valid(bench, monkeypatch)
    event = await _load_policy_event(bench.engine, receipt.decision.decision_id)
    # A genesis policy event whose prev-hash is moved off GENESIS, with the event hash recomputed to
    # stay self-consistent; only the predecessor check can catch it.
    event.prev_event_hash = "a" * 64
    calls = _block_reeval(monkeypatch)
    await _corrupt_event(
        receipt.decision.decision_id,
        {"prev_event_hash": "a" * 64, "event_hash": compute_event_hash(event)},
    )
    with pytest.raises(PolicyRecordingIntegrityError):
        await _submit(bench, _inputs())
    assert calls == []


async def test_replay_valid_with_intact_predecessor(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seed an unrelated genesis event so the policy event lands at sequence 2 with a predecessor.
    await seed_ledger_event(bench.engine, TENANT, ENGAGEMENT_ID)
    first = await _record_valid(bench, monkeypatch)
    assert first.event_sequence == 2
    event = await _load_policy_event(bench.engine, first.decision.decision_id)
    assert event.prev_event_hash != GENESIS_PREV_HASH
    _block_reeval(monkeypatch)
    replay = await _submit(bench, _inputs())
    assert replay.replayed is True
    assert replay.event_hash == first.event_hash


async def test_replay_ignores_unrelated_later_corruption(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await _record_valid(bench, monkeypatch)
    other = await _record_valid(
        bench, monkeypatch, proposal_id=uuid.uuid4(), idempotency_key="idem-2"
    )
    assert other.event_sequence == first.event_sequence + 1
    # Corrupt the later unrelated event; the earlier receipt must still replay (event-local).
    await _corrupt_event(other.decision.decision_id, {"event_hash": "f" * 64})
    _block_reeval(monkeypatch)
    replay = await _submit(bench, _inputs())
    assert replay.replayed is True
    assert replay.decision == first.decision
