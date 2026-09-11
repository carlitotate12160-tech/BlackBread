"""M1.4c2b0b known-answer proof that the derived lineage column does not touch the v1 event hash.

Adding ``agent_events.policy_decision_id`` (derived from the already hash-covered ``causation_id``)
must leave the sealed v1 payload and event preimage/hash vectors byte-identical. These are pure
in-process checks over the ledger hashing module and need no database.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from blackbread.ledger.event import AgentEvent
from blackbread.ledger.hashing import (
    _event_preimage,
    compute_event_hash,
    compute_payload_hash,
)

# The independently-verified golden payload/hash for a policy.decision.recorded v1 event, identical
# to the vector asserted in tests/policy/test_policy_decision_recorded_event.py.
GOLDEN_PAYLOAD = {
    "decided_at": "2026-09-03T12:05:00Z",
    "decision_authority": "policy.kernel.v2",
    "decision_digest": "e" * 64,
    "decision_id": "44444444-4444-4444-4444-444444444444",
    "decision_schema_name": "policy.decision",
    "decision_schema_version": 2,
    "graph_version": {
        "ledger_event_count": 7,
        "ledger_head_hash": "b" * 64,
        "projector_version": 1,
        "state_root": "a" * 64,
        "state_root_version": 2,
    },
    "idempotency_key": "idem-0001",
    "outcome": "ALLOW",
    "proposal_digest": "c" * 64,
    "proposal_id": "11111111-1111-1111-1111-111111111111",
    "reason_code": None,
    "runtime_gate_result_digest": "d" * 64,
}
GOLDEN_PAYLOAD_HASH = "24340c3fb5fc3e944b2b3160613d7d56689833d5ed5507c81877e78343f1f5fa"
# Independently recomputed from the sealed v1 preimage in ``_sealed_event`` below; pins the event
# preimage/hash vector against drift and proves the lineage column stays out of the v1 hash.
EVENT_HASH_KNOWN_ANSWER = "449cfdc77545a96a295570c9bc730e31460dd05f9d2c2b34f730cfcaf786fdb7"

_PREIMAGE_KEYS = frozenset(
    {
        "event_id",
        "engagement_id",
        "tenant_id",
        "sequence",
        "schema_name",
        "schema_version",
        "producer",
        "correlation_id",
        "causation_id",
        "occurred_at",
        "recorded_at",
        "payload_hash",
        "prev_event_hash",
        "hash_algorithm",
        "hash_version",
        "sensitivity",
        "redaction_refs",
    }
)


def _sealed_event(policy_decision_id: uuid.UUID | None) -> AgentEvent:
    return AgentEvent(
        id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
        engagement_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        tenant_id="tenant-a",
        sequence=8,
        schema_name="policy.decision.recorded",
        schema_version=1,
        producer="policy-record-transaction.v1",
        correlation_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        causation_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
        occurred_at=datetime(2026, 9, 3, 12, 5, tzinfo=UTC),
        recorded_at=datetime(2026, 9, 3, 12, 5, tzinfo=UTC),
        payload_hash=GOLDEN_PAYLOAD_HASH,
        prev_event_hash="0" * 64,
        event_hash="ignored",
        hash_algorithm="sha256",
        hash_version=1,
        sensitivity="internal",
        redaction_refs=[],
        policy_decision_id=policy_decision_id,
    )


def test_golden_payload_hash_is_unchanged() -> None:
    assert compute_payload_hash(GOLDEN_PAYLOAD) == GOLDEN_PAYLOAD_HASH
    # A round-trip through JSON (as the ledger stores it) preserves the vector.
    assert compute_payload_hash(json.loads(json.dumps(GOLDEN_PAYLOAD))) == GOLDEN_PAYLOAD_HASH


def test_event_preimage_does_not_include_policy_decision_id() -> None:
    preimage = _event_preimage(_sealed_event(uuid.uuid4()))
    assert set(preimage) == _PREIMAGE_KEYS
    assert "policy_decision_id" not in preimage
    # causation already carries the decision identity the lineage column is derived from.
    assert preimage["causation_id"] == "44444444-4444-4444-4444-444444444444"


def test_event_hash_is_invariant_to_the_lineage_column() -> None:
    with_lineage = compute_event_hash(
        _sealed_event(uuid.UUID("44444444-4444-4444-4444-444444444444"))
    )
    without_lineage = compute_event_hash(_sealed_event(None))
    assert with_lineage == without_lineage


def test_event_hash_known_answer_is_stable() -> None:
    assert compute_event_hash(_sealed_event(None)) == EVENT_HASH_KNOWN_ANSWER
