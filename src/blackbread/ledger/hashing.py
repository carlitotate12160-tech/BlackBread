import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from blackbread.ledger.errors import LedgerValidationError

HASH_ALGORITHM = "sha256"
HASH_VERSION = 1
HASH_HEX_LENGTH = 64
GENESIS_PREV_HASH = "0" * HASH_HEX_LENGTH
MAX_JSON_DEPTH = 100


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
    redaction_refs: Sequence[str]


def canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LedgerValidationError("timestamps for hashing must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validate_json_string(value: str, path: str) -> str:
    if "\x00" in value:
        raise LedgerValidationError(f"{path} contains a NUL character unsupported by JSONB")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LedgerValidationError(f"{path} contains invalid Unicode") from exc
    return value


def _normalize_json_float(value: float, path: str) -> float:
    if not math.isfinite(value):
        raise LedgerValidationError(f"{path} contains a non-finite number")
    token = json.dumps(value, allow_nan=False)
    if "e" in token.lower() or token == "-0.0":
        raise LedgerValidationError(
            f"{path} contains a float that cannot round-trip through PostgreSQL JSONB"
        )
    return value


def _normalize_json_value(value: object, path: str = "$", depth: int = 0) -> object:
    if depth > MAX_JSON_DEPTH:
        raise LedgerValidationError(f"{path} exceeds the maximum JSON nesting depth")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _validate_json_string(value, path)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _normalize_json_float(value, path)
    if isinstance(value, list):
        return [
            _normalize_json_value(item, f"{path}[{index}]", depth + 1)
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise LedgerValidationError(f"{path} contains a non-string object key")
            normalized_key = _validate_json_string(key, path)
            normalized[normalized_key] = _normalize_json_value(
                item,
                f"{path}.{key}",
                depth + 1,
            )
        return normalized
    raise LedgerValidationError(f"{path} contains a non-JSON value")


def canonical_json(value: object) -> str:
    try:
        normalized = _normalize_json_value(value)
        return json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
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
