"""Contract, exact-pair, digest, substitution, compatibility, and tamper proofs (M1.4b2b-A).

`evaluate_admission_for_runtime` must run the existing admission evaluator against the exact
caller-supplied capability and seal that exact `AdmissionResult`/`CapabilityAdmissionSnapshot`
pair into one frozen, digest-bound `AdmissionRuntimeBinding`. These tests prove the exact pair is
preserved, the binding digest is sensitive to every capability field, a tampered or incoherent
pair fails validation, AdmissionResult v1 is unchanged, and the binding is non-executable.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from blackbread.policy.admission import evaluate_admission
from blackbread.policy.admission_contracts import (
    ADMISSION_RESULT_SCHEMA,
    ADMISSION_RESULT_SCHEMA_VERSION,
    AdmissionResult,
)
from blackbread.policy.admission_runtime import (
    ADMISSION_RUNTIME_BINDING_SCHEMA,
    ADMISSION_RUNTIME_BINDING_SCHEMA_VERSION,
    AdmissionRuntimeBinding,
    _binding_digest,
    evaluate_admission_for_runtime,
)
from tests.conductor._builders import make_proposal
from tests.policy._builders import (
    capability_snapshot,
    identity_snapshot,
    manifest,
    policy_snapshot,
)

EVALUATED_AT = datetime(2026, 9, 3, 12, 1, tzinfo=UTC)

# Fields of CapabilityAdmissionSnapshot that carry a second valid value, mapped to that value.
# schema_name and schema_version are single-valued literals with no alternate valid value, so no
# valid mutation exists for them; the binding preimage still binds both.
_CAPABILITY_MUTATIONS: dict[str, object] = {
    "registry_schema_version": 2,
    "registry_digest": "7" * 64,
    "capability_id": "scout.other_capability.v1",
    "owner_agent": "Strike",
    "lifecycle": "FIELD_PROVEN",
    "input_schema": "OtherInput.v1",
    "risk_class": "AUTHENTICATION",
    "required_identity_tier": "T2",
    "approval_class": "OPERATOR_EXACT",
    "network_path": "TARGET_EGRESS",
    "supply_chain_digest": "8" * 64,
    "extractor_identity": "blackbread.extractors.other.v1",
    "extractor_digest": "9" * 64,
    "max_target_requests": 1,
    "max_deadline_seconds": 31,
}
# AdmissionResult copies these four registry-identity fields from the capability, so a valid
# binding must agree on them between the nested result and the sealed capability.
_CORE_FIELDS = (
    "registry_schema_version",
    "registry_digest",
    "capability_id",
    "supply_chain_digest",
)


def _admission_inputs(proposal, capability):
    return {
        "policy": policy_snapshot(graph_version=proposal.graph_version),
        "identity": identity_snapshot(proposal, achieved_tier=proposal.target_identity_tier),
        "capability": capability,
        "manifest": manifest(proposal),
        "evaluated_at": EVALUATED_AT,
    }


def _bind(proposal=None, capability=None):
    proposal = make_proposal() if proposal is None else proposal
    capability = capability_snapshot() if capability is None else capability
    binding = evaluate_admission_for_runtime(proposal, **_admission_inputs(proposal, capability))
    return binding, proposal, capability


def _admission(proposal, capability):
    return evaluate_admission(proposal, **_admission_inputs(proposal, capability))


def _result_copy(result: AdmissionResult, **overrides: object) -> AdmissionResult:
    fields = result.model_dump(exclude={"result_digest"})
    fields.update(overrides)
    return AdmissionResult.build(fields)


def test_binding_schema_identity_and_shape() -> None:
    binding, _, capability = _bind()
    assert (
        binding.schema_name
        == ADMISSION_RUNTIME_BINDING_SCHEMA
        == "policy.admission.runtime_binding"
    )
    assert binding.schema_version == ADMISSION_RUNTIME_BINDING_SCHEMA_VERSION == 1
    assert isinstance(binding.admission_result, AdmissionResult)
    assert binding.capability == capability
    assert len(binding.binding_digest) == 64


def test_exact_pair_matches_evaluate_admission_for_admitted() -> None:
    binding, proposal, capability = _bind()
    direct = _admission(proposal, capability)
    assert direct.outcome == "ADMITTED_FOR_RUNTIME_GATES"
    assert binding.admission_result == direct
    assert binding.admission_result.result_digest == direct.result_digest
    assert binding.admission_result.reason_code is None
    assert binding.capability == capability


def test_exact_outcome_and_reason_preserved_for_deny() -> None:
    # An expired proposal denies; the binding must embed the exact deny outcome and reason.
    proposal = make_proposal(
        created_at=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
        expires_at=datetime(2026, 9, 3, 10, 15, tzinfo=UTC),
    )
    binding, proposal, capability = _bind(proposal)
    direct = _admission(proposal, capability)
    assert direct.outcome == "DENY"
    assert binding.admission_result.outcome == "DENY"
    assert binding.admission_result.reason_code == direct.reason_code == "PROPOSAL_EXPIRED"


def test_evaluate_admission_for_runtime_is_deterministic() -> None:
    first, proposal, capability = _bind()
    second = evaluate_admission_for_runtime(proposal, **_admission_inputs(proposal, capability))
    assert first == second
    assert first.binding_digest == second.binding_digest


def test_evaluate_admission_for_runtime_does_not_mutate_inputs() -> None:
    proposal = make_proposal()
    capability = capability_snapshot()
    proposal_before = proposal.model_dump()
    capability_before = capability.model_dump()
    evaluate_admission_for_runtime(proposal, **_admission_inputs(proposal, capability))
    assert proposal.model_dump() == proposal_before
    assert capability.model_dump() == capability_before


@pytest.mark.parametrize("field", list(_CAPABILITY_MUTATIONS))
def test_binding_digest_changes_when_any_capability_field_changes(field: str) -> None:
    baseline, _, _ = _bind()
    result = baseline.admission_result
    mutated_capability = capability_snapshot(**{field: _CAPABILITY_MUTATIONS[field]})
    if field in _CORE_FIELDS:
        # Keep the nested result coherent so only the digest sensitivity is under test.
        mutated_result = _result_copy(result, **{field: _CAPABILITY_MUTATIONS[field]})
    else:
        mutated_result = result
    assert _binding_digest(mutated_result, mutated_capability) != baseline.binding_digest


@pytest.mark.parametrize("field", _CORE_FIELDS)
def test_core_field_mismatch_between_result_and_capability_is_rejected(field: str) -> None:
    # The digest is computed over the mismatched pair, so only the coherence check can reject it.
    baseline, _, _ = _bind()
    result = baseline.admission_result
    mismatched_capability = capability_snapshot(**{field: _CAPABILITY_MUTATIONS[field]})
    payload = {
        "schema_name": ADMISSION_RUNTIME_BINDING_SCHEMA,
        "schema_version": ADMISSION_RUNTIME_BINDING_SCHEMA_VERSION,
        "admission_result": result.model_dump(),
        "capability": mismatched_capability.model_dump(),
        "binding_digest": _binding_digest(result, mismatched_capability),
    }
    with pytest.raises(ValidationError):
        AdmissionRuntimeBinding.model_validate(payload)


def test_binding_production_is_single_sourced_through_admission() -> None:
    # Deterministic admission code owns production: the binding exposes no public constructor that
    # would let non-admission code seal an arbitrary result/capability pair. The sole public
    # producer is evaluate_admission_for_runtime, which evaluates admission from the exact
    # capability. Caller authentication and full-capability provenance are deferred
    # (LEDGER-GAP-001).
    assert not hasattr(AdmissionRuntimeBinding, "build")


@pytest.mark.parametrize(
    "field",
    [
        "approval_class",
        "network_path",
        "risk_class",
        "required_identity_tier",
        "lifecycle",
        "capability_id",
        "registry_digest",
        "supply_chain_digest",
        "extractor_identity",
        "extractor_digest",
        "max_target_requests",
        "max_deadline_seconds",
    ],
)
def test_tampered_capability_field_with_stale_digest_is_rejected(field: str) -> None:
    baseline, _, _ = _bind()
    data = baseline.model_dump()
    data["capability"][field] = _CAPABILITY_MUTATIONS[field]
    # binding_digest is left at its stale value.
    with pytest.raises(ValidationError):
        AdmissionRuntimeBinding.model_validate(data)


def test_tampered_admission_result_digest_is_rejected() -> None:
    baseline, _, _ = _bind()
    data = baseline.model_dump()
    data["admission_result"]["result_digest"] = "0" * 64
    with pytest.raises(ValidationError):
        AdmissionRuntimeBinding.model_validate(data)


def test_tampered_admission_result_contents_with_recomputed_result_digest_is_rejected() -> None:
    # A caller who rebinds the nested result's own digest still cannot keep the stale binding
    # digest: the binding preimage includes the result digest.
    baseline, _, _ = _bind()
    denied = _result_copy(
        baseline.admission_result, outcome="DENY", reason_code="STRUCTURAL_BUDGET_EXCEEDED"
    )
    data = baseline.model_dump()
    data["admission_result"] = denied.model_dump()
    with pytest.raises(ValidationError):
        AdmissionRuntimeBinding.model_validate(data)


def test_roundtrip_serialization_is_stable() -> None:
    binding, _, _ = _bind()
    restored = AdmissionRuntimeBinding.model_validate(binding.model_dump())
    assert restored == binding
    assert restored.binding_digest == binding.binding_digest


def test_unknown_schema_name_is_rejected() -> None:
    baseline, _, _ = _bind()
    data = baseline.model_dump()
    data["schema_name"] = "policy.admission.runtime_binding.v2"
    with pytest.raises(ValidationError):
        AdmissionRuntimeBinding.model_validate(data)


def test_unknown_schema_version_is_rejected() -> None:
    baseline, _, _ = _bind()
    data = baseline.model_dump()
    data["schema_version"] = 2
    with pytest.raises(ValidationError):
        AdmissionRuntimeBinding.model_validate(data)


def test_extra_field_is_rejected() -> None:
    baseline, _, _ = _bind()
    data = baseline.model_dump()
    data["execution_token"] = "1" * 64
    with pytest.raises(ValidationError):
        AdmissionRuntimeBinding.model_validate(data)


def test_binding_is_non_executable() -> None:
    fields = set(AdmissionRuntimeBinding.model_fields)
    assert fields == {
        "schema_name",
        "schema_version",
        "admission_result",
        "capability",
        "binding_digest",
    }
    forbidden = {
        "allow",
        "outcome",
        "decision_id",
        "policy_decision_id",
        "lease_id",
        "work_order_id",
        "executable_token",
        "target_effect",
        "capability_activation",
    }
    assert forbidden.isdisjoint(fields)
    for name in ("activate", "authorize", "execute", "to_work_order", "to_lease"):
        assert not hasattr(AdmissionRuntimeBinding, name)


def test_admission_result_v1_is_unchanged() -> None:
    assert ADMISSION_RESULT_SCHEMA == "policy.admission.result"
    assert ADMISSION_RESULT_SCHEMA_VERSION == 1
    binding, proposal, capability = _bind()
    assert binding.admission_result == _admission(proposal, capability)
    assert binding.admission_result.schema_version == 1
    assert "binding_digest" not in AdmissionResult.model_fields
    assert "capability" not in AdmissionResult.model_fields
