import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from blackbread.ledger.errors import LedgerValidationError
from blackbread.ledger.hashing import canonical_json, canonical_timestamp

ALLOWED_SENSITIVITIES = frozenset({"public", "internal", "confidential", "restricted"})
MAX_EVENT_PAYLOAD_BYTES = 1_048_576
MAX_REDACTION_REFS = 100


def _validate_text(value: str, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LedgerValidationError(f"{field} must be a non-blank string")
    if len(value) > maximum:
        raise LedgerValidationError(f"{field} exceeds {maximum} characters")


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

    def __post_init__(self) -> None:
        _validate_text(self.tenant_id, "tenant_id", 100)
        _validate_text(self.schema_name, "schema_name", 200)
        _validate_text(self.producer, "producer", 200)
        if not isinstance(self.engagement_id, uuid.UUID):
            raise LedgerValidationError("engagement_id must be a UUID")
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool):
            raise LedgerValidationError("schema_version must be an integer")
        if self.schema_version < 1:
            raise LedgerValidationError("schema_version must be positive")
        if not isinstance(self.occurred_at, datetime):
            raise LedgerValidationError("occurred_at must be a datetime")
        canonical_timestamp(self.occurred_at)
        if self.sensitivity not in ALLOWED_SENSITIVITIES:
            raise LedgerValidationError("unsupported sensitivity")
        for field, value in (
            ("correlation_id", self.correlation_id),
            ("causation_id", self.causation_id),
        ):
            if value is not None and not isinstance(value, uuid.UUID):
                raise LedgerValidationError(f"{field} must be a UUID or None")
        if not isinstance(self.payload, Mapping):
            raise LedgerValidationError("payload must be a mapping")
        payload_json = canonical_json(self.payload)
        if len(payload_json.encode("utf-8")) > MAX_EVENT_PAYLOAD_BYTES:
            raise LedgerValidationError("payload exceeds the event size limit")
        if isinstance(self.redaction_refs, (str, bytes)):
            raise LedgerValidationError("redaction_refs must be a sequence of opaque references")
        refs = tuple(self.redaction_refs)
        if len(refs) > MAX_REDACTION_REFS:
            raise LedgerValidationError("too many redaction references")
        for reference in refs:
            _validate_text(reference, "redaction reference", 500)
        object.__setattr__(self, "redaction_refs", refs)
