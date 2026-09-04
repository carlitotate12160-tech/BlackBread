"""Shared valid-input builders for policy-admission input-contract tests (M1.4b1a)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from blackbread.conductor.contracts import ActionProposal, TargetReference
from blackbread.policy.admission_contracts import (
    CapabilityAdmissionSnapshot,
    DestinationManifest,
    EngagementPolicySnapshot,
    ScopedDestination,
    TargetIdentitySnapshot,
    parameter_digest,
)
from tests.conductor._builders import graph_version, make_proposal

HEX_P = "1" * 64
HEX_ATTEST = "2" * 64
HEX_REGISTRY = "3" * 64
HEX_SUPPLY = "4" * 64
HEX_EXTRACTOR = "5" * 64
HEX_EVIDENCE = "6" * 64
EXTRACTOR = "blackbread.extractors.passive_asset_intelligence.v1"

TENANT = "tenant-a"
ENGAGEMENT = uuid.UUID("22222222-2222-2222-2222-222222222222")
CAPABILITY = "scout.passive_asset_intelligence.v1"
INPUT_SCHEMA = "PassiveAssetIntelligenceInput.v1"


def target(**overrides: Any) -> TargetReference:
    fields: dict[str, Any] = {"target_kind": "root_domain", "canonical_value": "example.com"}
    fields.update(overrides)
    return TargetReference(**fields)


def policy_snapshot(**overrides: Any) -> EngagementPolicySnapshot:
    fields: dict[str, Any] = {
        "tenant_id": TENANT,
        "engagement_id": ENGAGEMENT,
        "policy_schema": "EngagementPolicy.v1",
        "policy_version": 1,
        "policy_digest": HEX_P,
        "attestation_ref": "attestation-eng-001",
        "attestation_digest": HEX_ATTEST,
        "valid_from": datetime(2026, 9, 3, 11, 0, 0, tzinfo=UTC),
        "valid_until": datetime(2026, 9, 3, 13, 0, 0, tzinfo=UTC),
        "scope_allow": (target(),),
        "scope_exclusions": (),
        "allowed_capability_ids": (CAPABILITY,),
        "graph_version": graph_version(),
    }
    fields.update(overrides)
    return EngagementPolicySnapshot(**fields)


def identity_snapshot(proposal: ActionProposal, **overrides: Any) -> TargetIdentitySnapshot:
    fields: dict[str, Any] = {
        "tenant_id": TENANT,
        "engagement_id": ENGAGEMENT,
        "proposal_digest": proposal.proposal_digest,
        "target": target(),
        "achieved_tier": "T0",
        "verified_at": datetime(2026, 9, 3, 11, 55, 0, tzinfo=UTC),
        "expires_at": datetime(2026, 9, 3, 12, 30, 0, tzinfo=UTC),
        "graph_version": graph_version(),
        "verifier_ref": "identity-verifier-observation",
        "evidence_digest": HEX_EVIDENCE,
    }
    fields.update(overrides)
    return TargetIdentitySnapshot(**fields)


def capability_snapshot(**overrides: Any) -> CapabilityAdmissionSnapshot:
    fields: dict[str, Any] = {
        "registry_schema_version": 1,
        "registry_digest": HEX_REGISTRY,
        "capability_id": CAPABILITY,
        "owner_agent": "Scout",
        "lifecycle": "CLIENT_ELIGIBLE",
        "input_schema": INPUT_SCHEMA,
        "risk_class": "PASSIVE",
        "required_identity_tier": "T0",
        "approval_class": "AUTO_WITH_MANIFEST",
        "network_path": "CONTROL_PLANE_PASSIVE",
        "supply_chain_digest": HEX_SUPPLY,
        "extractor_identity": EXTRACTOR,
        "extractor_digest": HEX_EXTRACTOR,
        "max_target_requests": 0,
        "max_deadline_seconds": 30,
    }
    fields.update(overrides)
    return CapabilityAdmissionSnapshot(**fields)


def manifest(proposal: ActionProposal, **overrides: Any) -> DestinationManifest:
    fields: dict[str, Any] = {
        "proposal_digest": proposal.proposal_digest,
        "parameter_digest": parameter_digest(proposal.parameter_envelope.canonical_parameters),
        "input_schema": INPUT_SCHEMA,
        "capability_id": CAPABILITY,
        "extractor_identity": EXTRACTOR,
        "extractor_digest": HEX_EXTRACTOR,
        "destinations": (),
    }
    fields.update(overrides)
    return DestinationManifest(**fields)


def egress_destination(value: str = "app.example.com") -> ScopedDestination:
    return ScopedDestination(
        destination_kind="primary",
        scope=TargetReference(target_kind="exact_host", canonical_value=value),
    )


__all__ = [
    "CAPABILITY",
    "EXTRACTOR",
    "capability_snapshot",
    "egress_destination",
    "identity_snapshot",
    "make_proposal",
    "manifest",
    "policy_snapshot",
    "target",
]
