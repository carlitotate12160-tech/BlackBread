"""Pure deterministic policy-admission evaluation for M1.4b1b."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType

from blackbread.conductor.contracts import ActionProposal, TargetReference
from blackbread.policy.admission_contracts import (
    AdmissionDenyReason,
    AdmissionResult,
    CapabilityAdmissionSnapshot,
    DestinationManifest,
    EngagementPolicySnapshot,
    TargetIdentitySnapshot,
    parameter_digest,
)

_ELIGIBLE_LIFECYCLES = frozenset(
    {
        "CLIENT_ELIGIBLE",
        "EXACT_TARGET_APPROVED",
        "FIELD_OBSERVED",
        "FIELD_PROVEN",
        "REPEATABLE",
    }
)
_TIER_ORDER: MappingProxyType[str, int] = MappingProxyType({"T0": 0, "T1": 1, "T2": 2, "T3": 3})
_PROFILES: MappingProxyType[str, tuple[str, str, str]] = MappingProxyType(
    {
        "PASSIVE": ("T0", "AUTO_WITH_MANIFEST", "CONTROL_PLANE_PASSIVE"),
        "ACTIVE_READ_ONLY": ("T1", "LEASE", "TARGET_EGRESS"),
        "SENSITIVE_OFFLINE": ("T0", "OPERATOR_DATA_APPROVAL", "NONE"),
        "AUTHENTICATION": ("T2", "OPERATOR_EXACT", "TARGET_EGRESS"),
        "ACTIVE_SENSITIVE_READ": ("T2", "OPERATOR_EXACT", "TARGET_EGRESS"),
        "EXPLOIT": ("T3", "EXACT_TARGET_AND_CAPABILITY", "TARGET_EGRESS"),
        "POST_ACCESS": ("T3", "SEPARATE_OBJECTIVE", "TARGET_EGRESS"),
    }
)


class AdmissionEvaluationError(ValueError):
    """Typed fail-closed failure for invalid evaluator arguments."""


@dataclass(frozen=True)
class _Context:
    proposal: ActionProposal
    policy: EngagementPolicySnapshot
    identity: TargetIdentitySnapshot
    capability: CapabilityAdmissionSnapshot
    manifest: DestinationManifest
    evaluated_at: datetime


_Check = tuple[AdmissionDenyReason, bool]


def _early_checks(context: _Context) -> tuple[_Check, ...]:
    proposal = context.proposal
    policy = context.policy
    identity = context.identity
    manifest = context.manifest
    return (
        ("PROPOSAL_NOT_YET_VALID", context.evaluated_at < proposal.created_at),
        ("PROPOSAL_EXPIRED", context.evaluated_at >= proposal.expires_at),
        ("POLICY_NOT_YET_VALID", context.evaluated_at < policy.valid_from),
        ("POLICY_EXPIRED", context.evaluated_at >= policy.valid_until),
        (
            "TENANT_MISMATCH",
            policy.tenant_id != proposal.tenant_id or identity.tenant_id != proposal.tenant_id,
        ),
        (
            "ENGAGEMENT_MISMATCH",
            policy.engagement_id != proposal.engagement_id
            or identity.engagement_id != proposal.engagement_id,
        ),
        (
            "PROPOSAL_BINDING_MISMATCH",
            identity.proposal_digest != proposal.proposal_digest
            or manifest.proposal_digest != proposal.proposal_digest,
        ),
        (
            "GRAPH_BINDING_MISMATCH",
            policy.graph_version != proposal.graph_version
            or identity.graph_version != proposal.graph_version,
        ),
    )


def _capability_checks(context: _Context) -> tuple[_Check, ...]:
    proposal = context.proposal
    capability = context.capability
    manifest = context.manifest
    schema = proposal.parameter_envelope.input_schema_ref
    profile = (
        capability.required_identity_tier,
        capability.approval_class,
        capability.network_path,
    )
    parameter = parameter_digest(proposal.parameter_envelope.canonical_parameters)
    return (
        (
            "CAPABILITY_NOT_ALLOWED",
            proposal.capability_id not in context.policy.allowed_capability_ids,
        ),
        (
            "CAPABILITY_BINDING_MISMATCH",
            capability.capability_id != proposal.capability_id
            or manifest.capability_id != proposal.capability_id,
        ),
        ("CAPABILITY_LIFECYCLE_DENIED", capability.lifecycle not in _ELIGIBLE_LIFECYCLES),
        ("CAPABILITY_OWNER_MISMATCH", capability.owner_agent != proposal.agent_role),
        (
            "CAPABILITY_SCHEMA_MISMATCH",
            capability.input_schema != schema or manifest.input_schema != schema,
        ),
        ("CAPABILITY_PROFILE_MISMATCH", _PROFILES.get(capability.risk_class) != profile),
        (
            "EXTRACTOR_BINDING_MISMATCH",
            manifest.extractor_identity != capability.extractor_identity
            or manifest.extractor_digest != capability.extractor_digest,
        ),
        ("PARAMETER_BINDING_MISMATCH", manifest.parameter_digest != parameter),
    )


def _contains(authority: TargetReference, candidate: TargetReference) -> bool:
    if authority.target_kind == candidate.target_kind:
        return authority.canonical_value == candidate.canonical_value
    if authority.target_kind != "root_domain" or candidate.target_kind != "exact_host":
        return False
    root = authority.canonical_value
    host = candidate.canonical_value
    return host == root or host.endswith(f".{root}")


def _matches_any(candidate: TargetReference, authorities: tuple[TargetReference, ...]) -> bool:
    return any(_contains(authority, candidate) for authority in authorities)


def _overlaps(left: TargetReference, right: TargetReference) -> bool:
    # Exclusions are boundaries in both directions: a broad scope that contains a
    # narrower excluded host must be denied, and vice versa.
    return _contains(left, right) or _contains(right, left)


def _overlaps_any(candidate: TargetReference, authorities: tuple[TargetReference, ...]) -> bool:
    return any(_overlaps(candidate, authority) for authority in authorities)


def _late_checks(context: _Context) -> tuple[_Check, ...]:
    proposal = context.proposal
    identity = context.identity
    capability = context.capability
    destinations = context.manifest.destinations
    requested = proposal.requested_budget
    achieved = _TIER_ORDER[identity.achieved_tier]
    proposal_tier = _TIER_ORDER[proposal.target_identity_tier]
    capability_tier = _TIER_ORDER[capability.required_identity_tier]
    has_primary_target = any(
        item.destination_kind == "primary" and item.scope == proposal.target
        for item in destinations
    )
    egress_invalid = (capability.network_path == "TARGET_EGRESS" and not has_primary_target) or (
        capability.network_path != "TARGET_EGRESS"
        and (requested.target_requests != 0 or bool(destinations))
    )
    destination_excluded = any(
        _overlaps_any(item.scope, context.policy.scope_exclusions) for item in destinations
    )
    destination_outside = any(
        not _matches_any(item.scope, context.policy.scope_allow) for item in destinations
    )
    budget_exceeded = (
        requested.target_requests > capability.max_target_requests
        or requested.deadline_seconds > capability.max_deadline_seconds
    )
    return (
        ("TARGET_IDENTITY_MISMATCH", identity.target != proposal.target),
        ("TARGET_IDENTITY_NOT_YET_VALID", context.evaluated_at < identity.verified_at),
        ("TARGET_IDENTITY_EXPIRED", context.evaluated_at >= identity.expires_at),
        ("IDENTITY_TIER_INSUFFICIENT", achieved < proposal_tier or achieved < capability_tier),
        ("TARGET_EXCLUDED", _overlaps_any(proposal.target, context.policy.scope_exclusions)),
        ("TARGET_OUT_OF_SCOPE", not _matches_any(proposal.target, context.policy.scope_allow)),
        ("TARGET_EGRESS_DESTINATION_REQUIRED", egress_invalid),
        ("DESTINATION_EXCLUDED", destination_excluded),
        ("DESTINATION_OUT_OF_SCOPE", destination_outside),
        ("STRUCTURAL_BUDGET_EXCEEDED", budget_exceeded),
    )


def _validate_arguments(context: _Context) -> None:
    expected = (
        (context.proposal, ActionProposal),
        (context.policy, EngagementPolicySnapshot),
        (context.identity, TargetIdentitySnapshot),
        (context.capability, CapabilityAdmissionSnapshot),
        (context.manifest, DestinationManifest),
        (context.evaluated_at, datetime),
    )
    if any(not isinstance(value, kind) for value, kind in expected):
        raise AdmissionEvaluationError("evaluation arguments failed validation")
    if context.evaluated_at.tzinfo is None or context.evaluated_at.utcoffset() != timedelta(0):
        raise AdmissionEvaluationError("evaluation arguments failed validation")


def _result(context: _Context, reason: AdmissionDenyReason | None) -> AdmissionResult:
    proposal = context.proposal
    policy = context.policy
    identity = context.identity
    capability = context.capability
    manifest = context.manifest
    fields: dict[str, object] = {
        "schema_name": "policy.admission.result",
        "schema_version": 1,
        "tenant_id": proposal.tenant_id,
        "engagement_id": proposal.engagement_id,
        "proposal_id": proposal.proposal_id,
        "proposal_digest": proposal.proposal_digest,
        "policy_schema_ref": policy.policy_schema_ref,
        "policy_digest": policy.policy_digest,
        "attestation_digest": policy.attestation_digest,
        "identity_verifier_ref": identity.verifier_ref,
        "identity_evidence_digest": identity.evidence_digest,
        "registry_schema_version": capability.registry_schema_version,
        "registry_digest": capability.registry_digest,
        "capability_id": capability.capability_id,
        "supply_chain_digest": capability.supply_chain_digest,
        "extractor_identity": manifest.extractor_identity,
        "extractor_digest": manifest.extractor_digest,
        "parameter_digest": manifest.parameter_digest,
        "graph_version": proposal.graph_version,
        "evaluated_at": context.evaluated_at,
        "outcome": "DENY" if reason is not None else "ADMITTED_FOR_RUNTIME_GATES",
        "reason_code": reason,
    }
    return AdmissionResult.build(fields)


def evaluate_admission(  # noqa: PLR0913 - the public contract binds five independent snapshots
    proposal: ActionProposal,
    *,
    policy: EngagementPolicySnapshot,
    identity: TargetIdentitySnapshot,
    capability: CapabilityAdmissionSnapshot,
    manifest: DestinationManifest,
    evaluated_at: datetime,
) -> AdmissionResult:
    """Evaluate immutable verified facts in fixed fail-closed precedence."""
    context = _Context(proposal, policy, identity, capability, manifest, evaluated_at)
    _validate_arguments(context)
    checks = (*_early_checks(context), *_capability_checks(context), *_late_checks(context))
    reason = next((code for code, denied in checks if denied), None)
    return _result(context, reason)
