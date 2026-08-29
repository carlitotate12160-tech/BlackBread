import uuid
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from pydantic import ConfigDict, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from blackbread.ledger import append_event, verify_chain
from blackbread.ledger.catalog import (
    EngagementAttested,
    EngagementMode,
    EngagementScope,
    EngagementStopped,
    ScopeExclusion,
    default_registry,
)
from blackbread.ledger.errors import LedgerValidationError
from blackbread.ledger.schema import (
    EventEnvelope,
    EventPayload,
    EventRegistry,
    UnknownEventSchemaError,
    to_draft,
)
from blackbread.models.core import Engagement


class _ThingV1(EventPayload):
    SCHEMA_NAME: ClassVar[str] = "test.thing"
    SCHEMA_VERSION: ClassVar[int] = 1
    value: str


class _ThingV2(EventPayload):
    SCHEMA_NAME: ClassVar[str] = "test.thing"
    SCHEMA_VERSION: ClassVar[int] = 2
    value: str
    count: int


class _RogueThingV1(EventPayload):
    SCHEMA_NAME: ClassVar[str] = "test.thing"
    SCHEMA_VERSION: ClassVar[int] = 1
    value: str


class _BadName(EventPayload):
    SCHEMA_NAME: ClassVar[str] = "Bad Name"
    SCHEMA_VERSION: ClassVar[int] = 1


class _BoolVersion(EventPayload):
    SCHEMA_NAME: ClassVar[str] = "test.bool_version"
    SCHEMA_VERSION: ClassVar[int] = True


class _OversizedVersion(EventPayload):
    SCHEMA_NAME: ClassVar[str] = "test.oversized_version"
    SCHEMA_VERSION: ClassVar[int] = 2_147_483_648


class _UndeclaredThing(EventPayload):
    value: str


class _MutableThing(EventPayload):
    SCHEMA_NAME: ClassVar[str] = "test.mutable_thing"
    SCHEMA_VERSION: ClassVar[int] = 1
    values: list[str]
    metadata: dict[str, str]


class _LooseThing(EventPayload):
    model_config = ConfigDict(extra="allow", frozen=True, strict=True)
    SCHEMA_NAME: ClassVar[str] = "test.loose_thing"
    SCHEMA_VERSION: ClassVar[int] = 1


class _UnfrozenThing(EventPayload):
    model_config = ConfigDict(extra="forbid", frozen=False, strict=True)
    SCHEMA_NAME: ClassVar[str] = "test.unfrozen_thing"
    SCHEMA_VERSION: ClassVar[int] = 1


class _CoercingThing(EventPayload):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=False)
    SCHEMA_NAME: ClassVar[str] = "test.coercing_thing"
    SCHEMA_VERSION: ClassVar[int] = 1


class _HookSkippingThing(EventPayload):
    SCHEMA_NAME: ClassVar[str] = "test.hook_skipping_thing"
    SCHEMA_VERSION: ClassVar[int] = 1
    value: str

    def model_post_init(self, context: object) -> None:
        del context


def _scope() -> EngagementScope:
    return EngagementScope(
        root_domains=("example.com",),
        exact_hosts=("api.example.com",),
        exact_addresses=("192.0.2.10", "2001:db8::10"),
        cloud_tenants=("aws:123456789012",),
        exclusions=(ScopeExclusion(target_type="exact_host", value="status.example.com"),),
        third_party_boundaries=("cdn-provider",),
    )


def _attestation() -> EngagementAttested:
    valid_from = datetime.now(UTC)
    return EngagementAttested(
        manifest_hash="a" * 64,
        manifest_signature_ref="kms://authorization/key-1/signatures/attestation-1",
        attested_by="designated-user-1",
        mode=EngagementMode(
            knowledge="blind",
            execution="covert",
            tier="recon_only",
            pacing="short",
        ),
        scope=_scope(),
        valid_from=valid_from,
        expires_at=valid_from + timedelta(days=7),
    )


def _attestation_json_payload() -> dict[str, object]:
    return _attestation().to_ledger_payload()


def _envelope(engagement: Engagement) -> EventEnvelope:
    return EventEnvelope(
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        producer="conductor",
        occurred_at=datetime.now(UTC),
    )


def test_default_registry_is_complete_and_frozen() -> None:
    registry = default_registry()

    assert registry.registered_keys == {
        ("engagement.attested", 1),
        ("engagement.stopped", 1),
    }
    assert registry.resolve("engagement.attested", 1) is EngagementAttested
    with pytest.raises(LedgerValidationError, match="frozen"):
        registry.register(_ThingV1)


@pytest.mark.parametrize(
    "model",
    [_BadName, _BoolVersion, _OversizedVersion, object],
)
def test_register_rejects_invalid_schema_declarations(model: object) -> None:
    registry = EventRegistry()
    with pytest.raises(LedgerValidationError):
        registry.register(model)


@pytest.mark.parametrize("model", [_LooseThing, _UnfrozenThing, _CoercingThing])
def test_register_rejects_weakened_payload_config(model: type[EventPayload]) -> None:
    with pytest.raises(LedgerValidationError, match="strict frozen config"):
        EventRegistry().register(model)


def test_register_rejects_subclass_bypassing_snapshot_hook() -> None:
    with pytest.raises(LedgerValidationError, match="snapshot hook"):
        EventRegistry().register(_HookSkippingThing)


def test_register_duplicate_rejected_but_versions_coexist() -> None:
    registry = EventRegistry()
    registry.register(_ThingV1)
    registry.register(_ThingV2)

    assert registry.resolve("test.thing", 1) is _ThingV1
    assert registry.resolve("test.thing", 2) is _ThingV2
    with pytest.raises(LedgerValidationError, match="already registered"):
        registry.register(_ThingV1)


@pytest.mark.parametrize(
    ("name", "version"),
    [
        ("does.not.exist", 1),
        ("engagement.attested", 999),
    ],
)
def test_resolve_unknown_schema_fails_closed(name: str, version: int) -> None:
    with pytest.raises(UnknownEventSchemaError):
        default_registry().resolve(name, version)


@pytest.mark.parametrize(
    ("name", "version"),
    [
        ("Bad Name", 1),
        ("engagement.attested", 0),
        ("engagement.attested", True),
    ],
)
def test_resolve_rejects_noncanonical_schema_key(name: str, version: int) -> None:
    with pytest.raises(LedgerValidationError):
        default_registry().resolve(name, version)


def test_parse_valid_json_payload_returns_typed_model() -> None:
    parsed = default_registry().parse(
        "engagement.attested",
        1,
        _attestation_json_payload(),
    )

    assert isinstance(parsed, EngagementAttested)
    assert parsed.scope.exact_addresses == ("192.0.2.10", "2001:db8::10")
    assert parsed.mode == EngagementMode(
        knowledge="blind",
        execution="covert",
        tier="recon_only",
        pacing="short",
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"rogue": "x"},
        {"manifest_hash": "not-a-hash"},
        {"attested_by": 123},
    ],
)
def test_parse_rejects_extra_invalid_and_coerced_fields(mutation: dict[str, object]) -> None:
    payload = _attestation_json_payload()
    payload.update(mutation)

    with pytest.raises(LedgerValidationError, match="does not conform"):
        default_registry().parse("engagement.attested", 1, payload)


def test_parse_rejects_missing_field_and_non_mapping() -> None:
    with pytest.raises(LedgerValidationError, match="does not conform"):
        default_registry().parse("engagement.attested", 1, {"attested_by": "user-1"})
    with pytest.raises(LedgerValidationError, match="mapping"):
        default_registry().parse("engagement.attested", 1, [])


@pytest.mark.parametrize(
    "scope",
    [
        {"root_domains": ("Example.com",)},
        {"root_domains": ("*.example.com",)},
        {"root_domains": ("127.0.0.1",)},
        {"root_domains": ("127.1",)},
        {"root_domains": ("0177.0.0.1",)},
        {"root_domains": ("0x7f.0.0.1",)},
        {"exact_hosts": ("127.0.0.1",)},
        {"exact_hosts": ("127.1",)},
        {
            "exclusions": ({"target_type": "exact_host", "value": "0x7f.0.0.1"},),
            "root_domains": ("example.com",),
        },
        {"root_domains": ("example.com", "example.com")},
        {"root_domains": ("z.example.com", "a.example.com")},
        {"root_domains": tuple(f"{index}.example.com" for index in range(501))},
        {"exact_addresses": ("2001:0db8::10",)},
        {"exact_addresses": ("fe80::1%eth0",)},
        {
            "exclusions": ({"target_type": "exact_host", "value": "Admin.Example.com"},),
            "root_domains": ("example.com",),
        },
        {
            "exclusions": ({"target_type": "exact_address", "value": "2001:0db8::10"},),
            "root_domains": ("example.com",),
        },
        {},
    ],
)
def test_scope_rejects_noncanonical_or_empty_values(scope: dict[str, object]) -> None:
    with pytest.raises((ValidationError, ValueError)):
        EngagementScope(**scope)


def test_scope_allows_numeric_labels_when_hostname_has_domain_suffix() -> None:
    scope = EngagementScope(exact_hosts=("127.1.example.com",))

    assert scope.exact_hosts == ("127.1.example.com",)


def test_attestation_rejects_invalid_validity_and_naive_time() -> None:
    now = datetime.now(UTC)
    values = {
        "manifest_hash": "a" * 64,
        "manifest_signature_ref": "kms://signature/1",
        "attested_by": "user-1",
        "mode": EngagementMode(
            knowledge="blind",
            execution="covert",
            tier="recon_only",
            pacing="short",
        ),
        "scope": _scope(),
        "valid_from": now,
        "expires_at": now,
    }
    with pytest.raises(ValidationError, match="expiry"):
        EngagementAttested(**values)

    values["valid_from"] = datetime(2026, 8, 28)
    values["expires_at"] = now + timedelta(days=1)
    with pytest.raises(ValidationError, match="timezone-aware"):
        EngagementAttested(**values)


def test_stopped_event_is_typed_and_strict() -> None:
    event = EngagementStopped(
        reason="white_cell_stop",
        stopped_by="operator-1",
        disposition="freeze_forensic_hold",
    )
    assert event.reason == "white_cell_stop"

    with pytest.raises(ValidationError):
        EngagementStopped(
            reason="invented_reason",
            stopped_by="operator-1",
            disposition="freeze_forensic_hold",
        )
    with pytest.raises(ValidationError, match="require canonical detail"):
        EngagementStopped(
            reason="other",
            stopped_by="operator-1",
            disposition="freeze_forensic_hold",
        )
    assert (
        EngagementStopped(
            reason="other",
            detail="client-defined emergency stop",
            stopped_by="operator-1",
            disposition="freeze_forensic_hold",
        ).detail
        == "client-defined emergency stop"
    )


@pytest.mark.parametrize(
    "reason",
    [
        "white_cell_stop",
        "service_instability",
        "target_identity_uncertain",
        "third_party_boundary",
        "real_incident_collision",
        "unexpected_sensitive_data",
        "operator_heartbeat_lost",
    ],
)
def test_stopped_event_preserves_contract_stop_triggers(reason: str) -> None:
    event = EngagementStopped(
        reason=reason,
        stopped_by="conductor",
        disposition="graceful_stop",
    )

    assert event.reason == reason


@pytest.mark.parametrize("stopped_by", [" ", "x" * 201, "bad\x00actor", "\ud800"])
def test_stopped_event_rejects_noncanonical_actor(stopped_by: str) -> None:
    with pytest.raises(ValidationError):
        EngagementStopped(
            reason="operator_stop",
            stopped_by=stopped_by,
            disposition="graceful_stop",
        )


def test_to_draft_requires_exact_registered_payload_class() -> None:
    registry = EventRegistry()
    registry.register(_ThingV1)
    envelope = EventEnvelope(
        tenant_id="tenant-a",
        engagement_id=uuid.uuid4(),
        producer="test",
        occurred_at=datetime.now(UTC),
    )

    draft = to_draft(_ThingV1(value="x"), envelope, registry=registry)
    assert draft.schema_name == "test.thing"
    assert draft.payload == {"value": "x"}
    with pytest.raises(LedgerValidationError, match="payload class"):
        to_draft(_RogueThingV1(value="x"), envelope, registry=registry)
    with pytest.raises(LedgerValidationError, match="must inherit"):
        to_draft(object(), envelope, registry=registry)


def test_to_draft_rejects_missing_schema_declaration_as_validation_error() -> None:
    envelope = EventEnvelope(
        tenant_id="tenant-a",
        engagement_id=uuid.uuid4(),
        producer="test",
        occurred_at=datetime.now(UTC),
    )

    with pytest.raises(LedgerValidationError, match="schema name"):
        to_draft(_UndeclaredThing(value="x"), envelope, registry=EventRegistry())


def test_to_draft_revalidates_model_construct_payload() -> None:
    registry = EventRegistry()
    registry.register(_ThingV1)
    envelope = EventEnvelope(
        tenant_id="tenant-a",
        engagement_id=uuid.uuid4(),
        producer="test",
        occurred_at=datetime.now(UTC),
    )
    unvalidated = _ThingV1.model_construct()

    with pytest.raises(LedgerValidationError, match="does not conform"):
        to_draft(unvalidated, envelope, registry=registry)


def test_event_payload_serialization_rejects_nested_mutation() -> None:
    registry = EventRegistry()
    registry.register(_MutableThing)
    envelope = EventEnvelope(
        tenant_id="tenant-a",
        engagement_id=uuid.uuid4(),
        producer="test",
        occurred_at=datetime.now(UTC),
    )
    payload = _MutableThing(values=["original"], metadata={"state": "validated"})

    payload.values.append("mutated")
    payload.metadata["state"] = "mutated"

    with pytest.raises(LedgerValidationError, match="mutated after validation"):
        to_draft(payload, envelope, registry=registry)


async def test_typed_attestation_appends_parses_and_verifies(
    session: AsyncSession,
    engagement: Engagement,
) -> None:
    registry = default_registry()
    draft = to_draft(_attestation(), _envelope(engagement), registry=registry)
    event = await append_event(session, draft)
    await session.commit()

    parsed = registry.parse(event.schema_name, event.schema_version, event.payload)
    result = await verify_chain(
        session.bind,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )

    assert isinstance(parsed, EngagementAttested)
    assert result.ok is True
    assert result.event_count == 1


async def test_typed_stop_appends_and_verifies(
    session: AsyncSession,
    engagement: Engagement,
) -> None:
    payload = EngagementStopped(
        reason="white_cell_stop",
        stopped_by="operator-1",
        disposition="graceful_stop",
    )
    draft = to_draft(payload, _envelope(engagement), registry=default_registry())
    event = await append_event(session, draft)
    await session.commit()
    result = await verify_chain(
        session.bind,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )

    assert event.schema_name == "engagement.stopped"
    assert result.ok is True
