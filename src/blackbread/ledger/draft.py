import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import cast

from blackbread.ledger.errors import LedgerValidationError
from blackbread.ledger.hashing import canonical_json, canonical_timestamp

ALLOWED_SENSITIVITIES = frozenset({"public", "internal", "confidential", "restricted"})
MAX_EVENT_PAYLOAD_BYTES = 1_048_576
MAX_REDACTION_REFS = 100
MAX_SCHEMA_VERSION = 2_147_483_647


def _validate_text(value: str, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LedgerValidationError(f"{field} must be a non-blank string")
    if len(value) > maximum:
        raise LedgerValidationError(f"{field} exceeds {maximum} characters")
    if "\x00" in value:
        raise LedgerValidationError(f"{field} contains a NUL character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LedgerValidationError(f"{field} contains invalid Unicode") from exc


def _validate_optional_uuid(value: object, field: str) -> None:
    if value is not None and not isinstance(value, uuid.UUID):
        raise LedgerValidationError(f"{field} must be a UUID or None")


def _validate_schema_version(value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise LedgerValidationError("schema_version must be an integer")
    if value < 1:
        raise LedgerValidationError("schema_version must be positive")
    if value > MAX_SCHEMA_VERSION:
        raise LedgerValidationError("schema_version exceeds the PostgreSQL INTEGER range")


def _snapshot_payload(payload: object) -> tuple[Mapping[str, object], str]:
    if not isinstance(payload, Mapping):
        raise LedgerValidationError("payload must be a mapping")
    payload_json = canonical_json(payload, max_bytes=MAX_EVENT_PAYLOAD_BYTES)
    decoded: object = json.loads(payload_json)
    if not isinstance(decoded, dict):
        raise LedgerValidationError("payload must be a JSON object")
    normalized = cast(dict[str, object], decoded)
    return MappingProxyType(normalized), payload_json


def _validate_redaction_refs(redaction_refs: object) -> tuple[str, ...]:
    if isinstance(redaction_refs, (str, bytes)) or not isinstance(redaction_refs, Sequence):
        raise LedgerValidationError("redaction_refs must be a sequence of opaque references")
    refs = tuple(redaction_refs)
    if len(refs) > MAX_REDACTION_REFS:
        raise LedgerValidationError("too many redaction references")
    for reference in refs:
        _validate_text(reference, "redaction reference", 500)
    return refs


@dataclass(frozen=True, kw_only=True, slots=True)
class EventDraft:
    tenant_id: str
    engagement_id: uuid.UUID
    schema_name: str
    schema_version: int
    producer: str
    payload: Mapping[str, object]
    occurred_at: datetime
    sensitivity: str = "internal"
    correlation_id: uuid.UUID | None = None
    causation_id: uuid.UUID | None = None
    redaction_refs: Sequence[str] = ()
    _canonical_payload: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_text(self.tenant_id, "tenant_id", 100)
        _validate_text(self.schema_name, "schema_name", 200)
        _validate_text(self.producer, "producer", 200)
        if not isinstance(self.engagement_id, uuid.UUID):
            raise LedgerValidationError("engagement_id must be a UUID")
        _validate_schema_version(self.schema_version)
        if not isinstance(self.occurred_at, datetime):
            raise LedgerValidationError("occurred_at must be a datetime")
        canonical_timestamp(self.occurred_at)
        if not isinstance(self.sensitivity, str) or self.sensitivity not in ALLOWED_SENSITIVITIES:
            raise LedgerValidationError("unsupported sensitivity")
        _validate_optional_uuid(self.correlation_id, "correlation_id")
        _validate_optional_uuid(self.causation_id, "causation_id")
        payload, payload_json = _snapshot_payload(self.payload)
        refs = _validate_redaction_refs(self.redaction_refs)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "_canonical_payload", payload_json)
        object.__setattr__(self, "redaction_refs", refs)

    def materialize_payload(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self._canonical_payload))
