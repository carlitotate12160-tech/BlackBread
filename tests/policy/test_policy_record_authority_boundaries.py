"""M1.4c2b0 authority boundary proofs: runtime denial, non-wiring, and compatibility.

Each test proves one claim about what the inert substrate cannot do.
Run against real PostgreSQL 17.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from blackbread.ledger.hashing import (
    GENESIS_PREV_HASH,
    compute_event_hash,
    compute_payload_hash,
)
from tests.conftest import TEST_MIGRATION_DATABASE_URL

pytestmark = pytest.mark.anyio

TENANT = "boundary-test-tenant"


# ────────────────────────────────────────────────────────────────────
# §B — Direct runtime INSERT denial (uses blackbread_test_runtime)
# ────────────────────────────────────────────────────────────────────


async def test_runtime_proposal_insert_denied(session: AsyncSession) -> None:
    """blackbread_test_runtime INSERT into action_proposals fails."""
    await session.execute(text(f"SET LOCAL blackbread.tenant_id = '{TENANT}'"))
    engagement_id = uuid.uuid4()
    with pytest.raises(ProgrammingError, match="permission denied"):
        await session.execute(
            text(
                "INSERT INTO action_proposals (schema_name, schema_version, proposal_id, "
                "tenant_id, engagement_id, agent_instance_id, agent_role, capability_id, "
                "target_kind, target_value, input_schema_ref, parameters, intended_proof, "
                "precondition_refs, oracle_ref, risk, cost, information_gain, opsec_noise, "
                "target_requests, deadline_seconds, target_identity_tier, "
                "graph_state_root_version, graph_projector_version, graph_state_root, "
                "graph_ledger_event_count, graph_ledger_head_hash, "
                "idempotency_key, created_at, expires_at, proposal_digest) "
                "VALUES ('conductor.action_proposal', 1, :pid, :tid, :eid, :aid, "
                "'Scout', 'discovery.dns_enum.v1', 'root_domain', 'example.com', "
                "'DnsEnumInput.v1', '{}'::jsonb, 'test', '[]'::jsonb, 'test', "
                "0.1, 0.1, 0.5, 0.1, 1, 300, 'T0', 1, 1, :sr, 1, :lhh, "
                "'test-key', now(), now() + interval '1 hour', :pd)"
            ),
            {
                "pid": uuid.uuid4(),
                "tid": TENANT,
                "eid": engagement_id,
                "aid": uuid.uuid4(),
                "sr": "a" * 64,
                "lhh": "b" * 64,
                "pd": "c" * 64,
            },
        )
    await session.rollback()


async def test_runtime_decision_insert_denied(session: AsyncSession) -> None:
    """blackbread_test_runtime INSERT into decision_records fails."""
    await session.execute(text(f"SET LOCAL blackbread.tenant_id = '{TENANT}'"))
    with pytest.raises(ProgrammingError, match="permission denied"):
        await session.execute(
            text(
                "INSERT INTO decision_records (schema_name, schema_version, decision_id, "
                "tenant_id, engagement_id, proposal_id, proposal_digest, "
                "decision_authority, outcome, decided_at, "
                "graph_state_root_version, graph_projector_version, graph_state_root, "
                "graph_ledger_event_count, graph_ledger_head_hash, "
                "runtime_gate_result_digest, decision_digest, evaluation_request_digest) "
                "VALUES ('policy.decision', 2, :did, :tid, :eid, :pid, :pd, "
                "'policy.kernel.v2', 'ALLOW', now(), 1, 1, :sr, 1, :lhh, :rd, :dd, :erd)"
            ),
            {
                "did": uuid.uuid4(),
                "tid": TENANT,
                "eid": uuid.uuid4(),
                "pid": uuid.uuid4(),
                "pd": "a" * 64,
                "sr": "b" * 64,
                "lhh": "c" * 64,
                "rd": "d" * 64,
                "dd": "e" * 64,
                "erd": "f" * 64,
            },
        )
    await session.rollback()


async def test_runtime_reserved_event_insert_denied(session: AsyncSession) -> None:
    """blackbread_test_runtime INSERT of policy.decision.recorded into agent_events fails."""
    await session.execute(text(f"SET LOCAL blackbread.tenant_id = '{TENANT}'"))
    with pytest.raises((ProgrammingError, IntegrityError)):
        await session.execute(
            text(
                "INSERT INTO agent_events (id, engagement_id, tenant_id, sequence, "
                "schema_name, schema_version, producer, occurred_at, recorded_at, "
                "payload, payload_hash, prev_event_hash, event_hash, "
                "hash_algorithm, hash_version, sensitivity, redaction_refs) "
                "VALUES (:id, :eid, :tid, 1, 'policy.decision.recorded', 1, "
                "'policy-record-transaction.v1', now(), now(), "
                "'{}'::jsonb, :ph, :peh, :eh, 'sha256', 1, 'internal', '[]'::jsonb)"
            ),
            {
                "id": uuid.uuid4(),
                "eid": uuid.uuid4(),
                "tid": TENANT,
                "ph": "a" * 64,
                "peh": "b" * 64,
                "eh": "c" * 64,
            },
        )
    await session.rollback()


async def test_runtime_cannot_assume_recorder_role(session: AsyncSession) -> None:
    """blackbread_test_runtime cannot SET ROLE to the recorder."""
    with pytest.raises(ProgrammingError, match="permission denied"):
        await session.execute(text("SET ROLE blackbread_policy_recorder"))
    await session.rollback()


async def test_no_durable_row_after_denial(session: AsyncSession) -> None:
    """Admin confirms zero policy rows after denied runtime inserts."""

    admin_url = TEST_MIGRATION_DATABASE_URL
    admin = create_async_engine(admin_url)
    try:
        async with admin.begin() as conn:
            proposals = (
                await conn.execute(
                    text("SELECT count(*) FROM action_proposals WHERE tenant_id = :tid"),
                    {"tid": TENANT},
                )
            ).scalar()
            decisions = (
                await conn.execute(
                    text("SELECT count(*) FROM decision_records WHERE tenant_id = :tid"),
                    {"tid": TENANT},
                )
            ).scalar()
            events = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM agent_events "
                        "WHERE tenant_id = :tid AND schema_name = 'policy.decision.recorded'"
                    ),
                    {"tid": TENANT},
                )
            ).scalar()
            assert proposals == 0
            assert decisions == 0
            assert events == 0
    finally:
        await admin.dispose()


async def test_ordinary_non_policy_event_succeeds(session: AsyncSession) -> None:
    """Runtime INSERT of engagement.attested v1 into agent_events succeeds.

    This proves ordinary runtime event append remains compatible.
    """

    admin_url = TEST_MIGRATION_DATABASE_URL
    admin = create_async_engine(admin_url)
    compat_tenant = "compat-non-policy-tenant"
    engagement_id = uuid.uuid4()
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f"SET LOCAL blackbread.tenant_id = '{compat_tenant}'"))
            # Create a client and engagement for this test
            client_id = uuid.uuid4()
            await conn.execute(
                text("INSERT INTO clients (id, name, tenant_id) VALUES (:id, :n, :tid)"),
                {"id": client_id, "n": "compat-client", "tid": compat_tenant},
            )
            await conn.execute(
                text(
                    "INSERT INTO engagements (id, client_id, tenant_id, status) "
                    "VALUES (:id, :cid, :tid, 'created')"
                ),
                {"id": engagement_id, "cid": client_id, "tid": compat_tenant},
            )
    finally:
        await admin.dispose()

    # Now insert a normal event as the runtime role

    event_id = uuid.uuid4()
    now = datetime.now(UTC)
    payload = {"test": "data"}
    payload_hash = compute_payload_hash(payload)

    class _H:
        pass

    h = _H()
    h.id = event_id
    h.engagement_id = engagement_id
    h.tenant_id = compat_tenant
    h.sequence = 1
    h.schema_name = "engagement.attested"
    h.schema_version = 1
    h.producer = "test-runtime.v1"
    h.correlation_id = None
    h.causation_id = None
    h.occurred_at = now
    h.recorded_at = now
    h.payload = payload
    h.payload_hash = payload_hash
    h.prev_event_hash = GENESIS_PREV_HASH
    h.event_hash = ""
    h.hash_algorithm = "sha256"
    h.hash_version = 1
    h.sensitivity = "internal"
    h.redaction_refs = []
    event_hash = compute_event_hash(h)

    await session.execute(text(f"SET LOCAL blackbread.tenant_id = '{compat_tenant}'"))
    await session.execute(
        text(
            "INSERT INTO agent_events (id, engagement_id, tenant_id, sequence, "
            "schema_name, schema_version, producer, occurred_at, recorded_at, "
            "payload, payload_hash, prev_event_hash, event_hash, "
            "hash_algorithm, hash_version, sensitivity, redaction_refs) "
            "VALUES (:id, :eid, :tid, 1, 'engagement.attested', 1, "
            "'test-runtime.v1', :occ, :rec, CAST(:p AS jsonb), :ph, :peh, :eh, "
            "'sha256', 1, 'internal', '[]'::jsonb)"
        ),
        {
            "id": event_id,
            "eid": engagement_id,
            "tid": compat_tenant,
            "occ": now,
            "rec": now,
            "p": json.dumps(payload),
            "ph": payload_hash,
            "peh": GENESIS_PREV_HASH,
            "eh": event_hash,
        },
    )
    # Verify insert survived
    count = (
        await session.execute(
            text(
                "SELECT count(*) FROM agent_events "
                "WHERE tenant_id = :tid AND schema_name = 'engagement.attested'"
            ),
            {"tid": compat_tenant},
        )
    ).scalar()
    assert count == 1


# ────────────────────────────────────────────────────────────────────
# §I — Intentional non-wiring proofs (source scan)
# ────────────────────────────────────────────────────────────────────


def test_no_production_evaluation_facts_import() -> None:
    """No production module imports evaluation_facts for persistence."""
    src = pathlib.Path("src/blackbread")
    excluded = {"governance", "__pycache__"}
    for py in src.rglob("*.py"):
        if any(part in excluded for part in py.parts):
            continue
        if py.name == "evaluation_facts.py":
            continue
        content = py.read_text()
        assert "from blackbread.policy.evaluation_facts import" not in content, (
            f"production module {py} imports evaluation_facts"
        )


def test_no_production_set_role_recorder() -> None:
    """No production code contains SET ROLE blackbread_policy_recorder."""
    src = pathlib.Path("src/blackbread")
    for py in src.rglob("*.py"):
        content = py.read_text()
        assert "blackbread_policy_recorder" not in content, (
            f"production module {py} references recorder role"
        )


def test_no_production_append_policy_event() -> None:
    """No production code calls append_event for policy.decision.recorded."""
    src = pathlib.Path("src/blackbread")
    for py in src.rglob("*.py"):
        content = py.read_text()
        if "policy.decision.recorded" in content and py.name not in ("evaluation_facts.py",):
            assert "append_event" not in content, (
                f"production module {py} has both policy.decision.recorded and append_event"
            )


def test_no_production_lease_workorder_token() -> None:
    """No production code adds lease, WorkOrder, token, or capability activation fields."""
    src = pathlib.Path("src/blackbread")
    forbidden = ["WorkOrder", "execution_token", "capability_activation", "target_effect"]
    for py in src.rglob("*.py"):
        content = py.read_text()
        for term in forbidden:
            assert term not in content, f"production module {py} references {term}"
