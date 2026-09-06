from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from blackbread.conductor.contracts import ActionProposal
from blackbread.policy.admission import evaluate_admission
from blackbread.policy.admission_contracts import (
    AdmissionResult,
    CapabilityAdmissionSnapshot,
    DestinationManifest,
)
from blackbread.policy.runtime_contracts import RuntimeGateSnapshot
from tests.conductor._builders import make_proposal
from tests.policy._builders import capability_snapshot, identity_snapshot, manifest, policy_snapshot

HEX_APPROVAL = "a" * 64
HEX_BUDGET = "c" * 64
HEX_LOCK = "d" * 64
HEX_RUN = "e" * 64
HEX_OPSEC = "f" * 64

TENANT = "tenant-a"
ENGAGEMENT = uuid.UUID("22222222-2222-2222-2222-222222222222")
AGENT = uuid.UUID("33333333-3333-3333-3333-333333333333")
PROPOSAL = uuid.UUID("11111111-1111-1111-1111-111111111111")
CAPABILITY = "scout.passive_asset_intelligence.v1"
APPROVER = "operator-alice"


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 3, hour, minute, tzinfo=UTC)


def _target() -> dict[str, str]:
    return {"target_kind": "root_domain", "canonical_value": "example.com"}


def _grant(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "schema_name": "policy.runtime.approval_grant",
        "schema_version": 1,
        "tenant_id": TENANT,
        "engagement_id": ENGAGEMENT,
        "proposal_id": PROPOSAL,
        "proposal_digest": make_proposal().proposal_digest,
        "admission_result_digest": "1" * 64,
        "capability_id": CAPABILITY,
        "target": _target(),
        "approval_class": "AUTO_WITH_MANIFEST",
        "approver_identity": APPROVER,
        "grant_ref": "approval-grant-001",
        "grant_digest": HEX_APPROVAL,
        "valid_from": _ts(11, 0),
        "valid_until": _ts(13, 0),
        "revocation_ref": None,
        "revocation_timestamp": None,
        "revocation_digest": None,
        "objective_ref": None,
        "objective_binding_digest": None,
    }
    fields.update(overrides)
    return fields


def _account(agent: uuid.UUID | None = None, **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "schema_name": "policy.runtime.budget_account",
        "schema_version": 1,
        "tenant_id": TENANT,
        "engagement_id": ENGAGEMENT,
        "agent_instance_id": agent,
        "provenance_ref": "budget-ledger-001",
        "provenance_digest": HEX_BUDGET,
        "revision": 1,
        "request_limit": 10,
        "cost_microunit_limit": 1_000_000,
        "consumed_requests": 0,
        "consumed_microunits": 0,
        "reserved_requests": 0,
        "reserved_microunits": 0,
        "hard_stop_until": _ts(14, 0),
    }
    fields.update(overrides)
    return fields


def _budget(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "schema_name": "policy.runtime.budget",
        "schema_version": 1,
        "tenant_id": TENANT,
        "engagement_id": ENGAGEMENT,
        "agent_instance_id": AGENT,
        "engagement_account": _account(agent=None),
        "agent_account": _account(agent=AGENT),
    }
    fields.update(overrides)
    return fields


def _lock(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "schema_name": "policy.runtime.resource_lock",
        "schema_version": 1,
        "tenant_id": TENANT,
        "engagement_id": ENGAGEMENT,
        "provenance_ref": "lock-ledger-001",
        "provenance_digest": HEX_LOCK,
        "revision": 1,
        "holder": None,
    }
    fields.update(overrides)
    return fields


def _held(holder: uuid.UUID, expires_at: datetime, **overrides: Any) -> dict[str, Any]:
    return {
        "schema_name": "policy.runtime.held_lock",
        "schema_version": 1,
        "holder_proposal_id": holder,
        "holder_lease_id": None,
        "acquired_at": _ts(11, 0),
        "expires_at": expires_at,
        **overrides,
    }


def _run(state: str = "ACTIVE", **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "schema_name": "policy.runtime.engagement_run",
        "schema_version": 1,
        "tenant_id": TENANT,
        "engagement_id": ENGAGEMENT,
        "state": state,
        "provenance_ref": "run-ledger-001",
        "provenance_digest": HEX_RUN,
        "transitioned_at": _ts(11, 0),
        "stopped_reason_ref": None,
        "stopped_reason_digest": None,
    }
    if state == "STOPPED":
        fields["stopped_reason_ref"] = "stop-reason-001"
        fields["stopped_reason_digest"] = HEX_RUN
    fields.update(overrides)
    return fields


def _opsec(state: str = "COOL", **overrides: Any) -> dict[str, Any]:
    return {
        "schema_name": "policy.runtime.opsec",
        "schema_version": 1,
        "tenant_id": TENANT,
        "engagement_id": ENGAGEMENT,
        "state": state,
        "provenance_ref": "opsec-ledger-001",
        "provenance_digest": HEX_OPSEC,
        "observed_at": _ts(11, 30),
        "fresh_until": _ts(12, 30),
        **overrides,
    }


def _gate(**overrides: Any) -> dict[str, Any]:
    proposal = make_proposal()
    captured = _ts(11, 30)
    return {
        "schema_name": "policy.runtime.gate",
        "schema_version": 1,
        "tenant_id": TENANT,
        "engagement_id": ENGAGEMENT,
        "proposal_id": proposal.proposal_id,
        "proposal_digest": proposal.proposal_digest,
        "admission_result_digest": "1" * 64,
        "capability_id": CAPABILITY,
        "agent_instance_id": proposal.agent_instance_id,
        "captured_at": captured,
        "fresh_until": captured + timedelta(minutes=30),
        "approval_grant": None,
        "budget": None,
        "lock": None,
        "engagement": None,
        "opsec": None,
        **overrides,
    }


def admitted_context(
    proposal: ActionProposal | None = None,
    capability: CapabilityAdmissionSnapshot | None = None,
    destination_manifest: DestinationManifest | None = None,
    evaluated_at: datetime | None = None,
) -> tuple[ActionProposal, CapabilityAdmissionSnapshot, AdmissionResult]:
    proposal = make_proposal() if proposal is None else proposal
    capability = capability_snapshot() if capability is None else capability
    destination_manifest = (
        manifest(proposal) if destination_manifest is None else destination_manifest
    )
    evaluated_at = _ts(12, 1) if evaluated_at is None else evaluated_at
    admission = evaluate_admission(
        proposal,
        policy=policy_snapshot(graph_version=proposal.graph_version),
        identity=identity_snapshot(proposal, achieved_tier=proposal.target_identity_tier),
        capability=capability,
        manifest=destination_manifest,
        evaluated_at=evaluated_at,
    )
    return proposal, capability, admission


def runtime_snapshot(
    proposal: ActionProposal,
    admission: AdmissionResult,
    **overrides: Any,
) -> RuntimeGateSnapshot:
    captured = _ts(12, 2)
    budget = _budget(
        engagement_account=_account(cost_microunit_limit=10_000_000),
        agent_account=_account(agent=proposal.agent_instance_id, cost_microunit_limit=10_000_000),
    )
    fields = _gate(
        tenant_id=proposal.tenant_id,
        engagement_id=proposal.engagement_id,
        proposal_id=proposal.proposal_id,
        proposal_digest=proposal.proposal_digest,
        admission_result_digest=admission.result_digest,
        capability_id=proposal.capability_id,
        agent_instance_id=proposal.agent_instance_id,
        captured_at=captured,
        fresh_until=_ts(12, 10),
        budget=budget,
        lock=_lock(),
        engagement=_run(),
        opsec=_opsec(),
    )
    fields.update(overrides)
    return RuntimeGateSnapshot.build(fields)
