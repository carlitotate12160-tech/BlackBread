"""ActionProposal contract: field validation, boundaries, and immutability."""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from blackbread.conductor.contracts import (
    ACTION_PROPOSAL_SCHEMA,
    ACTION_PROPOSAL_SCHEMA_VERSION,
    ActionProposal,
    BudgetRequest,
    ConductorContractError,
    GraphVersionReference,
    ParameterEnvelope,
    ResourceEstimates,
    TargetReference,
)

from ._builders import make_proposal, proposal_fields, raw_proposal


def test_valid_proposal_is_admitted_and_frozen() -> None:
    proposal = make_proposal()
    assert proposal.schema_name == ACTION_PROPOSAL_SCHEMA
    assert proposal.schema_version == ACTION_PROPOSAL_SCHEMA_VERSION
    assert proposal.tenant_id == "tenant-a"
    with pytest.raises(ValidationError):
        proposal.tenant_id = "tenant-b"


def test_unknown_schema_name_fails_closed() -> None:
    with pytest.raises(ValidationError):
        make_proposal(schema_name="conductor.other")


def test_unknown_schema_version_fails_closed() -> None:
    with pytest.raises(ValidationError):
        make_proposal(schema_version=2)


def test_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        make_proposal(**{"unexpected": "x"})


@pytest.mark.parametrize("field", sorted(proposal_fields().keys()))
def test_missing_field_fails_closed(field: str) -> None:
    fields = proposal_fields()
    del fields[field]
    with pytest.raises(ValidationError):
        ActionProposal(**fields)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "1"),
        ("schema_version", True),
        ("proposal_id", "not-a-uuid"),
        ("engagement_id", 123),
        ("agent_instance_id", "33333333-3333-3333-3333-333333333333"),
        ("capability_id", 7),
        ("intended_proof", 7),
        ("idempotency_key", 7),
    ],
)
def test_wrong_primitive_types_fail_closed(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        make_proposal(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", " tenant-a"),
        ("tenant_id", "tenant-a "),
        ("tenant_id", ""),
        ("tenant_id", "   "),
        ("tenant_id", "tenant\x00a"),
        ("tenant_id", "t" * 101),
        ("intended_proof", " proof"),
        ("idempotency_key", "idem "),
        ("oracle_ref", ""),
    ],
)
def test_noncanonical_text_fails_closed(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        make_proposal(**{field: value})


@pytest.mark.parametrize(
    "capability_id",
    [
        "scout_passive_asset_intelligence_v1",
        "scout.passive_asset_intelligence",
        "Scout.Passive.v1",
        "scout.passive.v0",
        "scout.passive.v01",
        "scout..v1",
    ],
)
def test_noncanonical_capability_id_fails_closed(capability_id: str) -> None:
    with pytest.raises(ValidationError):
        make_proposal(capability_id=capability_id)


def test_versioned_capability_id_is_admitted() -> None:
    proposal = make_proposal(capability_id="report.evidence_build.v3")
    assert proposal.capability_id == "report.evidence_build.v3"


@pytest.mark.parametrize("role", ["Scout", "Strike", "Exploit", "Post-Exploit", "Report"])
def test_allowed_agent_roles_admitted(role: str) -> None:
    assert make_proposal(agent_role=role).agent_role == role


@pytest.mark.parametrize("role", ["scout", "Planner", "Conductor", "", "PostExploit"])
def test_invalid_agent_role_fails_closed(role: str) -> None:
    with pytest.raises(ValidationError):
        make_proposal(agent_role=role)


@pytest.mark.parametrize("tier", ["T0", "T1", "T2", "T3"])
def test_identity_tiers_admitted(tier: str) -> None:
    assert make_proposal(target_identity_tier=tier).target_identity_tier == tier


@pytest.mark.parametrize("tier", ["T4", "t0", "0", "", "TIER0"])
def test_invalid_identity_tier_fails_closed(tier: str) -> None:
    with pytest.raises(ValidationError):
        make_proposal(target_identity_tier=tier)


@pytest.mark.parametrize(
    ("target_kind", "canonical_value"),
    [
        ("root_domain", "example.com"),
        ("exact_host", "host.example.com"),
        ("exact_address", "192.0.2.1"),
        ("cloud_tenant", "acme-tenant-01"),
    ],
)
def test_target_kinds_admitted(target_kind: str, canonical_value: str) -> None:
    reference = TargetReference(target_kind=target_kind, canonical_value=canonical_value)
    assert make_proposal(target=reference).target.target_kind == target_kind


def test_invalid_target_kind_fails_closed() -> None:

    with pytest.raises(ValidationError):
        TargetReference(target_kind="ip_range", canonical_value="example.com")


@pytest.mark.parametrize(
    "tzinfo",
    [None, timezone(timedelta(hours=7))],
)
def test_non_utc_and_naive_timestamps_fail_closed(tzinfo: Any) -> None:
    stamp = datetime(2026, 9, 3, 12, 0, 0, tzinfo=tzinfo)
    with pytest.raises(ValidationError):
        make_proposal(created_at=stamp, expires_at=stamp + timedelta(minutes=5))


def test_reversed_validity_window_fails_closed() -> None:
    created = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        make_proposal(created_at=created, expires_at=created - timedelta(minutes=1))


def test_equal_validity_window_fails_closed() -> None:
    created = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        make_proposal(created_at=created, expires_at=created)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("risk", -0.1),
        ("risk", 1.1),
        ("information_gain", -0.01),
        ("information_gain", 2.0),
        ("opsec_noise", -1.0),
        ("opsec_noise", 1.5),
        ("cost", -0.5),
        ("cost", float("inf")),
        ("cost", float("nan")),
    ],
)
def test_invalid_estimate_bounds_fail_closed(field: str, value: Any) -> None:

    valid: dict[str, Any] = {
        "risk": 0.1,
        "cost": 1.0,
        "information_gain": 0.2,
        "opsec_noise": 0.3,
    }
    valid[field] = value
    with pytest.raises(ValidationError):
        ResourceEstimates(**valid)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_requests", -1),
        ("target_requests", 10_000_000),
        ("target_requests", True),
        ("deadline_seconds", 0),
        ("deadline_seconds", -5),
        ("deadline_seconds", 10_000_000),
    ],
)
def test_invalid_budget_values_fail_closed(field: str, value: Any) -> None:

    valid: dict[str, Any] = {"target_requests": 0, "deadline_seconds": 30}
    valid[field] = value
    with pytest.raises(ValidationError):
        BudgetRequest(**valid)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state_root", "z" * 64),
        ("state_root", "a" * 63),
        ("ledger_head_hash", "A" * 64),
        ("ledger_event_count", 0),
        ("ledger_event_count", -1),
        ("state_root_version", 0),
        ("projector_version", 0),
    ],
)
def test_invalid_graph_version_fails_closed(field: str, value: Any) -> None:

    valid: dict[str, Any] = {
        "state_root_version": 2,
        "projector_version": 1,
        "state_root": "a" * 64,
        "ledger_event_count": 3,
        "ledger_head_hash": "b" * 64,
    }
    valid[field] = value
    with pytest.raises(ValidationError):
        GraphVersionReference(**valid)


def test_too_many_precondition_refs_fail_closed() -> None:
    with pytest.raises(ValidationError):
        make_proposal(precondition_refs=tuple(f"pre-{index}" for index in range(65)))


def test_blank_precondition_ref_fails_closed() -> None:
    with pytest.raises(ValidationError):
        make_proposal(precondition_refs=("",))


@pytest.mark.parametrize(
    "parameters",
    [
        {"value": float("nan")},
        {"value": float("inf")},
        {1: "x"},
        {"value": object()},
    ],
)
def test_noncanonical_parameters_fail_closed(parameters: Any) -> None:
    with pytest.raises((ValidationError, ConductorContractError)):
        ParameterEnvelope(input_schema_ref="Sample.v1", parameters=parameters)


def test_excessive_parameters_fail_closed() -> None:
    oversized = {"blob": "x" * 200_000}
    with pytest.raises((ValidationError, ConductorContractError)):
        ParameterEnvelope(input_schema_ref="Sample.v1", parameters=oversized)


def test_invalid_input_schema_ref_fails_closed() -> None:
    with pytest.raises(ValidationError):
        ParameterEnvelope(input_schema_ref="not a ref", parameters={"a": 1})


def test_parameter_snapshot_is_immutable_after_validation() -> None:
    mutable: dict[str, Any] = {"sources": ["ct", "dns"]}
    envelope = ParameterEnvelope(input_schema_ref="Sample.v1", parameters=mutable)
    snapshot = envelope.canonical_parameters
    mutable["sources"].append("http")
    mutable["added"] = True
    assert envelope.canonical_parameters == snapshot


def test_parameter_nested_values_are_deeply_immutable() -> None:
    envelope = ParameterEnvelope(
        input_schema_ref="Sample.v1",
        parameters={"sources": ["ct", "dns"], "nested": {"depth": 1}},
    )
    snapshot = envelope.canonical_parameters
    with pytest.raises((AttributeError, TypeError)):
        envelope.parameters["sources"].append("http")  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        envelope.parameters["nested"]["depth"] = 2  # type: ignore[index]
    assert envelope.canonical_parameters == snapshot


def test_from_untrusted_admits_canonical_mapping() -> None:
    proposal = ActionProposal.from_untrusted(raw_proposal())
    assert proposal.tenant_id == "tenant-a"
    assert proposal.proposal_id == uuid.UUID("11111111-1111-1111-1111-111111111111")


def test_from_untrusted_rejects_oversized_raw() -> None:
    oversized = raw_proposal()
    oversized["unbounded_field"] = "x" * 500_000
    with pytest.raises(ConductorContractError):
        ActionProposal.from_untrusted(oversized)


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema_version": 2},
        {"tenant_id": " tenant-a"},
        {"capability_id": "bad"},
        {"agent_role": "Planner"},
    ],
)
def test_from_untrusted_rejects_malformed_mapping(mutation: dict[str, Any]) -> None:

    with pytest.raises(ConductorContractError):
        ActionProposal.from_untrusted(raw_proposal(**mutation))


def test_from_untrusted_rejects_non_mapping() -> None:

    with pytest.raises(ConductorContractError):
        ActionProposal.from_untrusted(["not", "a", "mapping"])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("target_kind", "canonical_value"),
    [
        ("exact_address", "example.com"),
        ("root_domain", "192.0.2.1"),
        ("exact_host", "EXAMPLE.COM"),
        ("exact_address", "2001:0db8::1"),
        ("root_domain", "Example.com"),
        ("exact_address", "999.0.2.1"),
    ],
)
def test_target_kind_and_value_must_be_canonically_consistent(
    target_kind: str, canonical_value: str
) -> None:
    with pytest.raises(ValidationError):
        TargetReference(target_kind=target_kind, canonical_value=canonical_value)


@pytest.mark.parametrize(
    ("target_kind", "canonical_value"),
    [
        ("root_domain", "example.com"),
        ("exact_host", "host.example.com"),
        ("exact_address", "192.0.2.1"),
        ("exact_address", "2001:db8::1"),
        ("cloud_tenant", "acme-tenant-01"),
    ],
)
def test_canonical_target_identity_is_admitted(target_kind: str, canonical_value: str) -> None:
    reference = TargetReference(target_kind=target_kind, canonical_value=canonical_value)
    assert reference.target_kind == target_kind
    assert reference.canonical_value == canonical_value
    assert make_proposal(target=reference).target.canonical_value == canonical_value


@pytest.mark.parametrize("field", ["tenant_id", "intended_proof", "idempotency_key", "oracle_ref"])
def test_invalid_unicode_surrogate_fails_closed(field: str) -> None:
    with pytest.raises(ValidationError):
        make_proposal(**{field: "bad\ud800value"})


def test_lone_surrogate_target_value_fails_closed() -> None:
    with pytest.raises(ValidationError):
        TargetReference(target_kind="cloud_tenant", canonical_value="\ud800")


def test_target_rejects_scope_authority_that_normalizes_instead_of_rejecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "blackbread.conductor.contracts.canonical_scope_value",
        lambda kind, value: (kind, f"{value}.normalized"),
    )
    with pytest.raises(ValidationError):
        TargetReference(target_kind="cloud_tenant", canonical_value="acme-tenant-01")


def test_oversized_mapping_rejected_before_full_traversal() -> None:
    class _CountingMapping(Mapping[str, object]):
        def __init__(self, count: int, value_size: int) -> None:
            self.count = count
            self.value_size = value_size
            self.visited = 0

        def __iter__(self) -> Iterator[str]:
            for index in range(self.count):
                self.visited += 1
                yield f"key_{index}"

        def __len__(self) -> int:
            return self.count

        def __getitem__(self, key: str) -> object:
            return "x" * self.value_size

    counting = _CountingMapping(count=1_000_000, value_size=256)
    with pytest.raises(ConductorContractError):
        ActionProposal.from_untrusted(counting)
    assert counting.visited < counting.count
