"""Immutable, versioned, unwired runtime-gate input-fact contracts (M1.4b2a)."""

from __future__ import annotations

import copy
import json
import uuid

import pytest
from pydantic import ValidationError

from blackbread.policy.runtime_contracts import (
    RUNTIME_GATE_SCHEMA,
    RUNTIME_GATE_SCHEMA_VERSION,
    ApprovalGrantSnapshot,
    EngagementRunStateSnapshot,
    HeldEngagementLock,
    OpsecStateSnapshot,
    ResourceLockSnapshot,
    RuntimeBudgetSnapshot,
    RuntimeGateSnapshot,
)
from tests.policy._runtime_builders import (
    AGENT,
    CAPABILITY,
    HEX_APPROVAL,
    HEX_BUDGET,
    HEX_RUN,
    PROPOSAL,
    TENANT,
    _account,
    _budget,
    _gate,
    _grant,
    _lock,
    _opsec,
    _run,
    _ts,
)

HEX_OBJECTIVE = "0" * 64

GOLDEN_GATE_DIGEST = "7013ce31a01206a44bdfb9629b3c15653412df7f70e6a4bf451947bbb3918132"


def _built(**overrides: object) -> RuntimeGateSnapshot:
    return RuntimeGateSnapshot.build(_gate(**overrides))


def _nested_gate() -> dict[str, object]:
    return _gate(
        approval_grant=_grant(),
        budget=_budget(),
        lock=_lock(),
        engagement=_run(),
        opsec=_opsec(),
    )


def test_runtime_contracts_are_version_one_schema() -> None:
    assert RUNTIME_GATE_SCHEMA == "policy.runtime.gate"
    assert RUNTIME_GATE_SCHEMA_VERSION == 1


def test_runtime_gate_snapshot_is_frozen_and_strict() -> None:
    gate = _built()
    with pytest.raises(ValidationError):
        gate.tenant_id = "tenant-z"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        RuntimeGateSnapshot.build({**_gate(), "unexpected": 1})


def test_runtime_gate_snapshot_rejects_cross_boundary_substitution() -> None:
    base = _nested_gate()

    def mutate(path: str, value: object) -> dict[str, object]:
        result = copy.deepcopy(base)
        keys = path.split(".")
        target: dict[str, object] = result
        for key in keys[:-1]:
            target = target[key]  # type: ignore[assignment]
        target[keys[-1]] = value
        return result

    other_tenant = "tenant-z"
    other_engagement = uuid.UUID("33333333-3333-3333-3333-333333333333")
    other_agent = uuid.UUID("44444444-4444-4444-4444-444444444444")

    for path in (
        "approval_grant.tenant_id",
        "budget.tenant_id",
        "budget.engagement_account.tenant_id",
        "lock.tenant_id",
        "engagement.tenant_id",
        "opsec.tenant_id",
    ):
        with pytest.raises(ValidationError, match="tenant"):
            RuntimeGateSnapshot.build(mutate(path, other_tenant))

    for path in (
        "approval_grant.engagement_id",
        "budget.engagement_id",
        "budget.engagement_account.engagement_id",
        "lock.engagement_id",
        "engagement.engagement_id",
        "opsec.engagement_id",
    ):
        with pytest.raises(ValidationError, match="engagement"):
            RuntimeGateSnapshot.build(mutate(path, other_engagement))

    with pytest.raises(ValidationError, match="agent"):
        RuntimeGateSnapshot.build(mutate("budget.agent_instance_id", other_agent))

    with pytest.raises(ValidationError, match="proposal"):
        RuntimeGateSnapshot.build(mutate("approval_grant.proposal_id", other_agent))

    with pytest.raises(ValidationError, match="admission"):
        RuntimeGateSnapshot.build(mutate("approval_grant.admission_result_digest", "2" * 64))

    with pytest.raises(ValidationError, match="capability"):
        RuntimeGateSnapshot.build(mutate("approval_grant.capability_id", "other.v1"))

    with pytest.raises(ValidationError):
        RuntimeGateSnapshot.build({**base, "unknown_field": 1})

    with pytest.raises(ValidationError):
        RuntimeGateSnapshot.build(
            {key: value for key, value in base.items() if key != "schema_name"}
        )


def test_runtime_gate_snapshot_digest_golden_vector_and_tamper_rejection() -> None:
    gate = _built(**_nested_gate())
    assert gate.snapshot_digest == GOLDEN_GATE_DIGEST

    changed = _built(**_nested_gate()).model_dump()
    changed["opsec"]["state"] = "WARM"
    resealed = RuntimeGateSnapshot.build(
        {key: value for key, value in changed.items() if key != "snapshot_digest"}
    )
    assert resealed.snapshot_digest != gate.snapshot_digest

    restored = RuntimeGateSnapshot.model_validate_json(gate.model_dump_json())
    assert restored == gate
    assert restored.snapshot_digest == gate.snapshot_digest

    payload = json.loads(gate.model_dump_json())
    payload["snapshot_digest"] = "9" * 64
    with pytest.raises(ValidationError, match="snapshot_digest does not bind"):
        RuntimeGateSnapshot.model_validate_json(json.dumps(payload))

    payload = json.loads(gate.model_dump_json())
    payload["approval_grant"]["grant_digest"] = "9" * 64
    with pytest.raises(ValidationError, match="snapshot_digest does not bind"):
        RuntimeGateSnapshot.model_validate_json(json.dumps(payload))

    with pytest.raises(ValidationError):
        RuntimeGateSnapshot.model_validate_json(
            json.dumps({**json.loads(gate.model_dump_json()), "snapshot_digest": None})
        )


def test_approval_grant_requires_exact_scope_validity_and_revocation_provenance() -> None:
    grant = ApprovalGrantSnapshot(**_grant())
    assert grant.tenant_id == TENANT
    assert grant.proposal_digest == _built().proposal_digest
    assert grant.capability_id == CAPABILITY
    assert grant.approval_class == "AUTO_WITH_MANIFEST"

    with pytest.raises(ValidationError):
        ApprovalGrantSnapshot(**_grant(valid_from=_ts(13, 0), valid_until=_ts(11, 0)))

    with pytest.raises(ValidationError):
        ApprovalGrantSnapshot(
            **_grant(
                revocation_ref="revoke-001",
                revocation_timestamp=None,
                revocation_digest=HEX_APPROVAL,
            )
        )

    with pytest.raises(ValidationError):
        ApprovalGrantSnapshot(
            **_grant(
                revocation_ref=None, revocation_timestamp=_ts(12, 0), revocation_digest=HEX_APPROVAL
            )
        )

    valid_revoke = _grant(
        revocation_ref="revoke-001",
        revocation_timestamp=_ts(12, 0),
        revocation_digest=HEX_APPROVAL,
    )
    revoked = ApprovalGrantSnapshot(**valid_revoke)
    assert revoked.revocation_ref == "revoke-001"

    with pytest.raises(ValidationError):
        ApprovalGrantSnapshot(**_grant(approval_class="SEPARATE_OBJECTIVE", objective_ref=None))

    separate = _grant(
        approval_class="SEPARATE_OBJECTIVE",
        objective_ref="objective-001",
        objective_binding_digest=HEX_OBJECTIVE,
    )
    approved = ApprovalGrantSnapshot(**separate)
    assert approved.objective_ref == "objective-001"

    with pytest.raises(ValidationError):
        ApprovalGrantSnapshot(
            **_grant(objective_ref="objective-001", objective_binding_digest=HEX_OBJECTIVE)
        )

    with pytest.raises(ValidationError):
        ApprovalGrantSnapshot(**_grant(approved=True))


def test_runtime_budget_rejects_overconsumed_or_substituted_accounts() -> None:
    budget = RuntimeBudgetSnapshot(**_budget())
    assert budget.engagement_account.provenance_digest == HEX_BUDGET
    assert budget.engagement_account.revision == 1
    assert budget.agent_account.agent_instance_id == AGENT
    assert budget.engagement_account.agent_instance_id is None

    with pytest.raises(ValidationError):
        RuntimeBudgetSnapshot(
            **_budget(engagement_account=_account(consumed_requests=8, reserved_requests=3))
        )

    with pytest.raises(ValidationError):
        RuntimeBudgetSnapshot(
            **_budget(
                engagement_account=_account(
                    consumed_microunits=900_000, reserved_microunits=150_000
                )
            )
        )

    with pytest.raises(ValidationError):
        RuntimeBudgetSnapshot(**_budget(engagement_account=_account(consumed_requests=-1)))

    with pytest.raises(ValidationError, match="tenant"):
        RuntimeBudgetSnapshot(
            **_budget(
                engagement_account=_account(tenant_id="tenant-z", agent=None),
            )
        )

    with pytest.raises(ValidationError, match="engagement"):
        RuntimeBudgetSnapshot(
            **_budget(
                agent_account=_account(
                    agent=AGENT,
                    engagement_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
                ),
            )
        )

    with pytest.raises(ValidationError, match="agent"):
        RuntimeBudgetSnapshot(
            **_budget(
                agent_account=_account(agent=uuid.UUID("44444444-4444-4444-4444-444444444444")),
            )
        )


def test_lock_run_and_opsec_states_are_closed_and_provenance_bound() -> None:
    lock = ResourceLockSnapshot(**_lock())
    assert lock.holder is None
    assert "resource_key" not in ResourceLockSnapshot.model_fields

    held = HeldEngagementLock(
        schema_name="policy.runtime.held_lock",
        schema_version=1,
        holder_proposal_id=PROPOSAL,
        holder_lease_id=None,
        acquired_at=_ts(11, 0),
        expires_at=_ts(12, 0),
    )
    held_lock = ResourceLockSnapshot(**_lock(holder=held.model_dump()))
    assert held_lock.holder is not None
    assert held_lock.holder.holder_proposal_id == PROPOSAL

    with pytest.raises(ValidationError):
        HeldEngagementLock(
            schema_name="policy.runtime.held_lock",
            schema_version=1,
            holder_proposal_id=PROPOSAL,
            holder_lease_id=None,
            acquired_at=_ts(13, 0),
            expires_at=_ts(11, 0),
        )

    with pytest.raises(ValidationError):
        EngagementRunStateSnapshot(**_run(state="PAUSED"))

    with pytest.raises(ValidationError):
        OpsecStateSnapshot(**_opsec(state="FROZEN"))

    with pytest.raises(ValidationError):
        EngagementRunStateSnapshot(
            **_run(state="ACTIVE", stopped_reason_ref="x", stopped_reason_digest=HEX_RUN)
        )

    stopped = EngagementRunStateSnapshot(**_run(state="STOPPED"))
    assert stopped.stopped_reason_ref == "stop-reason-001"

    with pytest.raises(ValidationError):
        OpsecStateSnapshot(**_opsec(observed_at=_ts(13, 0), fresh_until=_ts(11, 0)))


def test_runtime_gate_snapshot_lock_holder_states_and_tamper_rejection() -> None:
    other_proposal = uuid.UUID("44444444-4444-4444-4444-444444444444")
    other_tenant = "tenant-other"
    other_engagement = uuid.UUID("99999999-9999-9999-9999-999999999999")

    empty_gate = RuntimeGateSnapshot.build(_gate(lock=_lock(holder=None)))
    assert empty_gate.lock is not None
    assert empty_gate.lock.holder is None

    own_held = HeldEngagementLock(
        schema_name="policy.runtime.held_lock",
        schema_version=1,
        holder_proposal_id=PROPOSAL,
        holder_lease_id=None,
        acquired_at=_ts(11, 0),
        expires_at=_ts(12, 0),
    )
    own_gate = RuntimeGateSnapshot.build(_gate(lock=_lock(holder=own_held.model_dump())))
    assert own_gate.lock is not None
    assert own_gate.lock.holder is not None
    assert own_gate.lock.holder.holder_proposal_id == PROPOSAL

    other_held = HeldEngagementLock(
        schema_name="policy.runtime.held_lock",
        schema_version=1,
        holder_proposal_id=other_proposal,
        holder_lease_id=None,
        acquired_at=_ts(11, 0),
        expires_at=_ts(12, 0),
    )
    other_gate = RuntimeGateSnapshot.build(_gate(lock=_lock(holder=other_held.model_dump())))
    assert other_gate.lock is not None
    assert other_gate.lock.holder is not None
    assert other_gate.lock.holder.holder_proposal_id == other_proposal

    with pytest.raises(ValidationError, match="tenant"):
        RuntimeGateSnapshot.build(_gate(lock=_lock(tenant_id=other_tenant)))

    with pytest.raises(ValidationError, match="engagement"):
        RuntimeGateSnapshot.build(_gate(lock=_lock(engagement_id=other_engagement)))

    tampered = copy.deepcopy(empty_gate.model_dump())
    tampered["lock"]["holder"] = other_held.model_dump()
    with pytest.raises(ValidationError, match="snapshot_digest"):
        RuntimeGateSnapshot(**tampered)
