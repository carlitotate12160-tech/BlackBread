import uuid
from datetime import UTC, datetime

import pytest

from blackbread.ledger import EventDraft
from blackbread.ledger.draft import (
    MAX_EVENT_PAYLOAD_BYTES,
    MAX_REDACTION_REFS,
    MAX_SCHEMA_VERSION,
)
from blackbread.ledger.errors import LedgerValidationError


def _values() -> dict[str, object]:
    return {
        "tenant_id": "tenant-a",
        "engagement_id": uuid.uuid4(),
        "schema_name": "test.event",
        "schema_version": 1,
        "producer": "test-producer",
        "payload": {"marker": "x"},
        "occurred_at": datetime.now(UTC),
    }


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("tenant_id", " ", "tenant_id"),
        ("schema_name", "", "schema_name"),
        ("producer", "x" * 201, "producer"),
        ("producer", "bad\x00producer", "NUL"),
        ("engagement_id", "not-a-uuid", "engagement_id"),
        ("schema_version", 0, "positive"),
        ("schema_version", True, "integer"),
        ("schema_version", MAX_SCHEMA_VERSION + 1, "INTEGER range"),
        ("occurred_at", datetime(2026, 8, 28), "timezone-aware"),
        ("sensitivity", "secret", "sensitivity"),
        ("sensitivity", [], "sensitivity"),
        ("correlation_id", "not-a-uuid", "correlation_id"),
        ("payload", {"value": float("nan")}, "non-finite"),
        ("payload", {"value": "\x00"}, "NUL"),
        ("payload", {"value": 1e20}, "round-trip"),
        ("redaction_refs", "not-a-sequence", "redaction_refs"),
        ("redaction_refs", None, "redaction_refs"),
        ("redaction_refs", {"artifact": "one"}, "redaction_refs"),
        ("redaction_refs", ["x"] * (MAX_REDACTION_REFS + 1), "too many"),
        ("redaction_refs", [""], "redaction reference"),
    ],
)
def test_event_draft_rejects_invalid_envelope(
    field: str,
    value: object,
    match: str,
) -> None:
    values = _values()
    values[field] = value
    with pytest.raises(LedgerValidationError, match=match):
        EventDraft(**values)


def test_event_draft_rejects_oversized_payload() -> None:
    values = _values()
    values["payload"] = {"value": "x" * (MAX_EVENT_PAYLOAD_BYTES + 1)}
    with pytest.raises(LedgerValidationError, match="size limit"):
        EventDraft(**values)


def test_event_draft_rejects_oversized_payload_before_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_serialization(*args: object, **kwargs: object) -> None:
        raise AssertionError("oversized input reached json.dumps")

    monkeypatch.setattr("blackbread.ledger.hashing.json.dumps", fail_serialization)
    values = _values()
    values["payload"] = {"value": "x" * (MAX_EVENT_PAYLOAD_BYTES + 1)}

    with pytest.raises(LedgerValidationError, match="size limit"):
        EventDraft(**values)


def test_event_draft_freezes_redaction_reference_order() -> None:
    values = _values()
    values["redaction_refs"] = ["artifact://one", "artifact://two"]
    draft = EventDraft(**values)
    assert draft.redaction_refs == ("artifact://one", "artifact://two")
