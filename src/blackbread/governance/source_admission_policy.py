"""Strict source-admission policy contract with deterministic semantic digests.

Set-like collections are normalized; grant, origin-rule, and obligation arrays retain order.
The digest proves content consistency only, never authenticity, freshness, or authorization.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Any, Literal, NoReturn

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

_POLICY_DOMAIN = b"blackbread.source-policy.v1"
_MAX_JSON_DEPTH = 100


class UseProfile(StrEnum):
    ENGINEERING_REVIEW = "ENGINEERING_REVIEW"
    PUBLIC_DISTRIBUTION = "PUBLIC_DISTRIBUTION"


class ProcessorProfile(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    EXTERNAL = "EXTERNAL"


class Disposition(StrEnum):
    POTENTIALLY_ADMISSIBLE = "POTENTIALLY_ADMISSIBLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NEVER_ADMITTED = "NEVER_ADMITTED"


class IdentityRole(StrEnum):
    OWNER = "OWNER"
    GRANTOR = "GRANTOR"
    REVIEWER = "REVIEWER"
    REPOSITORY_CONTRIBUTOR = "REPOSITORY_CONTRIBUTOR"


class OriginKind(StrEnum):
    REPOSITORY_AUTHORED = "REPOSITORY_AUTHORED"
    AI_GENERATED = "AI_GENERATED"
    THIRD_PARTY_SOURCE = "THIRD_PARTY_SOURCE"
    VENDORED_SOURCE = "VENDORED_SOURCE"
    GENERATED_ARTIFACT = "GENERATED_ARTIFACT"
    EXTERNAL_PATCH = "EXTERNAL_PATCH"
    MIXED_UNRESOLVED = "MIXED_UNRESOLVED"
    UNAPPROVED_CONTRIBUTOR = "UNAPPROVED_CONTRIBUTOR"
    UNKNOWN = "UNKNOWN"


class AIFact(StrEnum):
    PROVIDER_IDENTIFIER = "PROVIDER_IDENTIFIER"
    AUTHORING_TOOL_IDENTIFIER = "AUTHORING_TOOL_IDENTIFIER"
    MODEL_IDENTIFIER = "MODEL_IDENTIFIER"
    MODEL_VERSION_AVAILABILITY = "MODEL_VERSION_AVAILABILITY"
    MODEL_VERSION = "MODEL_VERSION"
    GENERATION_EVIDENCE_REFERENCE = "GENERATION_EVIDENCE_REFERENCE"
    GENERATION_EVIDENCE_DIGEST = "GENERATION_EVIDENCE_DIGEST"
    DECLARED_INPUTS = "DECLARED_INPUTS"
    EXTERNAL_REFERENCES = "EXTERNAL_REFERENCES"
    HUMAN_SUBMITTER = "HUMAN_SUBMITTER"
    HUMAN_REVIEWER = "HUMAN_REVIEWER"


class ObligationRequirement(StrEnum):
    MANDATORY_IF_PRESENT = "MANDATORY_IF_PRESENT"
    MANDATORY_IF_REQUIRED_BY_EVIDENCE = "MANDATORY_IF_REQUIRED_BY_EVIDENCE"
    MANDATORY_FOR_AI = "MANDATORY_FOR_AI"
    NOT_EVALUATED = "NOT_EVALUATED"
    FORBIDDEN = "FORBIDDEN"


class RevisionTrigger(StrEnum):
    POLICY_VERSION_OR_CONTENT = "POLICY_VERSION_OR_CONTENT"
    USE_PROFILE = "USE_PROFILE"
    PROCESSOR_PROFILE = "PROCESSOR_PROFILE"
    CANDIDATE_HEAD = "CANDIDATE_HEAD"
    INVENTORY = "INVENTORY"
    REVIEW_EVIDENCE = "REVIEW_EVIDENCE"


def _normalize_set[SetValue](values: tuple[SetValue, ...]) -> tuple[SetValue, ...]:
    if len(values) != len(set(values)):
        raise ValueError("set-like collection contains duplicates")
    return tuple(sorted(values, key=str))


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("string must contain non-whitespace characters")
    return value


Text = Annotated[str, Field(min_length=1, max_length=500)]
SetText = Annotated[str, Field(min_length=1, max_length=500), AfterValidator(_non_blank)]
RoleSet = Annotated[tuple[IdentityRole, ...], AfterValidator(_normalize_set)]
OriginSet = Annotated[tuple[OriginKind, ...], AfterValidator(_normalize_set)]
UseSet = Annotated[tuple[UseProfile, ...], AfterValidator(_normalize_set)]
FactSet = Annotated[tuple[AIFact, ...], AfterValidator(_normalize_set)]
TriggerSet = Annotated[tuple[RevisionTrigger, ...], AfterValidator(_normalize_set)]
StringSet = Annotated[tuple[SetText, ...], AfterValidator(_normalize_set)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ApprovedIdentity(_StrictModel):
    identity_id: Text
    roles: RoleSet


class PermissionGrant(_StrictModel):
    grant_id: Text
    grantor_identity_id: Text
    repository: Text
    permitted_use: UseProfile
    material_scope: OriginSet
    owner_submitted_only: bool
    owner_controlled_rights_only: bool
    distribution_right: bool
    public_publication_right: bool
    waives_third_party_rights: bool
    merge_permission: bool
    capability_permission: bool
    target_permission: bool


class OriginRule(_StrictModel):
    rule_id: Text
    origin: OriginKind
    disposition: Disposition
    grant_id: Text | None
    exact_grant_required: bool
    approved_contributor_required: bool
    bindings_required: bool
    human_review_required: bool
    complete_ai_facts_required: bool
    provider_tool_terms_required: bool


class ObligationRule(_StrictModel):
    obligation_id: Text
    requirement: ObligationRequirement


class RetentionPolicy(_StrictModel):
    store_id: Text
    writer_principal: Text
    disposition_principal: Text
    metadata_report_days: Annotated[int, Field(ge=1)]
    review_quarantine_until_disposition: bool
    review_quarantine_max_days: Annotated[int, Field(ge=1)]
    raw_partial_max_hours: Annotated[int, Field(ge=1)]
    append_only_metadata: bool
    raw_deletion_requires_tombstone: bool
    separate_from_campaign_ledger: bool


class SourceAdmissionPolicy(_StrictModel):
    schema_version: Literal[1]
    policy_id: Text
    policy_version: Text
    canonical_path: Text
    effective_after_merge: bool
    use_profiles: UseSet
    processor_profile: ProcessorProfile
    external_processors_forbidden: bool
    review_only_enabled: bool
    per_run_override: bool
    license_family_allowlist: StringSet
    unknown_default: Disposition
    unsupported_default: Disposition
    unknown_admissible: bool
    approved_identities: tuple[ApprovedIdentity, ...]
    permission_grants: tuple[PermissionGrant, ...]
    origin_rules: tuple[OriginRule, ...]
    embedded_third_party_notice_requires_review: bool
    license_expression_required_for_grant_material: bool
    spdx_is_evidence_only: bool
    ai_required_facts: FactSet
    ai_allowed_unavailable_facts: FactSet
    ai_empty_collections_explicit: bool
    ai_not_provided_sufficient: bool
    obligations: tuple[ObligationRule, ...]
    retention: RetentionPolicy
    revision_triggers: TriggerSet
    previous_reports_historical_only: bool
    revision_inheritance_allowed: bool
    digest_content_consistency_only: bool
    digest_authenticates_owner: bool
    digest_proves_protected_main_origin: bool
    digest_proves_freshness: bool
    digest_grants_permission: bool

    @model_validator(mode="after")
    def _reject_duplicate_logical_ids(self) -> SourceAdmissionPolicy:
        groups = (
            [item.identity_id for item in self.approved_identities],
            [item.grant_id for item in self.permission_grants],
            [item.rule_id for item in self.origin_rules],
            [item.obligation_id for item in self.obligations],
        )
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("duplicate logical identifier")
        origins = [item.origin for item in self.origin_rules]
        if len(origins) != len(set(origins)):
            raise ValueError("duplicate origin rule")
        return self


class PolicyValidationError(ValueError):
    """Sanitized policy rejection carrying a stable machine code."""

    def __init__(self, code: str) -> None:
        super().__init__(f"source admission policy rejected: {code}")
        self.code = code


def _fail(code: str) -> NoReturn:
    raise PolicyValidationError(code) from None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, value in pairs:
        if key in decoded:
            _fail("POLICY_JSON_DUPLICATE_KEY")
        decoded[key] = value
    return decoded


def _reject_json_float(_: str) -> NoReturn:
    _fail("POLICY_FLOAT_FORBIDDEN")


def _reject_deep_json(value: Any) -> None:
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > _MAX_JSON_DEPTH:
            _fail("POLICY_JSON_MALFORMED")
        if isinstance(item, dict | list):
            children = item.values() if isinstance(item, dict) else item
            stack.extend((child, depth + 1) for child in children)


def parse_policy_bytes(payload: bytes) -> SourceAdmissionPolicy:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _fail("POLICY_UTF8_INVALID")
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_json_float,
            parse_constant=_reject_json_float,
        )
    except PolicyValidationError:
        raise
    except (json.JSONDecodeError, RecursionError):
        _fail("POLICY_JSON_MALFORMED")
    _reject_deep_json(decoded)
    if not isinstance(decoded, dict):
        _fail("POLICY_SCHEMA_INVALID")
    if "schema_version" not in decoded:
        _fail("POLICY_SCHEMA_MISSING")
    version = decoded["schema_version"]
    if type(version) is not int:
        _fail("POLICY_SCHEMA_INVALID")
    if version != 1:
        _fail("POLICY_SCHEMA_UNSUPPORTED")
    try:
        normalized = json.dumps(decoded, ensure_ascii=False, allow_nan=False)
        return SourceAdmissionPolicy.model_validate_json(normalized)
    except RecursionError:
        _fail("POLICY_JSON_MALFORMED")
    except (TypeError, ValueError):
        _fail("POLICY_SCHEMA_INVALID")


def canonical_policy_bytes(policy: SourceAdmissionPolicy) -> bytes:
    payload = policy.model_dump(mode="json")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def compute_policy_digest(policy: SourceAdmissionPolicy) -> str:
    preimage = _POLICY_DOMAIN + b"\0" + canonical_policy_bytes(policy)
    return hashlib.sha256(preimage).hexdigest()
