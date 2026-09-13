"""M1.4c2b1b composed evaluate-and-record transaction proofs on real PostgreSQL 17.

``record_policy_decision`` composes evaluation, ledger materialization, and the recorder routine
into one atomic transaction: a new proposal commits the proposal/decision/event triple together, an
exact retry reconstructs the durable receipt without reevaluation, conflicts and durable-corruption
fail closed with zero writes, concurrent identical submissions converge to one triple and one
evaluator call, and the runtime login can neither invoke the routine nor persist a forged ALLOW.
No SQLite, no mocked routine/privilege/transaction/RLS, no sleeps (locking + asyncio.gather).
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from blackbread.conductor.contracts import TargetReference
from blackbread.ledger.verify import verify_chain
from blackbread.policy import recording
from blackbread.policy.recording import (
    PolicyRecordingConflictError,
    PolicyRecordingIntegrityError,
    PolicyRecordingUnavailableError,
    PolicyRecordReceipt,
    _require_exact_retry,
    record_policy_decision,
)
from blackbread.policy.recording_store import ProposalMatches, StoredProposal
from blackbread.tenancy import TenantContext
from tests.conductor._builders import make_proposal
from tests.conftest import TEST_DATABASE_URL, TEST_MIGRATION_DATABASE_URL
from tests.policy._policy_record_authority_support import open_recorder_txn
from tests.policy._policy_record_builders import (
    decision_event_row,
    decision_row,
    insert_agent_event,
    insert_decision,
    insert_proposal,
    proposal_row,
)
from tests.policy._runtime_builders import runtime_case
from tests.policy.conftest import seed_engagement

# The evaluator's fixtures are anchored at 12:05 on 2026-09-03; pinning the internally generated
# decision stamp to that instant yields a deterministic real ALLOW without a caller-supplied time.
# The runtime-gate builders also hardcode this tenant/engagement in their nested budget/lock/opsec
# snapshots, so a coherent RuntimeGateSnapshot requires the proposal to use the same identity.
DECIDED_AT = datetime(2026, 9, 3, 12, 5, 0, tzinfo=UTC)
TENANT = "tenant-a"
ENGAGEMENT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

_APPEND_ONLY = (
    ("agent_events", "agent_events_reject_mutation"),
    ("agent_events", "agent_events_reject_truncate"),
    ("action_proposals", "action_proposals_reject_mutation"),
    ("action_proposals", "action_proposals_reject_truncate"),
    ("decision_records", "decision_records_reject_mutation"),
    ("decision_records", "decision_records_reject_truncate"),
)


async def _truncate_policy_substrate(engine: AsyncEngine) -> None:
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
    """Admin (superuser) engine that may EXECUTE the routine, a factory over it, and the seeded
    tenant/engagement. The admin connection proves transaction composition, not a caller."""

    engine: AsyncEngine
    factory: async_sessionmaker[AsyncSession]
    tenant: str
    engagement_id: uuid.UUID


@pytest_asyncio.fixture
async def admin_engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_MIGRATION_DATABASE_URL, pool_pre_ping=True)
    try:
        await _truncate_policy_substrate(engine)
        yield engine
    finally:
        # Empty the substrate on teardown too, so the session's ``downgrade base`` is not blocked by
        # 0009's refusal-with-records guard when this module runs on its own.
        await _truncate_policy_substrate(engine)
        await engine.dispose()


@pytest_asyncio.fixture
async def bench(admin_engine: AsyncEngine) -> Bench:
    await seed_engagement(admin_engine, TENANT, ENGAGEMENT_ID)
    factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    return Bench(admin_engine, factory, TENANT, ENGAGEMENT_ID)


@pytest_asyncio.fixture
async def runtime_engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


def _allow_inputs(**overrides: Any) -> dict[str, Any]:
    """Coherent snapshots for a real ALLOW under the seeded tenant/engagement at ``DECIDED_AT``."""
    proposal = make_proposal(tenant_id=TENANT, engagement_id=ENGAGEMENT_ID, **overrides)
    case = runtime_case(proposal=proposal, evaluated_at=DECIDED_AT)
    return {"proposal": proposal, **{k: case[k] for k in _SNAPSHOTS}}


_SNAPSHOTS = ("policy", "identity", "capability", "manifest", "runtime")


async def _call(
    factory: Callable[[], AsyncSession], inputs: dict[str, Any], tenant: str
) -> PolicyRecordReceipt:
    return await record_policy_decision(
        factory,
        inputs["proposal"],
        tenant=TenantContext(tenant),
        **{k: inputs[k] for k in _SNAPSHOTS},
    )


async def _submit(bench: Bench, inputs: dict[str, Any]) -> PolicyRecordReceipt:
    return await _call(bench.factory, inputs, bench.tenant)


async def _counts(engine: AsyncEngine, proposal_id: uuid.UUID) -> tuple[int, int, int]:
    async with engine.connect() as conn:
        proposals = await conn.scalar(
            text("SELECT count(*) FROM action_proposals WHERE proposal_id = :p"), {"p": proposal_id}
        )
        decisions = await conn.scalar(
            text("SELECT count(*) FROM decision_records WHERE proposal_id = :p"), {"p": proposal_id}
        )
        events = await conn.scalar(
            text("SELECT count(*) FROM agent_events WHERE correlation_id = :p"), {"p": proposal_id}
        )
    return int(proposals or 0), int(decisions or 0), int(events or 0)


async def _seed_committed(bench: Bench, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(recording, "_utcnow", lambda: DECIDED_AT)
    inputs = _allow_inputs()
    await _submit(bench, inputs)
    return inputs["proposal"]


# A. New proposal: evaluate once, commit the triple together, receipt matches rows, chain verifies.
async def test_new_proposal_commits_triple_once(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = recording.evaluate_persistence_facts

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(recording, "_utcnow", lambda: DECIDED_AT)
    monkeypatch.setattr(recording, "evaluate_persistence_facts", spy)
    inputs = _allow_inputs()
    proposal = inputs["proposal"]

    receipt = await _submit(bench, inputs)

    assert calls == [1]
    assert receipt.replayed is False
    assert receipt.decision.outcome == "ALLOW"
    assert await _counts(bench.engine, proposal.proposal_id) == (1, 1, 1)

    async with bench.factory() as session:
        await session.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": bench.tenant}
        )
        digest = await session.scalar(
            text("SELECT decision_digest FROM decision_records WHERE proposal_id = :p"),
            {"p": proposal.proposal_id},
        )
        result = await session.execute(
            text("SELECT id, sequence, event_hash FROM agent_events WHERE correlation_id = :p"),
            {"p": proposal.proposal_id},
        )
        event = result.mappings().one()
    assert digest == receipt.decision.decision_digest
    assert (event["id"], event["sequence"], event["event_hash"]) == (
        receipt.event_id,
        receipt.event_sequence,
        receipt.event_hash,
    )
    verification = await verify_chain(
        bench.engine, tenant_id=bench.tenant, engagement_id=bench.engagement_id
    )
    assert verification.ok
    assert verification.verified_event_count == 1


# B. Exact retry: same identity reconstructs the durable receipt with zero evaluator calls.
async def test_exact_retry_reconstructs_without_reevaluation(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recording, "_utcnow", lambda: DECIDED_AT)
    inputs = _allow_inputs()
    first = await _submit(bench, inputs)

    calls: list[int] = []
    monkeypatch.setattr(recording, "evaluate_persistence_facts", lambda *a, **k: calls.append(1))
    replay = await _submit(bench, inputs)

    assert calls == []
    assert replay.replayed is True
    assert replay.decision == first.decision
    assert (replay.event_id, replay.event_sequence, replay.event_hash) == (
        first.event_id,
        first.event_sequence,
        first.event_hash,
    )
    assert await _counts(bench.engine, inputs["proposal"].proposal_id) == (1, 1, 1)


# C. Conflicts: each rejects with zero additional writes.
async def test_same_id_different_digest_conflicts(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = await _seed_committed(bench, monkeypatch)
    clash = _allow_inputs(
        proposal_id=stored.proposal_id,
        idempotency_key=stored.idempotency_key,
        target=TargetReference(target_kind="root_domain", canonical_value="divergent.example"),
    )
    assert clash["proposal"].proposal_digest != stored.proposal_digest
    with pytest.raises(PolicyRecordingConflictError):
        await _submit(bench, clash)
    assert await _counts(bench.engine, stored.proposal_id) == (1, 1, 1)


async def test_same_key_different_proposal_conflicts(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = await _seed_committed(bench, monkeypatch)
    clash = _allow_inputs(proposal_id=uuid.uuid4(), idempotency_key=stored.idempotency_key)
    with pytest.raises(PolicyRecordingConflictError):
        await _submit(bench, clash)
    assert await _counts(bench.engine, clash["proposal"].proposal_id) == (0, 0, 0)
    assert await _counts(bench.engine, stored.proposal_id) == (1, 1, 1)


def _stored(proposal_id: uuid.UUID, key: str, digest: str) -> StoredProposal:
    return StoredProposal(proposal_id, key, digest, TENANT, ENGAGEMENT_ID)


def test_same_digest_or_divergent_identity_reject_before_any_write() -> None:
    # The digest binds proposal_id and a UNIQUE(tenant, engagement, digest) constraint makes a real
    # "same digest, different id" row unreachable, so this pins the classifier that rejects every
    # partial or divergent match: it raises before the boundary opens any transaction (zero writes).
    p = make_proposal(tenant_id=TENANT, engagement_id=ENGAGEMENT_ID)
    mine = _stored(p.proposal_id, p.idempotency_key, p.proposal_digest)
    other = _stored(uuid.uuid4(), "idem-other", "d" * 64)
    drift = _stored(p.proposal_id, "idem-drift", p.proposal_digest)
    divergent = [
        ProposalMatches(by_id=None, by_key=None, by_digest=other),  # digest hits a different id
        ProposalMatches(by_id=mine, by_key=other, by_digest=mine),  # three rows disagree
        ProposalMatches(by_id=mine, by_key=None, by_digest=None),  # partial match
        ProposalMatches(by_id=drift, by_key=drift, by_digest=drift),  # stored key differs
    ]
    for matches in divergent:
        with pytest.raises(PolicyRecordingConflictError):
            _require_exact_retry(matches, p)


async def test_cross_tenant_substitution_fails_closed(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = await _seed_committed(bench, monkeypatch)
    inputs = _allow_inputs(proposal_id=stored.proposal_id)
    # A tenant context that does not match the proposal tenant is rejected before any lookup/write.
    with pytest.raises(PolicyRecordingIntegrityError):
        await _call(bench.factory, inputs, "tenant-other")


async def test_missing_engagement_is_unavailable(
    admin_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # admin_engine truncates the substrate but this test never seeds the engagement, so the
    # tenant-qualified lock finds no row and the boundary fails closed before any write.
    monkeypatch.setattr(recording, "_utcnow", lambda: DECIDED_AT)
    factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    inputs = _allow_inputs()
    with pytest.raises(PolicyRecordingUnavailableError):
        await _call(factory, inputs, TENANT)
    assert await _counts(admin_engine, inputs["proposal"].proposal_id) == (0, 0, 0)


# D. Durable corruption: fail closed on an inconsistent durable triple.
async def test_retry_fails_closed_on_corrupt_decision_digest(bench: Bench) -> None:
    proposal = make_proposal(tenant_id=TENANT, engagement_id=ENGAGEMENT_ID)
    prow = proposal_row(proposal=proposal)
    drow = decision_row(prow, outcome="ALLOW")
    drow["decision_digest"] = "0" * 64  # a digest that cannot bind the reconstructed columns
    # Seed a complete triple as the reserved recorder identity (the only author allowed to write the
    # reserved policy event), leaving a durable but digest-inconsistent decision.
    async with bench.factory() as session:
        conn = await session.connection()
        await open_recorder_txn(conn, bench.tenant)
        await insert_proposal(conn, prow)
        await insert_decision(conn, drow)
        await insert_agent_event(conn, decision_event_row(prow, drow))
        await session.commit()
    inputs = {**_allow_inputs(), "proposal": proposal}
    with pytest.raises(PolicyRecordingIntegrityError):
        await _submit(bench, inputs)


async def test_retry_fails_closed_on_missing_event(bench: Bench) -> None:
    proposal = make_proposal(tenant_id=TENANT, engagement_id=ENGAGEMENT_ID)
    prow = proposal_row(proposal=proposal)
    # A committed proposal+decision with no policy event is an incomplete durable triple.
    async with bench.factory() as session:
        conn = await session.connection()
        await session.execute(
            text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": bench.tenant}
        )
        await insert_proposal(conn, prow)
        await insert_decision(conn, decision_row(prow, outcome="ALLOW"))
        await session.commit()
    inputs = {**_allow_inputs(), "proposal": proposal}
    with pytest.raises(PolicyRecordingIntegrityError):
        await _submit(bench, inputs)


# E. Rollback and cancellation: forced failures persist zero rows.
@pytest.mark.parametrize(
    ("attr", "boom"),
    [
        ("evaluate_persistence_facts", RuntimeError("before evaluation")),
        ("invoke_record_routine", RuntimeError("inside routine after evaluation")),
        ("invoke_record_routine", asyncio.CancelledError()),
    ],
    ids=["before-evaluation", "inside-routine", "cancelled-before-commit"],
)
async def test_forced_failure_persists_nothing(
    bench: Bench, monkeypatch: pytest.MonkeyPatch, attr: str, boom: BaseException
) -> None:
    monkeypatch.setattr(recording, "_utcnow", lambda: DECIDED_AT)
    inputs = _allow_inputs()

    async def _araise(*_a: Any, **_k: Any) -> Any:
        raise boom

    def _raise(*_a: Any, **_k: Any) -> Any:
        raise boom

    monkeypatch.setattr(recording, attr, _araise if attr == "invoke_record_routine" else _raise)
    with pytest.raises(type(boom)):
        await _submit(bench, inputs)
    assert await _counts(bench.engine, inputs["proposal"].proposal_id) == (0, 0, 0)


# F. Concurrency: deterministic lock convergence, no sleeps.
async def test_concurrent_identical_submissions_converge(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recording, "_utcnow", lambda: DECIDED_AT)
    calls: list[int] = []
    real = recording.evaluate_persistence_facts

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(recording, "evaluate_persistence_facts", counting)
    inputs = _allow_inputs()

    async def submit() -> PolicyRecordReceipt:
        # Distinct engines guarantee two separate sessions racing on the engagement row lock.
        engine = create_async_engine(TEST_MIGRATION_DATABASE_URL, pool_pre_ping=True)
        try:
            return await _call(async_sessionmaker(engine, expire_on_commit=False), inputs, TENANT)
        finally:
            await engine.dispose()

    results = await asyncio.gather(submit(), submit())

    assert sorted(r.replayed for r in results) == [False, True]
    assert calls == [1]
    assert await _counts(bench.engine, inputs["proposal"].proposal_id) == (1, 1, 1)
    assert results[0].decision == results[1].decision


async def test_conflicting_concurrent_submission_fails_closed(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = await _seed_committed(bench, monkeypatch)
    clash = _allow_inputs(proposal_id=uuid.uuid4(), idempotency_key=stored.idempotency_key)
    with pytest.raises(PolicyRecordingConflictError):
        await _submit(bench, clash)
    assert await _counts(bench.engine, clash["proposal"].proposal_id) == (0, 0, 0)


# G. Forged ALLOW: the runtime login cannot persist a coherent, digest-valid forged triple.
async def test_runtime_login_cannot_forge_allow(bench: Bench, runtime_engine: AsyncEngine) -> None:
    proposal = make_proposal(tenant_id=bench.tenant, engagement_id=bench.engagement_id)
    prow = proposal_row(proposal=proposal)
    # decision_row builds through the real PolicyDecisionV2 contract, so this ALLOW triple is fully
    # coherent and digest-valid; the forgery is authority, not content.
    drow = decision_row(prow, build_outcome="ALLOW", build_reason=None)

    # 1. Direct raw routine invocation as the runtime login fails on privilege.
    with pytest.raises(DBAPIError) as routine_exc:
        async with runtime_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": bench.tenant}
            )
            await conn.execute(
                text("SELECT public.blackbread_record_policy_decision(NULL, NULL, NULL)")
            )
    assert "permission denied" in str(routine_exc.value.orig).lower()

    # 2. Direct record-table writes as the runtime login fail.
    async with runtime_engine.connect() as conn:
        for insert, row in ((insert_proposal, prow), (insert_decision, drow)):
            trans = await conn.begin()
            await conn.execute(
                text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": bench.tenant}
            )
            with pytest.raises(DBAPIError) as write_exc:
                await insert(conn, row)
            assert "permission denied" in str(write_exc.value.orig).lower()
            await trans.rollback()

    # 3. The composed boundary using the runtime session cannot persist either.
    runtime_factory = async_sessionmaker(runtime_engine, expire_on_commit=False)
    inputs = _allow_inputs()
    with pytest.raises(DBAPIError):
        await _call(runtime_factory, inputs, bench.tenant)

    # All three relevant row counts remain zero for both proposal identities.
    assert await _counts(bench.engine, prow["proposal_id"]) == (0, 0, 0)
    assert await _counts(bench.engine, inputs["proposal"].proposal_id) == (0, 0, 0)


# I. Public API shape: no decision/result/event/stamp/digest/execution seam, no **kwargs injection.
def test_public_signature_admits_no_decision_or_execution_seam() -> None:
    signature = inspect.signature(record_policy_decision)
    expected = (
        "recorder_session_factory proposal tenant policy identity capability manifest runtime"
    )
    assert set(signature.parameters) == set(expected.split())
    forbidden = (
        "PolicyDecisionV2 AdmissionResult RuntimeGateResult EvaluationPersistenceFacts "
        "PolicyDecisionRecord EventDraft AgentEvent decision_id decided_at outcome reason "
        "digest producer lease WorkOrder token"
    )
    for parameter in signature.parameters.values():
        assert parameter.kind not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)
        annotation = str(parameter.annotation)
        assert not any(term in annotation for term in forbidden.split()), annotation


def test_receipt_is_not_an_execution_credential() -> None:
    fields = set(PolicyRecordReceipt.__dataclass_fields__)
    assert fields == {"decision", "event_id", "event_sequence", "event_hash", "replayed"}
    for banned in ("lease", "work_order", "token", "capability", "activation", "target_effect"):
        assert banned not in fields
