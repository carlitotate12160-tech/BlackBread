"""Immutable, strict, versioned policy-admission contract validation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from blackbread.conductor.contracts import TargetReference
from blackbread.policy.admission_contracts import (
    ADMISSION_SCHEMA,
    ADMISSION_SCHEMA_VERSION,
    CapabilityAdmissionSnapshot,
    DestinationManifest,
    EngagementPolicySnapshot,
    ScopedDestination,
)
from tests.conductor._builders import make_proposal
from tests.policy._builders import (
    capability_snapshot,
    egress_destination,
    identity_snapshot,
    manifest,
    policy_snapshot,
    target,
)


def test_schema_identity_is_versioned() -> None:
    assert ADMISSION_SCHEMA == "policy.admission"
    assert ADMISSION_SCHEMA_VERSION == 1


def test_snapshots_are_frozen() -> None:
    snapshot = policy_snapshot()
    with pytest.raises(ValidationError):
        snapshot.tenant_id = "tenant-z"  # type: ignore[misc]


def test_policy_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        EngagementPolicySnapshot(**{**_policy_kwargs(), "unexpected": 1})


def test_policy_rejects_inverted_validity_interval() -> None:
    with pytest.raises(ValidationError):
        policy_snapshot(
            valid_from=datetime(2026, 9, 3, 13, 0, tzinfo=UTC),
            valid_until=datetime(2026, 9, 3, 11, 0, tzinfo=UTC),
        )


def test_policy_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        policy_snapshot(valid_from=datetime(2026, 9, 3, 11, 0))


def test_policy_requires_at_least_one_scope_allow() -> None:
    with pytest.raises(ValidationError):
        policy_snapshot(scope_allow=())


def test_policy_rejects_duplicate_capability_ids() -> None:
    with pytest.raises(ValidationError):
        policy_snapshot(
            allowed_capability_ids=(
                "scout.passive_asset_intelligence.v1",
                "scout.passive_asset_intelligence.v1",
            )
        )


def test_identity_rejects_inverted_validity() -> None:
    proposal = make_proposal()
    with pytest.raises(ValidationError):
        identity_snapshot(
            proposal,
            verified_at=datetime(2026, 9, 3, 12, 30, tzinfo=UTC),
            expires_at=datetime(2026, 9, 3, 11, 0, tzinfo=UTC),
        )


def test_capability_lifecycle_vocabulary_is_closed() -> None:
    with pytest.raises(ValidationError):
        capability_snapshot(lifecycle="ACTIVE")


def test_capability_network_path_vocabulary_is_closed() -> None:
    with pytest.raises(ValidationError):
        capability_snapshot(network_path="INTERNAL")


def test_destination_kind_vocabulary_is_closed() -> None:
    with pytest.raises(ValidationError):
        ScopedDestination(destination_kind="tunnel", scope=target())


def test_destination_scope_reuses_canonical_target_authority() -> None:
    with pytest.raises(ValidationError):
        ScopedDestination(
            destination_kind="primary",
            scope=TargetReference(target_kind="exact_host", canonical_value="Bad_Host"),
        )


def test_manifest_rejects_duplicate_destinations() -> None:
    proposal = make_proposal()
    with pytest.raises(ValidationError):
        manifest(
            proposal,
            destinations=(egress_destination("a.example.com"), egress_destination("a.example.com")),
        )


def test_manifest_bounds_destination_count() -> None:
    proposal = make_proposal()
    many = tuple(egress_destination(f"h{index}.example.com") for index in range(300))
    with pytest.raises(ValidationError):
        manifest(proposal, destinations=many)


def test_snapshots_reuse_shared_target_reference_type() -> None:
    assert isinstance(policy_snapshot().scope_allow[0], TargetReference)
    assert isinstance(identity_snapshot(make_proposal()).target, TargetReference)
    assert isinstance(egress_destination().scope, TargetReference)


def _policy_kwargs() -> dict[str, object]:
    return {
        "tenant_id": "tenant-a",
        "engagement_id": policy_snapshot().engagement_id,
        "policy_schema": "EngagementPolicy.v1",
        "policy_version": 1,
        "policy_digest": "1" * 64,
        "attestation_ref": "attestation-eng-001",
        "attestation_digest": "2" * 64,
        "valid_from": datetime(2026, 9, 3, 11, 0, tzinfo=UTC),
        "valid_until": datetime(2026, 9, 3, 13, 0, tzinfo=UTC),
        "scope_allow": (target(),),
        "scope_exclusions": (),
        "allowed_capability_ids": ("scout.passive_asset_intelligence.v1",),
        "graph_version": policy_snapshot().graph_version,
    }


def test_capability_snapshot_binds_structural_ceilings() -> None:
    snapshot = capability_snapshot(max_target_requests=4, max_deadline_seconds=60)
    assert snapshot.max_target_requests == 4
    assert snapshot.max_deadline_seconds == 60
    assert isinstance(snapshot, CapabilityAdmissionSnapshot)


def test_manifest_binds_extractor_and_parameter_digest() -> None:
    built = manifest(make_proposal())
    assert isinstance(built, DestinationManifest)
    assert len(built.parameter_digest) == 64
    assert len(built.extractor_digest) == 64
