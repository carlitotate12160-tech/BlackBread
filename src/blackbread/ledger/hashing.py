import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from blackbread.ledger.errors import LedgerValidationError

HASH_ALGORITHM = "sha256"
HASH_VERSION = 1
HASH_HEX_LENGTH = 64
GENESIS_PREV_HASH = "0" * HASH_HEX_LENGTH
MAX_JSON_DEPTH = 100

_NUL_CODEPOINT = 0
_UNICODE_SURROGATE_LOW = 0xD800
_UNICODE_SURROGATE_HIGH = 0xDFFF
_ASCII_CONTROL_BOUNDARY = 0x20
_ASCII_MAX = 0x7F
_TWO_BYTE_UTF_MAX = 0x7FF
_THREE_BYTE_UTF_MAX = 0xFFFF
_JSON_ESCAPE_CHARS = frozenset({'"', "\\", "\b", "\f", "\n", "\r", "\t"})


class _JsonBudget:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.consumed = 0

    def consume(self, size: int) -> None:
        self.consumed += size
        if self.consumed > self.maximum:
            raise LedgerValidationError("value exceeds the canonical JSON size limit")


class SealedEvent(Protocol):
    id: UUID
    engagement_id: UUID
    tenant_id: str
    sequence: int
    schema_name: str
    schema_version: int
    producer: str
    correlation_id: UUID | None
    causation_id: UUID | None
    occurred_at: datetime
    recorded_at: datetime
    payload_hash: str
    prev_event_hash: str
    hash_algorithm: str
    hash_version: int
    sensitivity: str
    redaction_refs: list[str]


def canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LedgerValidationError("timestamps for hashing must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _check_char_validity(codepoint: int, path: str) -> None:
    if codepoint == _NUL_CODEPOINT:
        raise LedgerValidationError(f"{path} contains a NUL character unsupported by JSONB")
    if _UNICODE_SURROGATE_LOW <= codepoint <= _UNICODE_SURROGATE_HIGH:
        raise LedgerValidationError(f"{path} contains invalid Unicode")


def _consume_char_budget(
    character: str,
    codepoint: int,
    budget: _JsonBudget,
) -> None:
    if character in _JSON_ESCAPE_CHARS:
        budget.consume(2)
    elif codepoint < _ASCII_CONTROL_BOUNDARY:
        budget.consume(6)
    elif codepoint <= _ASCII_MAX:
        budget.consume(1)
    elif codepoint <= _TWO_BYTE_UTF_MAX:
        budget.consume(2)
    elif codepoint <= _THREE_BYTE_UTF_MAX:
        budget.consume(3)
    else:
        budget.consume(4)


def _validate_json_string(
    value: str,
    path: str,
    budget: _JsonBudget | None = None,
) -> str:
    if budget is not None:
        budget.consume(2)
    for character in value:
        codepoint = ord(character)
        _check_char_validity(codepoint, path)
        if budget is not None:
            _consume_char_budget(character, codepoint, budget)
    return value


def _normalize_json_float(
    value: float,
    path: str,
    budget: _JsonBudget | None,
) -> float:
    if not math.isfinite(value):
        raise LedgerValidationError(f"{path} contains a non-finite number")
    encoded_float = json.dumps(value, allow_nan=False)
    is_negative_zero = value == 0.0 and math.copysign(1.0, value) < 0
    if "e" in encoded_float.lower() or is_negative_zero:
        raise LedgerValidationError(
            f"{path} contains a float that cannot round-trip through PostgreSQL JSONB"
        )
    if budget is not None:
        budget.consume(len(encoded_float))
    return value


def _normalize_scalar(
    value: object,
    path: str,
    budget: _JsonBudget | None,
) -> object | None:
    if value is None:
        if budget is not None:
            budget.consume(4)
        return value
    if isinstance(value, bool):
        if budget is not None:
            budget.consume(4 if value else 5)
        return value
    if isinstance(value, str):
        return _validate_json_string(value, path, budget)
    if isinstance(value, int):
        if budget is not None:
            budget.consume(len(str(value)))
        return value
    if isinstance(value, float):
        return _normalize_json_float(value, path, budget)
    return _SENTINEL


_SENTINEL = object()


def _normalize_list(
    value: list[object],
    path: str,
    depth: int,
    budget: _JsonBudget | None,
) -> list[object]:
    if budget is not None:
        budget.consume(2)
    normalized_items: list[object] = []
    for index, item in enumerate(value):
        if budget is not None and index:
            budget.consume(1)
        normalized_items.append(
            _normalize_json_value(item, f"{path}[{index}]", depth + 1, budget)
        )
    return normalized_items


def _normalize_mapping(
    value: Mapping[str, object],
    path: str,
    depth: int,
    budget: _JsonBudget | None,
) -> dict[str, object]:
    if budget is not None:
        budget.consume(2)
    normalized: dict[str, object] = {}
    for index, (key, item) in enumerate(value.items()):
        if not isinstance(key, str):
            raise LedgerValidationError(f"{path} contains a non-string object key")
        if budget is not None and index:
            budget.consume(1)
        normalized_key = _validate_json_string(key, path, budget)
        if budget is not None:
            budget.consume(1)
        normalized[normalized_key] = _normalize_json_value(
            item, f"{path}.<value>", depth + 1, budget
        )
    return normalized


def _normalize_json_value(
    value: object,
    path: str = "$",
    depth: int = 0,
    budget: _JsonBudget | None = None,
) -> object:
    if depth > MAX_JSON_DEPTH:
        raise LedgerValidationError(f"{path} exceeds the maximum JSON nesting depth")
    scalar = _normalize_scalar(value, path, budget)
    if scalar is not _SENTINEL:
        return scalar
    if isinstance(value, list):
        return _normalize_list(value, path, depth, budget)
    if isinstance(value, Mapping):
        return _normalize_mapping(value, path, depth, budget)
    raise LedgerValidationError(f"{path} contains a non-JSON value")


def canonical_json(value: object, *, max_bytes: int | None = None) -> str:
    try:
        budget = _JsonBudget(max_bytes) if max_bytes is not None else None
        normalized = _normalize_json_value(value, budget=budget)
        encoded = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if max_bytes is not None and len(encoded.encode("utf-8")) > max_bytes:
            raise LedgerValidationError("value exceeds the canonical JSON size limit")
        return encoded
    except LedgerValidationError:
        raise
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise LedgerValidationError("value cannot be canonicalized as JSON") from exc


def normalize_json_object(value: Mapping[str, object]) -> dict[str, object]:
    normalized = _normalize_json_value(value)
    if not isinstance(normalized, dict):
        raise LedgerValidationError("event payload must be a JSON object")
    return cast(dict[str, object], normalized)


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def compute_payload_hash(payload: Mapping[str, object]) -> str:
    return sha256_hex(canonical_json(payload))


def _event_preimage(event: SealedEvent) -> dict[str, object]:
    return {
        "event_id": str(event.id),
        "engagement_id": str(event.engagement_id),
        "tenant_id": event.tenant_id,
        "sequence": event.sequence,
        "schema_name": event.schema_name,
        "schema_version": event.schema_version,
        "producer": event.producer,
        "correlation_id": str(event.correlation_id) if event.correlation_id is not None else None,
        "causation_id": str(event.causation_id) if event.causation_id is not None else None,
        "occurred_at": canonical_timestamp(event.occurred_at),
        "recorded_at": canonical_timestamp(event.recorded_at),
        "payload_hash": event.payload_hash,
        "prev_event_hash": event.prev_event_hash,
        "hash_algorithm": event.hash_algorithm,
        "hash_version": event.hash_version,
        "sensitivity": event.sensitivity,
        "redaction_refs": list(event.redaction_refs),
    }


def compute_event_hash(event: SealedEvent) -> str:
    if event.hash_algorithm != HASH_ALGORITHM or event.hash_version != HASH_VERSION:
        raise LedgerValidationError("unsupported event hash scheme")
    return sha256_hex(canonical_json(_event_preimage(event)))
