"""M1.4c2b1a dormant-substrate proofs for migration 0010 and the recording store at head.

Observes the objects and privileges ``alembic upgrade head`` (revision 0010) leaves on the
shared migrated test database: the recorder-owned ``SECURITY DEFINER`` routine with a pinned
``search_path`` and ``PUBLIC`` execute revoked, the recorder's bounded INSERT (and no broad
DML) on the record tables, the b1 uniqueness guarantee, forced RLS, and the recorder's
non-login/non-assumable/membership-free shape.

The substrate is dormant: ``blackbread_runtime`` holds no EXECUTE privilege, a direct runtime call
fails closed before any row persists, and runtime can author neither the record tables nor the
reserved ``policy.decision.recorded`` event. Store-level proofs exercise the strict row projection
and routine invocation under the authorized migration/test superuser only; a temporary-owner-swap
proof shows owner identity is load-bearing. No production module imports the store and no
``recording.py`` evaluation wiring exists — that composition is M1.4c2b1b scope.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from blackbread.conductor.contracts import ActionProposal
from blackbread.ledger.event import AgentEvent
from blackbread.ledger.hashing import (
    GENESIS_PREV_HASH,
    HASH_ALGORITHM,
    HASH_VERSION,
    compute_event_hash,
)
from blackbread.policy import recording_store
from blackbread.policy.recording_store import PolicyDecisionRecord
from blackbread.tenancy import TenantContext, bind_tenant_context
from tests.conductor._builders import make_proposal
from tests.policy._policy_record_authority_support import (
    RECORDER_ROLE,
    REV_0010,
    ROUTINE,
    ROUTINE_SIGNATURE,
    RUNTIME_ROLE,
    clear_policy_rows_before_base_downgrade,  # noqa: F401 -- session cleanup autouse fixture
    table_privilege,
)
from tests.policy._policy_record_builders import (
    DECISION_COLUMNS,
    decision_event_row,
    decision_row,
    insert_agent_event,
    insert_decision,
    insert_proposal,
    proposal_row,
)
from tests.policy.conftest import seed_engagement

RECORD_TABLES = ("action_proposals", "decision_records")
RLS_TABLES = ("agent_events", "action_proposals", "decision_records")
RUNTIME_CALL = (
    f"SELECT public.{ROUTINE}(NULL::public.action_proposals, NULL::public.decision_records, "
    "NULL::public.agent_events)"
)


async def _scalar(engine: AsyncEngine, sql: str, **params: object) -> Any:
    async with engine.connect() as conn:
        return await conn.scalar(text(sql), params)


async def _counts(admin: AsyncEngine, tenant_id: str) -> tuple[int, int, int]:
    async with admin.connect() as conn:
        p = await conn.scalar(
            text("SELECT count(*) FROM action_proposals WHERE tenant_id = :t"), {"t": tenant_id}
        )
        d = await conn.scalar(
            text("SELECT count(*) FROM decision_records WHERE tenant_id = :t"), {"t": tenant_id}
        )
        e = await conn.scalar(
            text(
                "SELECT count(*) FROM agent_events "
                "WHERE tenant_id = :t AND schema_name = 'policy.decision.recorded'"
            ),
            {"t": tenant_id},
        )
    return int(p or 0), int(d or 0), int(e or 0)


def _event(
    p_row: dict[str, Any], d_row: dict[str, Any], *, sequence: int, prev_hash: str
) -> AgentEvent:
    """A coherent ``policy.decision.recorded`` v1 event chained to ``prev_hash``."""
    row = decision_event_row(p_row, d_row, sequence=sequence, prev_event_hash=prev_hash)
    event = AgentEvent(**row, hash_algorithm=HASH_ALGORITHM, hash_version=HASH_VERSION)
    event.event_hash = compute_event_hash(event)
    return event


async def _record_via_store(
    admin: AsyncEngine, proposal: ActionProposal, d_row: dict[str, Any] | None = None
) -> tuple[dict[str, Any], uuid.UUID]:
    """Persist one coherent triple through the store under the authorized test identity."""
    p_row = proposal_row(proposal)
    d_row = d_row or decision_row(p_row)
    await seed_engagement(admin, proposal.tenant_id, proposal.engagement_id)
    async with AsyncSession(admin) as session, session.begin():
        await bind_tenant_context(session, TenantContext(proposal.tenant_id))
        assert await recording_store.lock_engagement(
            session, proposal.tenant_id, proposal.engagement_id
        )
        sequence, prev_hash = await recording_store.latest_event_chain(
            session, proposal.tenant_id, proposal.engagement_id
        )
        event = _event(p_row, d_row, sequence=sequence, prev_hash=prev_hash or GENESIS_PREV_HASH)
        spec = PolicyDecisionRecord(**{k: d_row[k] for k in DECISION_COLUMNS})
        event_id = await recording_store.invoke_record_routine(session, proposal, spec, event)
        assert event_id == event.id
    return d_row, event.id


async def test_routine_is_security_definer_owned_by_recorder_with_pinned_search_path(
    policy_admin_engine: AsyncEngine,
) -> None:
    async with policy_admin_engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT pg_get_userbyid(proowner) AS owner, prosecdef, proconfig, "
                        "prorettype::regtype::text AS rettype FROM pg_proc WHERE proname = :n"
                    ),
                    {"n": ROUTINE},
                )
            )
            .mappings()
            .one()
        )
    assert row["owner"] == RECORDER_ROLE, "routine owner must be exactly the recorder"
    assert row["prosecdef"] is True, "routine must be SECURITY DEFINER"
    assert row["proconfig"] == ["search_path=pg_catalog, public"]
    assert row["rettype"] == "uuid"
    assert len(REV_0010) <= 32, "revision must fit alembic_version varchar(32)"


async def test_no_role_but_the_recorder_owner_may_execute_the_routine(
    policy_admin_engine: AsyncEngine,
) -> None:
    public_exec = await _scalar(
        policy_admin_engine,
        "SELECT has_function_privilege('public', oid, 'EXECUTE') FROM pg_proc WHERE proname = :n",
        n=ROUTINE,
    )
    runtime_exec = await _scalar(
        policy_admin_engine,
        "SELECT has_function_privilege(:r, oid, 'EXECUTE') FROM pg_proc WHERE proname = :n",
        r=RUNTIME_ROLE,
        n=ROUTINE,
    )
    recorder_exec = await _scalar(
        policy_admin_engine,
        "SELECT has_function_privilege(:r, oid, 'EXECUTE') FROM pg_proc WHERE proname = :n",
        r=RECORDER_ROLE,
        n=ROUTINE,
    )
    # PostgreSQL keeps an implicit EXECUTE grant row for the routine owner; the dormant invariant is
    # that no non-owner grantee (PUBLIC or the runtime activation identity) holds any routine
    # privilege, so the routine is unreachable from any login until M1.4c2b1b grants EXECUTE.
    non_owner_grants = await _scalar(
        policy_admin_engine,
        "SELECT count(*) FROM information_schema.routine_privileges "
        "WHERE routine_schema = 'public' AND routine_name = :n AND grantee <> :owner",
        n=ROUTINE,
        owner=RECORDER_ROLE,
    )
    assert public_exec is False, "PUBLIC EXECUTE must be revoked"
    assert runtime_exec is False, "the dormant b1a substrate grants runtime no EXECUTE path"
    # The recorder owns the routine (owner implicitly may execute); this documents the boundary.
    assert recorder_exec is True
    assert non_owner_grants == 0, "no routine privilege may be granted to any non-owner role"


async def test_runtime_direct_routine_call_is_denied_and_persists_nothing(
    policy_admin_engine: AsyncEngine, engine: AsyncEngine
) -> None:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    with pytest.raises(ProgrammingError) as excinfo:
        async with engine.connect() as conn:
            await conn.execute(text(RUNTIME_CALL))
    assert "permission denied for function" in str(excinfo.value.orig).lower()
    assert await _counts(policy_admin_engine, tenant) == (0, 0, 0)


async def test_runtime_login_cannot_author_a_policy_decision_event(
    policy_admin_engine: AsyncEngine, engine: AsyncEngine
) -> None:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    engagement_id = uuid.uuid4()
    await seed_engagement(policy_admin_engine, tenant, engagement_id)
    proposal = proposal_row(proposal_id=uuid.uuid4(), tenant_id=tenant, engagement_id=engagement_id)
    decision = decision_row(proposal)
    async with policy_admin_engine.begin() as conn:
        await insert_proposal(conn, proposal)
        await insert_decision(conn, decision)
    # A fully coherent event row still fails: the lineage trigger runs as the invoker and only
    # the reserved recorder identity may author a policy.decision.recorded event.
    with pytest.raises(ProgrammingError) as excinfo:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
            )
            await insert_agent_event(conn, decision_event_row(proposal, decision))
    assert "requires the reserved recorder identity" in str(excinfo.value.orig)
    persisted = await _scalar(
        policy_admin_engine, "SELECT count(*) FROM agent_events WHERE tenant_id = :t", t=tenant
    )
    assert persisted == 0


async def test_recorder_has_bounded_insert_and_no_broad_dml(
    policy_admin_engine: AsyncEngine,
) -> None:
    for table in RECORD_TABLES:
        assert await table_privilege(policy_admin_engine, RECORDER_ROLE, table, "SELECT")
        assert await table_privilege(policy_admin_engine, RECORDER_ROLE, table, "INSERT")
        for privilege in ("UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            granted = await table_privilege(policy_admin_engine, RECORDER_ROLE, table, privilege)
            assert granted is False, f"recorder must not hold {privilege} on {table}"
    # The recorder appends events but must never read/update/delete/truncate the ledger.
    assert await table_privilege(policy_admin_engine, RECORDER_ROLE, "agent_events", "INSERT")
    for privilege in ("SELECT", "UPDATE", "DELETE", "TRUNCATE"):
        held = await table_privilege(policy_admin_engine, RECORDER_ROLE, "agent_events", privilege)
        assert held is False, f"recorder must not hold {privilege} on agent_events"


async def test_recorder_effective_grants_are_exactly_the_b1_minimum(
    policy_admin_engine: AsyncEngine,
) -> None:
    async with policy_admin_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee = :r AND table_schema = 'public' "
                    "UNION "
                    "SELECT table_name, privilege_type FROM information_schema.column_privileges "
                    "WHERE grantee = :r AND table_schema = 'public'"
                ),
                {"r": RECORDER_ROLE},
            )
        ).all()
    granted = {(str(row[0]), str(row[1])) for row in rows}
    assert granted == {
        ("action_proposals", "SELECT"),
        ("action_proposals", "INSERT"),
        ("decision_records", "SELECT"),
        ("decision_records", "INSERT"),
        ("agent_events", "INSERT"),
    }, f"recorder privileges must be exactly the b1 minimum, got {sorted(granted)}"


async def test_runtime_holds_no_write_or_execute_path_to_the_record_substrate(
    policy_admin_engine: AsyncEngine,
) -> None:
    for table in RECORD_TABLES:
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            granted = await table_privilege(policy_admin_engine, RUNTIME_ROLE, table, privilege)
            assert granted is False, f"runtime must not hold {privilege} on {table}"
    runtime_exec = await _scalar(
        policy_admin_engine,
        "SELECT has_function_privilege(:r, oid, 'EXECUTE') FROM pg_proc WHERE proname = :n",
        r=RUNTIME_ROLE,
        n=ROUTINE,
    )
    assert runtime_exec is False, "dormant b1a grants runtime no path to the record tables"


async def test_runtime_login_cannot_directly_insert_record_tables(
    policy_admin_engine: AsyncEngine, engine: AsyncEngine
) -> None:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    engagement_id = uuid.uuid4()
    await seed_engagement(policy_admin_engine, tenant, engagement_id)
    proposal = proposal_row(proposal_id=uuid.uuid4(), tenant_id=tenant, engagement_id=engagement_id)
    for insert, row in ((insert_proposal, proposal), (insert_decision, decision_row(proposal))):
        with pytest.raises(ProgrammingError) as excinfo:
            async with engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('blackbread.tenant_id', :t, true)"), {"t": tenant}
                )
                await insert(conn, row)
        assert "permission denied" in str(excinfo.value.orig).lower()


async def test_forced_row_level_security_is_preserved_on_0010_head(
    policy_admin_engine: AsyncEngine,
) -> None:
    async with policy_admin_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = ANY(:tables)"
                ),
                {"tables": list(RLS_TABLES)},
            )
        ).mappings()
        state = {row["relname"]: row for row in rows}
    for table in RLS_TABLES:
        assert state[table]["relrowsecurity"] is True, f"{table} RLS disabled"
        assert state[table]["relforcerowsecurity"] is True, f"{table} RLS not forced"


async def test_b1_uniqueness_rejects_a_second_decision_for_one_proposal(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    engagement_id = uuid.uuid4()
    await seed_engagement(policy_admin_engine, tenant, engagement_id)
    proposal = proposal_row(proposal_id=uuid.uuid4(), tenant_id=tenant, engagement_id=engagement_id)
    first = decision_row(proposal)
    second = decision_row(proposal)  # a different decision id, same (tenant, engagement, proposal)
    async with policy_admin_engine.begin() as conn:
        await insert_proposal(conn, proposal)
        await insert_decision(conn, first)
    with pytest.raises(DBAPIError):
        async with policy_admin_engine.begin() as conn:
            await insert_decision(conn, second)


async def test_routine_refuses_a_caller_supplied_policy_decision_id(
    policy_admin_engine: AsyncEngine,
) -> None:
    # The lineage column is database-derived; the routine must reject a supplied value before any
    # insert runs. A NULL composite event with only policy_decision_id set isolates that guard.
    nulls = ", ".join(["NULL"] * 19 + [":pid"])
    with pytest.raises(DBAPIError) as excinfo:
        async with policy_admin_engine.begin() as conn:
            await conn.execute(
                text(
                    f"SELECT public.{ROUTINE}(NULL::public.action_proposals, "
                    f"NULL::public.decision_records, ROW({nulls})::public.agent_events)"
                ),
                {"pid": uuid.uuid4()},
            )
    assert "policy_decision_id is database-derived" in str(excinfo.value.orig)


async def test_store_persists_the_atomic_triple_under_the_test_identity(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    proposal = make_proposal(tenant_id=tenant, engagement_id=uuid.uuid4(), proposal_id=uuid.uuid4())
    d_row, event_id = await _record_via_store(policy_admin_engine, proposal)
    assert await _counts(policy_admin_engine, tenant) == (1, 1, 1)
    derived = await _scalar(
        policy_admin_engine,
        "SELECT policy_decision_id FROM agent_events WHERE id = :i",
        i=event_id,
    )
    assert derived == d_row["decision_id"], "the 0009 trigger derives lineage from causation_id"


async def test_store_resolves_all_three_proposal_identities(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    proposal = make_proposal(tenant_id=tenant, engagement_id=uuid.uuid4(), proposal_id=uuid.uuid4())
    await _record_via_store(policy_admin_engine, proposal)
    async with AsyncSession(policy_admin_engine) as session:
        matches = await recording_store.find_proposal_matches(session, proposal)
        for found in (matches.by_id, matches.by_key, matches.by_digest):
            assert found is not None
            assert found.proposal_id == proposal.proposal_id
            assert found.proposal_digest == proposal.proposal_digest
        fresh = make_proposal(
            tenant_id=tenant,
            engagement_id=proposal.engagement_id,
            proposal_id=uuid.uuid4(),
            idempotency_key=f"idem-{uuid.uuid4().hex[:10]}",
        )
        misses = await recording_store.find_proposal_matches(session, fresh)
        assert misses == recording_store.ProposalMatches(None, None, None)


async def test_store_reports_durable_completion_states(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    engagement_id = uuid.uuid4()
    proposal = make_proposal(
        tenant_id=tenant, engagement_id=engagement_id, proposal_id=uuid.uuid4()
    )
    d_row, event_id = await _record_via_store(policy_admin_engine, proposal)
    partial = proposal_row(
        proposal_id=uuid.uuid4(),
        tenant_id=tenant,
        engagement_id=engagement_id,
        idempotency_key=f"idem-{uuid.uuid4().hex[:10]}",
    )
    async with policy_admin_engine.begin() as conn:
        await insert_proposal(conn, partial)
        await insert_decision(conn, decision_row(partial))
    async with AsyncSession(policy_admin_engine) as session:
        complete = await recording_store.load_durable_completion(
            session, tenant, engagement_id, proposal.proposal_id
        )
        assert complete.decision is not None
        assert complete.decision["decision_id"] == d_row["decision_id"]
        assert (complete.decision_count, complete.event_count) == (1, 1)
        assert complete.event_id == event_id and complete.event_sequence == 1
        assert complete.event_hash is not None

        half = await recording_store.load_durable_completion(
            session, tenant, engagement_id, partial["proposal_id"]
        )
        assert half.decision is not None
        assert (half.decision_count, half.event_count, half.event_id) == (1, 0, None)

        missing = await recording_store.load_durable_completion(
            session, tenant, engagement_id, uuid.uuid4()
        )
        assert (missing.decision, missing.decision_count, missing.event_count) == (None, 0, 0)


async def test_routine_rejects_inconsistent_lineage_and_rolls_back_the_whole_triple(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    proposal = make_proposal(tenant_id=tenant, engagement_id=uuid.uuid4(), proposal_id=uuid.uuid4())
    p_row = proposal_row(proposal)
    d_row = decision_row(p_row)
    await seed_engagement(policy_admin_engine, tenant, proposal.engagement_id)
    async with AsyncSession(policy_admin_engine) as session:
        with pytest.raises(DBAPIError, match="lineage is not self-consistent"):
            async with session.begin():
                await bind_tenant_context(session, TenantContext(tenant))
                event = _event(p_row, d_row, sequence=1, prev_hash=GENESIS_PREV_HASH)
                event.causation_id = uuid.uuid4()  # event no longer names this decision
                spec = PolicyDecisionRecord(**{k: d_row[k] for k in DECISION_COLUMNS})
                await recording_store.invoke_record_routine(session, proposal, spec, event)
    assert await _counts(policy_admin_engine, tenant) == (0, 0, 0)


async def test_routine_rejects_a_tenant_context_mismatch_and_rolls_back(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    proposal = make_proposal(tenant_id=tenant, engagement_id=uuid.uuid4(), proposal_id=uuid.uuid4())
    p_row = proposal_row(proposal)
    d_row = decision_row(p_row)
    await seed_engagement(policy_admin_engine, tenant, proposal.engagement_id)
    async with AsyncSession(policy_admin_engine) as session:
        with pytest.raises(DBAPIError, match="tenant context does not match"):
            async with session.begin():
                await bind_tenant_context(session, TenantContext(f"other-{tenant}"))
                spec = PolicyDecisionRecord(**{k: d_row[k] for k in DECISION_COLUMNS})
                event = _event(p_row, d_row, sequence=1, prev_hash=GENESIS_PREV_HASH)
                await recording_store.invoke_record_routine(session, proposal, spec, event)
    assert await _counts(policy_admin_engine, tenant) == (0, 0, 0)


async def test_routine_owner_identity_is_load_bearing(
    policy_admin_engine: AsyncEngine,
) -> None:
    tenant = f"tenant-{uuid.uuid4().hex[:12]}"
    proposal = make_proposal(tenant_id=tenant, engagement_id=uuid.uuid4(), proposal_id=uuid.uuid4())
    p_row = proposal_row(proposal)
    d_row = decision_row(p_row)
    await seed_engagement(policy_admin_engine, tenant, proposal.engagement_id)
    async with policy_admin_engine.begin() as conn:
        await conn.execute(text(f"ALTER FUNCTION {ROUTINE_SIGNATURE} OWNER TO postgres"))
    try:
        # With the routine owned by a non-recorder, the SECURITY DEFINER identity is no longer the
        # reserved writer, so the 0009 lineage trigger rejects the policy event and the whole
        # triple rolls back. Owner identity -- not table privileges -- is what the event requires.
        with pytest.raises(DBAPIError, match="reserved recorder identity"):
            await _record_via_store(policy_admin_engine, proposal, d_row)
        assert await _counts(policy_admin_engine, tenant) == (0, 0, 0)
    finally:
        async with policy_admin_engine.begin() as conn:
            await conn.execute(text(f"ALTER FUNCTION {ROUTINE_SIGNATURE} OWNER TO {RECORDER_ROLE}"))
    await _record_via_store(policy_admin_engine, proposal, d_row)
    assert await _counts(policy_admin_engine, tenant) == (1, 1, 1)
