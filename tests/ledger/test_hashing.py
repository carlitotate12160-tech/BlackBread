import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

import pytest

from blackbread.ledger.errors import LedgerValidationError
from blackbread.ledger.hashing import (
    GENESIS_PREV_HASH,
    HASH_ALGORITHM,
    HASH_VERSION,
    canonical_json,
    canonical_timestamp,
    compute_event_hash,
    compute_payload_hash,
)


@dataclass(frozen=True)
class HashableEvent:
    id: uuid.UUID
    engagement_id: uuid.UUID
    tenant_id: str
    sequence: int
    schema_name: str
    schema_version: int
    producer: str
    correlation_id: uuid.UUID | None
    causation_id: uuid.UUID | None
    occurred_at: datetime
    recorded_at: datetime
    payload_hash: str
    prev_event_hash: str
    hash_algorithm: str
    hash_version: int
    sensitivity: str
    redaction_refs: list[str]


def _event(**changes: Any) -> HashableEvent:
    base = HashableEvent(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        engagement_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        tenant_id="tenant-a",
        sequence=1,
        schema_name="test.event",
        schema_version=1,
        producer="test-producer",
        correlation_id=None,
        causation_id=None,
        occurred_at=datetime(2026, 8, 28, 3, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 28, 3, 1, tzinfo=UTC),
        payload_hash=compute_payload_hash({"marker": "x"}),
        prev_event_hash=GENESIS_PREV_HASH,
        hash_algorithm=HASH_ALGORITHM,
        hash_version=HASH_VERSION,
        sensitivity="internal",
        redaction_refs=["artifact://redacted/1"],
    )
    return replace(base, **changes)


def test_canonical_timestamp_normalises_to_utc_z() -> None:
    value = datetime(2026, 8, 28, 3, 0, tzinfo=UTC)
    assert canonical_timestamp(value) == "2026-08-28T03:00:00Z"


def test_canonical_timestamp_rejects_naive_datetime() -> None:
    with pytest.raises(LedgerValidationError, match="timezone-aware"):
        canonical_timestamp(datetime(2026, 8, 28, 3, 0))


def test_canonical_json_is_key_order_independent() -> None:
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


@pytest.mark.parametrize(
    "value",
    [
        {"value": float("nan")},
        {"value": float("inf")},
        {1: "non-string-key"},
        {"value": ("tuple",)},
        {"value": "\x00"},
        {"value": 1e20},
        {"value": -0.0},
    ],
)
def test_canonical_json_rejects_non_json_values(value: object) -> None:
    with pytest.raises(LedgerValidationError):
        canonical_json(value)


def test_canonical_json_normalises_generic_mappings() -> None:
    value = MappingProxyType(
        {"nested": MappingProxyType({"marker": "x"}), "items": [MappingProxyType({"id": 1})]}
    )
    assert canonical_json(value) == '{"items":[{"id":1}],"nested":{"marker":"x"}}'


def test_payload_hash_is_stable_across_key_order() -> None:
    first = {"marker": "x", "nested": {"a": 1, "b": 2}}
    second = {"nested": {"b": 2, "a": 1}, "marker": "x"}
    assert compute_payload_hash(first) == compute_payload_hash(second)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sensitivity", "restricted"),
        ("redaction_refs", ["artifact://redacted/2"]),
        ("tenant_id", "tenant-b"),
        ("schema_version", 2),
    ],
)
def test_event_hash_binds_envelope_security_fields(field: str, value: object) -> None:
    original = _event()
    assert compute_event_hash(replace(original, **{field: value})) != compute_event_hash(original)


@pytest.mark.parametrize(
    ("field", "value"),
    [("hash_algorithm", "sha512"), ("hash_version", 2)],
)
def test_event_hash_rejects_unknown_hash_scheme(field: str, value: object) -> None:
    with pytest.raises(LedgerValidationError, match="unsupported"):
        compute_event_hash(replace(_event(), **{field: value}))
