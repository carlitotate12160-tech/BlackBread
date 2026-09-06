"""Admission-to-runtime binding that seals the exact admitted capability (M1.4b2b-A).

Admission (`evaluate_admission`) and the future runtime-gate evaluator (M1.4b2b-B) each need the
capability profile. Supplying the capability twice — once to admission and again, independently,
to the runtime evaluator — opens a cross-stage substitution seam: a caller can hand the runtime
evaluator a different capability that shares only the registry-identity fields the runtime binding
check compares (registry schema version, registry digest, capability id, supply-chain digest, owner)
while carrying a weaker ``approval_class``, ``network_path``, ``risk_class``, or identity tier. The
runtime gates then evaluate a decision that was admitted under a stronger capability with the weaker
capability's approval, OPSEC, and lock semantics.

This module removes that seam structurally rather than by adding another runtime comparison.
``evaluate_admission_for_runtime`` runs the existing admission evaluator against the exact
caller-supplied capability and seals that exact ``AdmissionResult`` and the exact
``CapabilityAdmissionSnapshot`` into one frozen, digest-bound ``AdmissionRuntimeBinding``. The
runtime evaluator must consume the capability only through this binding and must never accept a
second independently supplied snapshot.

The binding provides integrity and stage continuity, not caller authentication. It grants no
execution authority: it cannot represent ALLOW, a decision, a lease, a work order, an executable
token, a capability activation, or any target effect. Durable provenance and publication remain
later ledger/persistence work.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from blackbread.conductor.contracts import ActionProposal, HexDigest, SchemaVersionOne
from blackbread.ledger.hashing import canonical_json, sha256_hex
from blackbread.policy.admission import evaluate_admission
from blackbread.policy.admission_contracts import (
    AdmissionResult,
    CapabilityAdmissionSnapshot,
    DestinationManifest,
    EngagementPolicySnapshot,
    TargetIdentitySnapshot,
)

ADMISSION_RUNTIME_BINDING_SCHEMA = "policy.admission.runtime_binding"
ADMISSION_RUNTIME_BINDING_SCHEMA_VERSION = 1

_BINDING_DIGEST_DOMAIN = "blackbread.policy.admission.runtime_binding_digest.v1"

# AdmissionResult copies these four registry-identity fields from the capability it evaluated. A
# nested result and capability that disagree here were never evaluated together, so the pair is
# rejected before the binding is trusted.
_CORE_FIELDS = (
    "registry_schema_version",
    "registry_digest",
    "capability_id",
    "supply_chain_digest",
)


def _binding_preimage(
    admission_result: AdmissionResult, capability: CapabilityAdmissionSnapshot
) -> list[object]:
    """Explicit ordered preimage for the binding digest.

    Never relies on Pydantic or dict field order. It binds the binding schema identity, the nested
    admission result digest, and every field of the exact capability, so any change to the sealed
    pair changes the binding digest.
    """
    return [
        ["schema_name", ADMISSION_RUNTIME_BINDING_SCHEMA],
        ["schema_version", ADMISSION_RUNTIME_BINDING_SCHEMA_VERSION],
        ["admission_result_digest", admission_result.result_digest],
        ["capability_schema_name", capability.schema_name],
        ["capability_schema_version", capability.schema_version],
        ["registry_schema_version", capability.registry_schema_version],
        ["registry_digest", capability.registry_digest],
        ["capability_id", capability.capability_id],
        ["owner_agent", capability.owner_agent],
        ["lifecycle", capability.lifecycle],
        ["input_schema", capability.input_schema],
        ["risk_class", capability.risk_class],
        ["required_identity_tier", capability.required_identity_tier],
        ["approval_class", capability.approval_class],
        ["network_path", capability.network_path],
        ["supply_chain_digest", capability.supply_chain_digest],
        ["extractor_identity", capability.extractor_identity],
        ["extractor_digest", capability.extractor_digest],
        ["max_target_requests", capability.max_target_requests],
        ["max_deadline_seconds", capability.max_deadline_seconds],
    ]


def _binding_digest(
    admission_result: AdmissionResult, capability: CapabilityAdmissionSnapshot
) -> str:
    preimage = _binding_preimage(admission_result, capability)
    return sha256_hex(f"{_BINDING_DIGEST_DOMAIN}\x00{canonical_json(preimage)}")


class AdmissionRuntimeBinding(BaseModel):
    """Frozen, strict, digest-bound seal of the exact admitted capability pair.

    Carries the exact ``AdmissionResult`` v1 and the exact ``CapabilityAdmissionSnapshot`` evaluated
    together, plus a deterministic ``binding_digest`` over both. It is non-executable: it grants no
    ALLOW, decision, lease, work order, executable token, capability activation, or target effect.

    Production is single-sourced: the only public producer is ``evaluate_admission_for_runtime``,
    which evaluates admission from the exact capability, so a binding obtained through it carries a
    pair that was genuinely evaluated together. The digest binds every capability field, giving
    tamper-evidence; the coherence check rejects a pair that disagrees on the four registry-identity
    fields ``AdmissionResult`` v1 records. What the binding does not, and within this slice cannot,
    provide is caller authentication: ``AdmissionResult`` v1 does not carry ``approval_class``,
    ``network_path``, ``risk_class``, or the identity tier, so the contract cannot re-derive them,
    and this slice adds no signature, MAC, or ledger anchor (see LEDGER-GAP-001). Proving that an
    authenticated caller did not assemble a coherent-but-weaker pair is therefore deferred to later
    ledger provenance work. M1.4b2b-B must obtain this binding from
    ``evaluate_admission_for_runtime`` and must not accept a separately supplied capability.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_name: Literal["policy.admission.runtime_binding"]
    schema_version: SchemaVersionOne
    admission_result: AdmissionResult
    capability: CapabilityAdmissionSnapshot
    binding_digest: HexDigest

    @model_validator(mode="after")
    def _check_coherence_and_digest(self) -> AdmissionRuntimeBinding:
        for field in _CORE_FIELDS:
            if getattr(self.admission_result, field) != getattr(self.capability, field):
                raise ValueError(f"nested admission and capability disagree on {field}")
        if self.binding_digest != _binding_digest(self.admission_result, self.capability):
            raise ValueError("binding_digest does not bind the sealed admission and capability")
        return self


def _seal_binding(
    admission_result: AdmissionResult, capability: CapabilityAdmissionSnapshot
) -> AdmissionRuntimeBinding:
    # Private: the only caller is evaluate_admission_for_runtime, so admission code owns production
    # of the binding. There is deliberately no public constructor that seals an arbitrary
    # result/capability pair.
    return AdmissionRuntimeBinding.model_validate(
        {
            "schema_name": ADMISSION_RUNTIME_BINDING_SCHEMA,
            "schema_version": ADMISSION_RUNTIME_BINDING_SCHEMA_VERSION,
            "admission_result": admission_result,
            "capability": capability,
            "binding_digest": _binding_digest(admission_result, capability),
        }
    )


def evaluate_admission_for_runtime(  # noqa: PLR0913 - mirrors evaluate_admission's five snapshots
    proposal: ActionProposal,
    *,
    policy: EngagementPolicySnapshot,
    identity: TargetIdentitySnapshot,
    capability: CapabilityAdmissionSnapshot,
    manifest: DestinationManifest,
    evaluated_at: datetime,
) -> AdmissionRuntimeBinding:
    """Run admission against the exact capability and seal the exact pair for the runtime stage.

    The entire admission-policy decision is delegated to ``evaluate_admission``; this function adds
    no check and reinterprets none. It binds the exact ``AdmissionResult`` that evaluator returns to
    the exact ``capability`` that produced it, so the runtime stage receives the capability only as
    part of this immutable pair.
    """
    admission_result = evaluate_admission(
        proposal,
        policy=policy,
        identity=identity,
        capability=capability,
        manifest=manifest,
        evaluated_at=evaluated_at,
    )
    return _seal_binding(admission_result, capability)
