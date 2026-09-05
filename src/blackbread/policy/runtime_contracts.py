from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from blackbread.conductor.contracts import (
    CanonicalText,
    CapabilityId,
    HexDigest,
    SchemaVersionOne,
    TargetReference,
    TenantId,
    UtcTimestamp,
)
from blackbread.ledger.hashing import canonical_json, canonical_timestamp, sha256_hex
from blackbread.policy.admission_contracts import ApprovalClass

RUNTIME_GATE_SCHEMA = "policy.runtime.gate"
RUNTIME_GATE_SCHEMA_VERSION = 1

_GATE_DIGEST_DOMAIN = "blackbread.policy.runtime.gate.snapshot_digest.v1"

HeatState = Literal["COOL", "WARM", "HOT", "BURNED"]
EngagementRunState = Literal["ACTIVE", "STOPPED"]


def _require_equal(value: object, expected: object, scope: str, field: str) -> None:
    if value != expected:
        raise ValueError(f"{scope} {field} mismatch")


def _bind_object(source: object, target: object, scope: str, fields: tuple[str, ...]) -> None:
    for field in fields:
        _require_equal(getattr(source, field), getattr(target, field), scope, field)


def _canonical_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return _canonical_value(dict(value))
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return canonical_timestamp(value)
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_value(item) for key, item in value.items()}
    return value


def _runtime_gate_digest(values: Mapping[str, Any]) -> str:
    preimage = _canonical_value(dict(values))
    return sha256_hex(f"{_GATE_DIGEST_DOMAIN}\x00{canonical_json(preimage)}")


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _TenantScoped(_Frozen):
    tenant_id: TenantId
    engagement_id: UUID


class ApprovalGrantSnapshot(_TenantScoped):
    schema_name: Literal["policy.runtime.approval_grant"]
    schema_version: SchemaVersionOne
    proposal_id: UUID
    proposal_digest: HexDigest
    admission_result_digest: HexDigest
    capability_id: CapabilityId
    target: TargetReference
    approval_class: ApprovalClass
    approver_identity: CanonicalText
    grant_ref: CanonicalText
    grant_digest: HexDigest
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp
    revocation_ref: CanonicalText | None
    revocation_timestamp: UtcTimestamp | None
    revocation_digest: HexDigest | None
    objective_ref: CanonicalText | None
    objective_binding_digest: HexDigest | None

    @model_validator(mode="after")
    def _check_validity_and_coherence(self) -> ApprovalGrantSnapshot:
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be strictly after valid_from")
        revocation = (self.revocation_ref, self.revocation_timestamp, self.revocation_digest)
        if any(revocation) and not all(revocation):
            raise ValueError("revocation fields must be all present or all absent")
        is_separate = self.approval_class == "SEPARATE_OBJECTIVE"
        has_objective = self.objective_ref is not None or self.objective_binding_digest is not None
        if is_separate and not all((self.objective_ref, self.objective_binding_digest)):
            raise ValueError(
                "SEPARATE_OBJECTIVE requires objective_ref and objective_binding_digest"
            )
        if not is_separate and has_objective:
            raise ValueError("objective fields are only allowed for SEPARATE_OBJECTIVE")
        return self


class BudgetAccountSnapshot(_TenantScoped):
    schema_name: Literal["policy.runtime.budget_account"]
    schema_version: SchemaVersionOne
    agent_instance_id: UUID | None
    provenance_ref: CanonicalText
    provenance_digest: HexDigest
    revision: Annotated[int, Field(ge=0)]
    request_limit: Annotated[int, Field(ge=0)]
    cost_microunit_limit: Annotated[int, Field(ge=0)]
    consumed_requests: Annotated[int, Field(ge=0)]
    consumed_microunits: Annotated[int, Field(ge=0)]
    reserved_requests: Annotated[int, Field(ge=0)]
    reserved_microunits: Annotated[int, Field(ge=0)]
    hard_stop_until: UtcTimestamp

    @model_validator(mode="after")
    def _check_consumption(self) -> BudgetAccountSnapshot:
        if self.consumed_requests + self.reserved_requests > self.request_limit:
            raise ValueError("consumed_requests + reserved_requests exceeds request_limit")
        if self.consumed_microunits + self.reserved_microunits > self.cost_microunit_limit:
            raise ValueError(
                "consumed_microunits + reserved_microunits exceeds cost_microunit_limit"
            )
        return self


class RuntimeBudgetSnapshot(_TenantScoped):
    schema_name: Literal["policy.runtime.budget"]
    schema_version: SchemaVersionOne
    agent_instance_id: UUID
    engagement_account: BudgetAccountSnapshot
    agent_account: BudgetAccountSnapshot

    @model_validator(mode="after")
    def _check_account_binding(self) -> RuntimeBudgetSnapshot:
        for name, account in (
            ("engagement_account", self.engagement_account),
            ("agent_account", self.agent_account),
        ):
            if account.tenant_id != self.tenant_id:
                raise ValueError(f"{name} tenant_id does not match runtime budget")
            if account.engagement_id != self.engagement_id:
                raise ValueError(f"{name} engagement_id does not match runtime budget")
        if self.engagement_account.agent_instance_id is not None:
            raise ValueError("engagement_account must not carry an agent_instance_id")
        if self.agent_account.agent_instance_id != self.agent_instance_id:
            raise ValueError("agent_account agent_instance_id does not match runtime budget")
        return self


class HeldEngagementLock(_Frozen):
    schema_name: Literal["policy.runtime.held_lock"]
    schema_version: SchemaVersionOne
    holder_proposal_id: UUID
    holder_lease_id: UUID | None
    acquired_at: UtcTimestamp
    expires_at: UtcTimestamp

    @model_validator(mode="after")
    def _check_interval(self) -> HeldEngagementLock:
        if self.expires_at <= self.acquired_at:
            raise ValueError("expires_at must be strictly after acquired_at")
        return self


class ResourceLockSnapshot(_TenantScoped):
    schema_name: Literal["policy.runtime.resource_lock"]
    schema_version: SchemaVersionOne
    provenance_ref: CanonicalText
    provenance_digest: HexDigest
    revision: Annotated[int, Field(ge=0)]
    holder: HeldEngagementLock | None


class EngagementRunStateSnapshot(_TenantScoped):
    schema_name: Literal["policy.runtime.engagement_run"]
    schema_version: SchemaVersionOne
    state: EngagementRunState
    provenance_ref: CanonicalText
    provenance_digest: HexDigest
    transitioned_at: UtcTimestamp
    stopped_reason_ref: CanonicalText | None
    stopped_reason_digest: HexDigest | None

    @model_validator(mode="after")
    def _check_state_coherence(self) -> EngagementRunStateSnapshot:
        if self.state == "STOPPED":
            if not all((self.stopped_reason_ref, self.stopped_reason_digest)):
                raise ValueError(
                    "STOPPED state requires stopped_reason_ref and stopped_reason_digest"
                )
        elif any((self.stopped_reason_ref, self.stopped_reason_digest)):
            raise ValueError("ACTIVE state must not carry stopped_reason fields")
        return self


class OpsecStateSnapshot(_TenantScoped):
    schema_name: Literal["policy.runtime.opsec"]
    schema_version: SchemaVersionOne
    state: HeatState
    provenance_ref: CanonicalText
    provenance_digest: HexDigest
    observed_at: UtcTimestamp
    fresh_until: UtcTimestamp

    @model_validator(mode="after")
    def _check_freshness(self) -> OpsecStateSnapshot:
        if self.fresh_until <= self.observed_at:
            raise ValueError("fresh_until must be strictly after observed_at")
        return self


def _bind_budget(b: RuntimeBudgetSnapshot, gate: _RuntimeGateFields) -> None:
    _bind_object(b, gate, "budget", ("tenant_id", "engagement_id", "agent_instance_id"))
    for name in ("engagement_account", "agent_account"):
        account = getattr(b, name)
        _require_equal(account.tenant_id, gate.tenant_id, name, "tenant_id")
        _require_equal(account.engagement_id, gate.engagement_id, name, "engagement_id")
    if b.engagement_account.agent_instance_id is not None:
        raise ValueError("engagement_account must not carry an agent_instance_id")
    _require_equal(
        b.agent_account.agent_instance_id,
        gate.agent_instance_id,
        "agent_account",
        "agent_instance_id",
    )


class _RuntimeGateFields(_TenantScoped):
    schema_name: Literal["policy.runtime.gate"]
    schema_version: SchemaVersionOne
    proposal_id: UUID
    proposal_digest: HexDigest
    admission_result_digest: HexDigest
    capability_id: CapabilityId
    agent_instance_id: UUID
    captured_at: UtcTimestamp
    fresh_until: UtcTimestamp
    approval_grant: ApprovalGrantSnapshot | None
    budget: RuntimeBudgetSnapshot | None
    lock: ResourceLockSnapshot | None
    engagement: EngagementRunStateSnapshot | None
    opsec: OpsecStateSnapshot | None

    @model_validator(mode="after")
    def _check_freshness(self) -> _RuntimeGateFields:
        if self.fresh_until <= self.captured_at:
            raise ValueError("fresh_until must be strictly after captured_at")
        return self

    @model_validator(mode="after")
    def _check_cross_boundary_binding(self) -> _RuntimeGateFields:
        if self.approval_grant is not None:
            _bind_object(
                self.approval_grant,
                self,
                "approval_grant",
                (
                    "tenant_id",
                    "engagement_id",
                    "proposal_id",
                    "proposal_digest",
                    "admission_result_digest",
                    "capability_id",
                ),
            )
        if self.budget is not None:
            _bind_budget(self.budget, self)
        if self.lock is not None:
            _bind_object(self.lock, self, "lock", ("tenant_id", "engagement_id"))
            if self.lock.holder is not None:
                _require_equal(
                    self.lock.holder.holder_proposal_id,
                    self.proposal_id,
                    "lock.holder",
                    "proposal_id",
                )
        if self.engagement is not None:
            _bind_object(self.engagement, self, "engagement", ("tenant_id", "engagement_id"))
        if self.opsec is not None:
            _bind_object(self.opsec, self, "opsec", ("tenant_id", "engagement_id"))
        return self


class RuntimeGateSnapshot(_RuntimeGateFields):
    snapshot_digest: HexDigest

    @model_validator(mode="after")
    def _check_snapshot_digest(self) -> RuntimeGateSnapshot:
        values = self.model_dump(exclude={"snapshot_digest"})
        if self.snapshot_digest != _runtime_gate_digest(values):
            raise ValueError("snapshot_digest does not bind the gate contents")
        return self

    @classmethod
    def build(cls, fields: Mapping[str, object]) -> RuntimeGateSnapshot:
        values = _RuntimeGateFields.model_validate(fields).model_dump()
        return cls.model_validate({**values, "snapshot_digest": _runtime_gate_digest(values)})
