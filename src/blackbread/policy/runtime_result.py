"""Strict non-executable result contract for pure runtime-gate evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Annotated, Any, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from blackbread.conductor.contracts import (
    MAX_SCHEMA_VERSION,
    CapabilityId,
    HexDigest,
    SchemaVersionOne,
    TenantId,
    UtcTimestamp,
)
from blackbread.ledger.hashing import canonical_json, canonical_timestamp, sha256_hex
from blackbread.policy.admission_contracts import ApprovalClass, NetworkPath

RUNTIME_GATE_RESULT_SCHEMA = "policy.runtime.gate.result"
RUNTIME_GATE_RESULT_SCHEMA_VERSION = 1
_RESULT_DIGEST_DOMAIN = "blackbread.policy.runtime.gate.result_digest.v1"

RuntimeGateOutcome = Literal[
    "PASSED_FOR_FINAL_DECISION",
    "DENY",
    "APPROVAL_REQUIRED",
    "WAIT_FOR_RESOURCE",
    "STALE_CONTEXT",
    "ENGAGEMENT_STOPPED",
    "OPSEC_HOLD",
]
RuntimeGateReason = Literal[
    "ADMISSION_BINDING_MISMATCH",
    "RUNTIME_BINDING_MISMATCH",
    "CAPABILITY_BINDING_MISMATCH",
    "ADMISSION_NOT_ADMITTED",
    "PROPOSAL_NOT_YET_VALID",
    "PROPOSAL_EXPIRED",
    "ENGAGEMENT_STATE_MISSING",
    "RUNTIME_CONTEXT_INCOHERENT",
    "ENGAGEMENT_STOPPED",
    "OPSEC_STATE_MISSING",
    "OPSEC_BURNED",
    "OPSEC_HOT",
    "RUNTIME_SNAPSHOT_NOT_YET_VALID",
    "RUNTIME_SNAPSHOT_EXPIRED",
    "OPSEC_STATE_EXPIRED",
    "BUDGET_STATE_MISSING",
    "BUDGET_WINDOW_EXPIRED",
    "LOCK_STATE_MISSING",
    "APPROVAL_MISSING",
    "APPROVAL_CLASS_MISMATCH",
    "APPROVAL_TARGET_MISMATCH",
    "APPROVAL_NOT_YET_VALID",
    "APPROVAL_EXPIRED",
    "APPROVAL_REVOKED",
    "BUDGET_DEADLINE_EXCEEDED",
    "BUDGET_CAPACITY_EXCEEDED",
    "RESOURCE_LOCK_HELD",
]


def _outcome_for_reason(reason: RuntimeGateReason) -> RuntimeGateOutcome:
    if reason.startswith("APPROVAL_"):
        return "APPROVAL_REQUIRED"
    if reason == "RESOURCE_LOCK_HELD":
        return "WAIT_FOR_RESOURCE"
    if reason == "ENGAGEMENT_STOPPED":
        return "ENGAGEMENT_STOPPED"
    if reason.startswith("OPSEC_") and reason != "OPSEC_STATE_EXPIRED":
        return "OPSEC_HOLD"
    stale = reason.startswith(("PROPOSAL_", "RUNTIME_SNAPSHOT_")) or reason in {
        "ENGAGEMENT_STATE_MISSING",
        "RUNTIME_CONTEXT_INCOHERENT",
        "OPSEC_STATE_EXPIRED",
        "BUDGET_STATE_MISSING",
        "BUDGET_WINDOW_EXPIRED",
        "LOCK_STATE_MISSING",
    }
    return "STALE_CONTEXT" if stale else "DENY"


OUTCOME_BY_REASON: MappingProxyType[RuntimeGateReason, RuntimeGateOutcome] = MappingProxyType(
    {reason: _outcome_for_reason(reason) for reason in get_args(RuntimeGateReason)}
)


class _RuntimeGateResultFields(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_name: Literal["policy.runtime.gate.result"]
    schema_version: SchemaVersionOne
    tenant_id: TenantId
    engagement_id: UUID
    proposal_id: UUID
    proposal_digest: HexDigest
    agent_instance_id: UUID
    admission_result_digest: HexDigest
    runtime_snapshot_digest: HexDigest
    registry_schema_version: Annotated[int, Field(ge=1, le=MAX_SCHEMA_VERSION)]
    registry_digest: HexDigest
    capability_id: CapabilityId
    supply_chain_digest: HexDigest
    approval_class: ApprovalClass
    network_path: NetworkPath
    requested_target_requests: Annotated[int, Field(ge=0)]
    requested_cost_microunits: Annotated[int, Field(ge=0)]
    requested_deadline_seconds: Annotated[int, Field(ge=1)]
    evaluated_at: UtcTimestamp
    outcome: RuntimeGateOutcome
    reason_code: RuntimeGateReason | None


class RuntimeGateResult(_RuntimeGateResultFields):
    result_digest: HexDigest

    @model_validator(mode="after")
    def _check_outcome_and_digest(self) -> RuntimeGateResult:
        expected = (
            "PASSED_FOR_FINAL_DECISION"
            if self.reason_code is None
            else OUTCOME_BY_REASON[self.reason_code]
        )
        if self.outcome != expected:
            raise ValueError("outcome and reason_code are incompatible")
        if self.result_digest != _result_digest(self.model_dump(exclude={"result_digest"})):
            raise ValueError("result_digest does not bind the result contents")
        return self

    @classmethod
    def build(cls, fields: Mapping[str, object]) -> RuntimeGateResult:
        values = _RuntimeGateResultFields.model_validate(fields).model_dump()
        return cls.model_validate({**values, "result_digest": _result_digest(values)})


def _canonical_scalar(value: object) -> object:
    if isinstance(value, datetime):
        return canonical_timestamp(value)
    return str(value) if isinstance(value, UUID) else value


def _result_digest(values: Mapping[str, Any]) -> str:
    preimage = {key: _canonical_scalar(value) for key, value in values.items()}
    return sha256_hex(f"{_RESULT_DIGEST_DOMAIN}\x00{canonical_json(preimage)}")
