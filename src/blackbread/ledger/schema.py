import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from blackbread.ledger.draft import MAX_EVENT_PAYLOAD_BYTES, EventDraft
from blackbread.ledger.errors import LedgerValidationError
from blackbread.ledger.hashing import canonical_json

_SCHEMA_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_MAX_SCHEMA_NAME_LENGTH = 200


class UnknownEventSchemaError(LedgerValidationError):
    """Raised when an event schema is not explicitly registered."""


class EventPayload(BaseModel):
    """Strict, immutable payload base for a versioned ledger event schema."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    SCHEMA_NAME: ClassVar[str]
    SCHEMA_VERSION: ClassVar[int]

    def to_ledger_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")


def _schema_key(schema_name: object, schema_version: object) -> tuple[str, int]:
    if (
        not isinstance(schema_name, str)
        or len(schema_name) > _MAX_SCHEMA_NAME_LENGTH
        or _SCHEMA_NAME_PATTERN.fullmatch(schema_name) is None
    ):
        raise LedgerValidationError("event schema name is not canonical")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 1
    ):
        raise LedgerValidationError("event schema version must be a positive integer")
    return schema_name, schema_version


class EventRegistry:
    """Allowlist of exact payload classes keyed by canonical name and version."""

    def __init__(self) -> None:
        self._schemas: dict[tuple[str, int], type[EventPayload]] = {}
        self._frozen = False

    @property
    def registered_keys(self) -> frozenset[tuple[str, int]]:
        return frozenset(self._schemas)

    def register(self, model: type[EventPayload]) -> None:
        if self._frozen:
            raise LedgerValidationError("event registry is frozen")
        if not isinstance(model, type) or not issubclass(model, EventPayload):
            raise LedgerValidationError("registered event schema must inherit EventPayload")
        key = _schema_key(
            getattr(model, "SCHEMA_NAME", None),
            getattr(model, "SCHEMA_VERSION", None),
        )
        if key in self._schemas:
            raise LedgerValidationError(f"event schema {key[0]} v{key[1]} is already registered")
        self._schemas[key] = model

    def freeze(self) -> Self:
        self._frozen = True
        return self

    def resolve(self, schema_name: str, schema_version: int) -> type[EventPayload]:
        key = _schema_key(schema_name, schema_version)
        try:
            return self._schemas[key]
        except KeyError:
            raise UnknownEventSchemaError(
                f"unknown event schema {schema_name} v{schema_version}"
            ) from None

    def parse(
        self,
        schema_name: str,
        schema_version: int,
        payload: Mapping[str, object],
    ) -> EventPayload:
        if not isinstance(payload, Mapping):
            raise LedgerValidationError("event payload must be a mapping")
        model = self.resolve(schema_name, schema_version)
        try:
            payload_json = canonical_json(payload, max_bytes=MAX_EVENT_PAYLOAD_BYTES)
            return model.model_validate_json(payload_json, strict=True)
        except ValidationError as exc:
            raise LedgerValidationError(
                f"payload does not conform to {schema_name} v{schema_version}"
            ) from exc


@dataclass(frozen=True, kw_only=True, slots=True)
class EventEnvelope:
    tenant_id: str
    engagement_id: UUID
    producer: str
    occurred_at: datetime
    sensitivity: str = "internal"
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    redaction_refs: tuple[str, ...] = ()


def to_draft(
    payload: EventPayload,
    envelope: EventEnvelope,
    *,
    registry: EventRegistry,
) -> EventDraft:
    if not isinstance(payload, EventPayload):
        raise LedgerValidationError("typed event payload must inherit EventPayload")
    schema_name = type(payload).SCHEMA_NAME
    schema_version = type(payload).SCHEMA_VERSION
    registered_model = registry.resolve(schema_name, schema_version)
    if type(payload) is not registered_model:
        raise LedgerValidationError(
            f"payload class is not registered for {schema_name} v{schema_version}"
        )
    return EventDraft(
        tenant_id=envelope.tenant_id,
        engagement_id=envelope.engagement_id,
        schema_name=schema_name,
        schema_version=schema_version,
        producer=envelope.producer,
        payload=payload.to_ledger_payload(),
        occurred_at=envelope.occurred_at,
        sensitivity=envelope.sensitivity,
        correlation_id=envelope.correlation_id,
        causation_id=envelope.causation_id,
        redaction_refs=envelope.redaction_refs,
    )
