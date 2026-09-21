"""Strict caller-constructible source-admission semantic models.

They prove schema/local coherence only; digest fields stay unverified and confer no authority.
"""

from __future__ import annotations

import base64
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from blackbread.governance.source_admission_policy import (
    AIFact,
    OriginKind,
    ProcessorProfile,
    RetentionPolicy,
    UseProfile,
)


class ChangeKind(StrEnum):
    ADDED = "ADDED"
    DELETED = "DELETED"
    MODIFIED = "MODIFIED"
    RENAMED = "RENAMED"


class ObjectKind(StrEnum):
    BLOB = "BLOB"
    SYMLINK = "SYMLINK"
    SUBMODULE = "SUBMODULE"
    UNSUPPORTED = "UNSUPPORTED"


class Availability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class ReviewDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class Verdict(StrEnum):
    ADMITTED = "ADMITTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REJECTED = "REJECTED"
    INVALID = "INVALID"


class ReasonCode(StrEnum):
    SCHEMA_INVALID = "SCHEMA_INVALID"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    SNAPSHOT_MISMATCH = "SNAPSHOT_MISMATCH"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    INCOMPLETE_INVENTORY = "INCOMPLETE_INVENTORY"
    UNTRUSTED_REVIEW = "UNTRUSTED_REVIEW"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    POLICY_FORBIDS_USE = "POLICY_FORBIDS_USE"
    DISCLOSURE_FORBIDDEN = "DISCLOSURE_FORBIDDEN"
    REQUIRED_OBLIGATION_UNSATISFIED = "REQUIRED_OBLIGATION_UNSATISFIED"
    ORIGIN_UNKNOWN = "ORIGIN_UNKNOWN"
    LICENSE_UNKNOWN = "LICENSE_UNKNOWN"
    LICENSE_EXPRESSION_UNSUPPORTED = "LICENSE_EXPRESSION_UNSUPPORTED"
    PROVENANCE_AMBIGUOUS = "PROVENANCE_AMBIGUOUS"
    REVIEW_MISSING = "REVIEW_MISSING"


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("string must contain non-whitespace characters")
    return value


def _normalize_set[SetValue](values: tuple[SetValue, ...]) -> tuple[SetValue, ...]:
    if len(values) != len(set(values)):
        raise ValueError("set-like collection contains duplicates")
    return tuple(sorted(values, key=str))


def _validate_schema_version(value: object) -> object:
    if type(value) is not int:
        raise ValueError("schema version must be an integer")
    return value


def _validate_timestamp(value: str) -> str:
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    return value


def _validate_git_path(value: str) -> str:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, UnicodeEncodeError):
        raise ValueError("Git path must use canonical base64") from None
    if not decoded or b"\0" in decoded or base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("Git path must use canonical non-empty base64")
    return value


SchemaVersion = Annotated[Literal[1], BeforeValidator(_validate_schema_version)]
Text = Annotated[str, Field(min_length=1, max_length=500), AfterValidator(_non_blank)]
Sha1 = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Timestamp = Annotated[str, AfterValidator(_validate_timestamp)]
GitPath = Annotated[str, Field(min_length=4, max_length=5500), AfterValidator(_validate_git_path)]
StringSet = Annotated[tuple[Text, ...], AfterValidator(_normalize_set)]
Sha256Set = Annotated[tuple[Sha256, ...], AfterValidator(_normalize_set)]
OriginSet = Annotated[tuple[OriginKind, ...], AfterValidator(_normalize_set)]
ReasonSet = Annotated[tuple[ReasonCode, ...], AfterValidator(_normalize_set)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SourceSubject(_StrictModel):
    repository: Text
    base_commit_sha1: Sha1
    head_commit_sha1: Sha1
    base_tree_sha1: Sha1
    head_tree_sha1: Sha1
    use_profile: UseProfile
    processor_profile: ProcessorProfile
    coverage_description: Text


_OBJECT_MODES = (
    (ObjectKind.BLOB, "100644"),
    (ObjectKind.BLOB, "100755"),
    (ObjectKind.SYMLINK, "120000"),
    (ObjectKind.SUBMODULE, "160000"),
)


def _validate_side(
    values: tuple[object | None, ...], kind: ObjectKind | None, mode: str | None, required: bool
) -> None:
    if required and any(value is None for value in values):
        raise ValueError("change side is incomplete")
    if not required and any(value is not None for value in values):
        raise ValueError("absent change side must be empty")
    if required and kind is not ObjectKind.UNSUPPORTED and (kind, mode) not in _OBJECT_MODES:
        raise ValueError("object kind and Git mode disagree")


class SourceItem(_StrictModel):
    item_id: Text
    change_kind: ChangeKind
    base_path_b64: GitPath | None
    head_path_b64: GitPath | None
    base_object_kind: ObjectKind | None
    head_object_kind: ObjectKind | None
    base_mode: Text | None
    head_mode: Text | None
    base_object_sha1: Sha1 | None
    head_object_sha1: Sha1 | None
    base_content_sha256: Sha256 | None
    head_content_sha256: Sha256 | None
    origins: OriginSet
    lineage_refs: StringSet
    dependency_refs: StringSet
    obligation_refs: StringSet

    @model_validator(mode="after")
    def _validate_change_shape(self) -> SourceItem:
        before = (
            self.base_path_b64,
            self.base_object_kind,
            self.base_mode,
            self.base_object_sha1,
            self.base_content_sha256,
        )
        after = (
            self.head_path_b64,
            self.head_object_kind,
            self.head_mode,
            self.head_object_sha1,
            self.head_content_sha256,
        )
        base_required = self.change_kind is not ChangeKind.ADDED
        head_required = self.change_kind is not ChangeKind.DELETED
        _validate_side(before, self.base_object_kind, self.base_mode, base_required)
        _validate_side(after, self.head_object_kind, self.head_mode, head_required)
        if self.change_kind is ChangeKind.MODIFIED and self.base_path_b64 != self.head_path_b64:
            raise ValueError("modified item paths must match")
        if self.change_kind is ChangeKind.RENAMED and self.base_path_b64 == self.head_path_b64:
            raise ValueError("renamed item paths must differ")
        return self


class AIFactEvidence(_StrictModel):
    fact: AIFact
    availability: Availability
    value: Text | None
    evidence_ref: Text | None
    evidence_sha256: Sha256 | None

    @model_validator(mode="after")
    def _validate_availability(self) -> AIFactEvidence:
        evidence = (self.value, self.evidence_ref, self.evidence_sha256)
        if self.availability is Availability.AVAILABLE and any(item is None for item in evidence):
            raise ValueError("available fact requires value and evidence")
        unavailable = self.availability is Availability.UNAVAILABLE
        if unavailable and any(item is not None for item in evidence):
            raise ValueError("unavailable fact cannot invent evidence")
        return self


class OriginDeclaration(_StrictModel):
    declaration_id: Text
    item_ids: StringSet
    content_sha256s: Sha256Set
    origins: OriginSet
    contributor_identity_id: Text | None
    ai_facts: tuple[AIFactEvidence, ...]
    external_references: StringSet
    license_expression: Text | None
    declaration_evidence_ref: Text
    declaration_evidence_sha256: Sha256

    @model_validator(mode="after")
    def _reject_duplicate_facts(self) -> OriginDeclaration:
        facts = [item.fact for item in self.ai_facts]
        if len(facts) != len(set(facts)):
            raise ValueError("duplicate AI fact")
        return self


class ReviewEvidence(_StrictModel):
    review_id: Text
    reviewer_identity_id: Text
    item_ids: StringSet
    inventory_digest: Sha256
    decision: ReviewDecision
    rationale: Text
    evidence_ref: Text
    evidence_sha256: Sha256
    reviewed_at: Timestamp
    superseded_by: Text | None
    revoked: bool


class SourcePolicyRef(_StrictModel):
    policy_id: Text
    policy_version: Text
    source_commit_sha1: Sha1
    source_blob_sha1: Sha1
    policy_sha256: Sha256
    use_profile: UseProfile
    processor_profile: ProcessorProfile
    retention: RetentionPolicy


class SourceAdmissionBundle(_StrictModel):
    schema_version: SchemaVersion
    subject: SourceSubject
    items: tuple[SourceItem, ...]
    declarations: tuple[OriginDeclaration, ...]
    reviews: tuple[ReviewEvidence, ...]
    policy_ref: SourcePolicyRef
    collector_version: Text
    collected_at: Timestamp
    producer: Text
    run_id: Text

    @model_validator(mode="after")
    def _reject_duplicate_ids(self) -> SourceAdmissionBundle:
        groups = (
            [item.item_id for item in self.items],
            [item.declaration_id for item in self.declarations],
            [item.review_id for item in self.reviews],
        )
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("duplicate logical identifier")
        return self


class ItemAdmissionDecision(_StrictModel):
    item_id: Text
    verdict: Verdict
    reason_codes: ReasonSet
    evidence_complete: bool


class SourceAdmissionReport(_StrictModel):
    schema_version: SchemaVersion
    subject: SourceSubject
    inventory_digest: Sha256
    declarations_digest: Sha256
    reviews_digest: Sha256
    policy_ref: SourcePolicyRef
    evaluator_version: Text
    item_decisions: tuple[ItemAdmissionDecision, ...]
    verdict: Verdict
    reason_codes: ReasonSet
    evidence_complete: bool
    coverage_description: Text
    observed_at: Timestamp
    producer: Text
    run_id: Text
    report_digest: Sha256

    @model_validator(mode="after")
    def _reject_duplicate_ids(self) -> SourceAdmissionReport:
        item_ids = [item.item_id for item in self.item_decisions]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("duplicate logical identifier")
        return self
