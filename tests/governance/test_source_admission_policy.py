"""Strict policy contract proofs for source admission."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from blackbread.governance.source_admission_policy import (
    AIFact,
    Disposition,
    IdentityRole,
    ObligationRequirement,
    OriginKind,
    PolicyValidationError,
    ProcessorProfile,
    RevisionTrigger,
    SourceAdmissionPolicy,
    UseProfile,
    canonical_policy_bytes,
    compute_policy_digest,
    parse_policy_bytes,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "source-admission-policy.json"
OWNER = "github:carlitotate12160-tech"
KNOWN_DIGEST = "ab0f6408d257fd8a5a38ddc5582900aad45be2ae2c438e1d7697cfcb75523463"


def _raw_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _policy() -> SourceAdmissionPolicy:
    return parse_policy_bytes(POLICY_PATH.read_bytes())


def _encoded(raw: dict[str, Any]) -> bytes:
    return json.dumps(raw, ensure_ascii=False).encode("utf-8")


def _assert_code(payload: bytes, expected: str) -> None:
    with pytest.raises(PolicyValidationError) as excinfo:
        parse_policy_bytes(payload)
    assert excinfo.value.code == expected
    decoded = payload.decode("utf-8", errors="ignore")
    assert not decoded or decoded not in str(excinfo.value)


def test_checked_in_policy_parses_and_names_exact_boundary() -> None:
    policy = _policy()

    assert policy.schema_version == 1
    assert policy.policy_id == "blackbread-source-admission"
    assert policy.policy_version == "1"
    assert policy.canonical_path == "config/source-admission-policy.json"
    assert policy.effective_after_merge is True
    assert policy.use_profiles == (UseProfile.ENGINEERING_REVIEW,)
    assert policy.processor_profile is ProcessorProfile.LOCAL_ONLY
    assert policy.external_processors_forbidden is True
    assert policy.review_only_enabled is False
    assert policy.per_run_override is False
    assert policy.license_family_allowlist == ()
    assert policy.unknown_default is Disposition.REVIEW_REQUIRED
    assert policy.unsupported_default is Disposition.REVIEW_REQUIRED
    assert policy.unknown_admissible is False


def test_owner_identity_and_permission_grant_are_exact_and_non_authorizing() -> None:
    policy = _policy()
    identity = policy.approved_identities[0]
    grant = policy.permission_grants[0]

    assert len(policy.approved_identities) == 1
    assert identity.identity_id == OWNER
    assert set(identity.roles) == {
        IdentityRole.OWNER,
        IdentityRole.GRANTOR,
        IdentityRole.REVIEWER,
        IdentityRole.REPOSITORY_CONTRIBUTOR,
    }
    assert grant.grant_id == "owner-engineering-review-v1"
    assert grant.grantor_identity_id == OWNER
    assert grant.repository == "carlitotate12160-tech/BlackBread"
    assert grant.permitted_use is UseProfile.ENGINEERING_REVIEW
    assert set(grant.material_scope) == {
        OriginKind.REPOSITORY_AUTHORED,
        OriginKind.AI_GENERATED,
    }
    assert grant.owner_submitted_only is True
    assert grant.owner_controlled_rights_only is True
    assert grant.distribution_right is False
    assert grant.public_publication_right is False
    assert grant.waives_third_party_rights is False
    assert grant.merge_permission is False
    assert grant.capability_permission is False
    assert grant.target_permission is False


def test_no_bot_rights_holder_allowlist_or_self_reference_exists() -> None:
    policy = _policy()
    raw = _raw_policy()

    assert all("bot" not in identity.identity_id.lower() for identity in policy.approved_identities)
    assert policy.license_family_allowlist == ()
    forbidden_keys = {"commit_sha", "git_blob_sha", "raw_sha256", "policy_digest"}

    def keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for child in value.values() for key in keys(child)}
        if isinstance(value, list):
            return {key for child in value for key in keys(child)}
        return set()

    assert keys(raw).isdisjoint(forbidden_keys)


def test_origin_ai_and_obligation_decisions_are_exact() -> None:
    policy = _policy()
    rules = {rule.origin: rule for rule in policy.origin_rules}
    obligations = {rule.obligation_id: rule.requirement for rule in policy.obligations}

    assert rules[OriginKind.REPOSITORY_AUTHORED].disposition is Disposition.POTENTIALLY_ADMISSIBLE
    assert rules[OriginKind.REPOSITORY_AUTHORED].exact_grant_required is True
    assert rules[OriginKind.REPOSITORY_AUTHORED].approved_contributor_required is True
    assert rules[OriginKind.REPOSITORY_AUTHORED].bindings_required is True
    assert rules[OriginKind.REPOSITORY_AUTHORED].human_review_required is True
    assert rules[OriginKind.AI_GENERATED].exact_grant_required is True
    assert rules[OriginKind.AI_GENERATED].approved_contributor_required is True
    assert rules[OriginKind.AI_GENERATED].bindings_required is True
    assert rules[OriginKind.AI_GENERATED].human_review_required is True
    assert rules[OriginKind.AI_GENERATED].complete_ai_facts_required is True
    assert rules[OriginKind.AI_GENERATED].provider_tool_terms_required is True
    for origin in (
        OriginKind.THIRD_PARTY_SOURCE,
        OriginKind.VENDORED_SOURCE,
        OriginKind.GENERATED_ARTIFACT,
        OriginKind.EXTERNAL_PATCH,
        OriginKind.MIXED_UNRESOLVED,
        OriginKind.UNAPPROVED_CONTRIBUTOR,
    ):
        assert rules[origin].disposition is Disposition.REVIEW_REQUIRED
    assert rules[OriginKind.UNKNOWN].disposition is Disposition.NEVER_ADMITTED
    assert policy.embedded_third_party_notice_requires_review is True
    assert policy.license_expression_required_for_grant_material is False
    assert policy.spdx_is_evidence_only is True
    assert set(policy.ai_required_facts) == set(AIFact)
    assert policy.ai_allowed_unavailable_facts == (AIFact.MODEL_VERSION,)
    assert policy.ai_empty_collections_explicit is True
    assert policy.ai_not_provided_sufficient is False
    assert obligations == {
        "retained-notices": ObligationRequirement.MANDATORY_IF_PRESENT,
        "attribution": ObligationRequirement.MANDATORY_IF_REQUIRED_BY_EVIDENCE,
        "modification-marking": ObligationRequirement.MANDATORY_IF_REQUIRED_BY_EVIDENCE,
        "ai-provider-tool-terms": ObligationRequirement.MANDATORY_FOR_AI,
        "redistribution-rights": ObligationRequirement.NOT_EVALUATED,
        "public-repository-publication": ObligationRequirement.NOT_EVALUATED,
        "source-disclosure": ObligationRequirement.NOT_EVALUATED,
        "target-use": ObligationRequirement.FORBIDDEN,
    }


def test_retention_revision_and_digest_limitations_are_exact() -> None:
    policy = _policy()
    retention = policy.retention

    assert retention.store_id == "engineering-source-admission-v1"
    assert retention.writer_principal == "source-admission-runner"
    assert retention.disposition_principal == "repository-owner"
    assert retention.metadata_report_days == 30
    assert retention.review_quarantine_until_disposition is True
    assert retention.review_quarantine_max_days == 30
    assert retention.raw_partial_max_hours == 24
    assert retention.append_only_metadata is True
    assert retention.raw_deletion_requires_tombstone is True
    assert retention.separate_from_campaign_ledger is True
    assert set(policy.revision_triggers) == set(RevisionTrigger)
    assert policy.previous_reports_historical_only is True
    assert policy.revision_inheritance_allowed is False
    assert policy.digest_content_consistency_only is True
    assert policy.digest_authenticates_owner is False
    assert policy.digest_proves_protected_main_origin is False
    assert policy.digest_proves_freshness is False
    assert policy.digest_grants_permission is False


def test_parser_rejects_encoding_json_schema_unknown_coercion_and_float() -> None:
    raw = _raw_policy()
    _assert_code(b"\xff\xfe", "POLICY_UTF8_INVALID")
    _assert_code(b"{not-json", "POLICY_JSON_MALFORMED")
    _assert_code(b'{"schema_version":1,"schema_version":1}', "POLICY_JSON_DUPLICATE_KEY")
    without_schema = deepcopy(raw)
    del without_schema["schema_version"]
    _assert_code(_encoded(without_schema), "POLICY_SCHEMA_MISSING")
    _assert_code(_encoded({**raw, "schema_version": 2}), "POLICY_SCHEMA_UNSUPPORTED")
    _assert_code(_encoded({**raw, "schema_version": "1"}), "POLICY_SCHEMA_INVALID")
    _assert_code(_encoded({**raw, "unknown_field": True}), "POLICY_SCHEMA_INVALID")
    float_policy = deepcopy(raw)
    float_policy["retention"]["metadata_report_days"] = 30.0
    _assert_code(_encoded(float_policy), "POLICY_FLOAT_FORBIDDEN")


@pytest.mark.parametrize(
    ("collection", "id_field"),
    [
        ("approved_identities", "identity_id"),
        ("permission_grants", "grant_id"),
        ("origin_rules", "rule_id"),
        ("obligations", "obligation_id"),
    ],
)
def test_duplicate_logical_ids_fail_closed(collection: str, id_field: str) -> None:
    raw = _raw_policy()
    duplicate = deepcopy(raw[collection][0])
    duplicate[id_field] = raw[collection][0][id_field]
    raw[collection].append(duplicate)

    _assert_code(_encoded(raw), "POLICY_SCHEMA_INVALID")


def test_required_empty_collection_cannot_be_omitted() -> None:
    raw = _raw_policy()
    del raw["license_family_allowlist"]

    _assert_code(_encoded(raw), "POLICY_SCHEMA_INVALID")


def test_set_like_order_normalizes_but_semantic_array_order_is_preserved() -> None:
    raw = _raw_policy()
    raw["approved_identities"][0]["roles"].reverse()
    reordered_set = parse_policy_bytes(_encoded(raw))
    baseline = _policy()

    assert canonical_policy_bytes(reordered_set) == canonical_policy_bytes(baseline)
    assert compute_policy_digest(reordered_set) == compute_policy_digest(baseline)

    raw = _raw_policy()
    raw["origin_rules"].reverse()
    reordered_semantics = parse_policy_bytes(_encoded(raw))
    assert canonical_policy_bytes(reordered_semantics) != canonical_policy_bytes(baseline)
    assert compute_policy_digest(reordered_semantics) != compute_policy_digest(baseline)


def test_canonical_bytes_and_digest_match_known_answer() -> None:
    policy = _policy()
    raw_canonical = json.dumps(
        _raw_policy(), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    independent = hashlib.sha256(b"blackbread.source-policy.v1\0" + raw_canonical).hexdigest()

    assert canonical_policy_bytes(policy) == canonical_policy_bytes(
        parse_policy_bytes(canonical_policy_bytes(policy))
    )
    assert independent == KNOWN_DIGEST
    assert compute_policy_digest(policy) == KNOWN_DIGEST


Mutation = Callable[[dict[str, Any]], None]


def _grant_scope(raw: dict[str, Any]) -> None:
    raw["permission_grants"][0]["material_scope"] = ["REPOSITORY_AUTHORED"]


def _allowed_use(raw: dict[str, Any]) -> None:
    raw["use_profiles"] = ["ENGINEERING_REVIEW", "PUBLIC_DISTRIBUTION"]


def _processor(raw: dict[str, Any]) -> None:
    raw["processor_profile"] = "EXTERNAL"


def _origin_rule(raw: dict[str, Any]) -> None:
    raw["origin_rules"][0]["disposition"] = "REVIEW_REQUIRED"


def _obligation(raw: dict[str, Any]) -> None:
    raw["obligations"][0]["requirement"] = "NOT_EVALUATED"


def _retention(raw: dict[str, Any]) -> None:
    raw["retention"]["metadata_report_days"] = 31


def _revision(raw: dict[str, Any]) -> None:
    raw["revision_triggers"].remove("REVIEW_EVIDENCE")


@pytest.mark.parametrize(
    "mutation",
    [_grant_scope, _allowed_use, _processor, _origin_rule, _obligation, _retention, _revision],
)
def test_every_security_relevant_policy_family_changes_digest(mutation: Mutation) -> None:
    raw = _raw_policy()
    mutation(raw)
    changed = parse_policy_bytes(_encoded(raw))

    assert compute_policy_digest(changed) != compute_policy_digest(_policy())


def test_policy_module_is_intentionally_unwired() -> None:
    module_path = ROOT / "src" / "blackbread" / "governance" / "source_admission_policy.py"
    for path in (ROOT / "src" / "blackbread").rglob("*.py"):
        if path != module_path:
            assert "source_admission_policy" not in path.read_text(encoding="utf-8")
