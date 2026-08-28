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


def _validate_json_value(value: object, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LedgerValidationError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise LedgerValidationError(f"{path} contains a non-string object key")
            _validate_json_value(item, f"{path}.{key}")
        return
    raise LedgerValidationError(f"{path} contains a non-JSON value")


def canonical_json(value: object) -> str:
    _validate_json_value(value)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise LedgerValidationError("value cannot be canonicalized as JSON") from exc


def normalize_json_object(value: Mapping[str, object]) -> dict[str, object]:
    encoded = canonical_json(value)
    decoded: object = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise LedgerValidationError("event payload must be a JSON object")
    return cast(dict[str, object], decoded)


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
