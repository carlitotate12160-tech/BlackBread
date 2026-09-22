"""Pure deterministic source-admission evaluator.

Derives every item decision, aggregate verdict, and report digest internally.
"""

from __future__ import annotations

from blackbread.governance.source_admission_codec import (
    compute_declarations_digest,
    compute_inventory_digest,
    compute_report_digest,
    compute_reviews_digest,
)
from blackbread.governance.source_admission_contracts import (
    Availability,
    ItemAdmissionDecision,
    OriginDeclaration,
    ReasonCode,
    ReviewDecision,
    SourceAdmissionBundle,
    SourceAdmissionReport,
    SourceItem,
    SourcePolicyRef,
    SourceSubject,
    Text,
    Timestamp,
    Verdict,
    _StrictModel,
)
from blackbread.governance.source_admission_policy import (
    AIFact,
    Disposition,
    OriginKind,
    OriginRule,
    ProcessorProfile,
    SourceAdmissionPolicy,
    compute_policy_digest,
)


class SourceAdmissionEvaluationContext(_StrictModel):
    expected_subject: SourceSubject
    expected_policy_ref: SourcePolicyRef
    evaluator_version: Text
    observed_at: Timestamp
    producer: Text
    run_id: Text


def _is_approved_reviewer(reviewer_id: str, policy: SourceAdmissionPolicy) -> bool:
    for identity in policy.approved_identities:
        if identity.identity_id == reviewer_id and "REVIEWER" in identity.roles:
            return True
    return False


def _check_origins(
    item: SourceItem, origin_rules: dict[OriginKind, OriginRule], reasons: set[ReasonCode]
) -> tuple[bool, bool]:
    invalid = False
    review_required = False
    for origin in item.origins:
        if origin not in origin_rules:
            reasons.add(ReasonCode.POLICY_UNAVAILABLE)
            invalid = True
        elif origin_rules[origin].disposition == Disposition.NEVER_ADMITTED:
            reasons.add(ReasonCode.ORIGIN_UNKNOWN)
            review_required = True
    return invalid, review_required


def _check_declarations(
    item: SourceItem,
    decs: list[OriginDeclaration],
    policy: SourceAdmissionPolicy,
    reasons: set[ReasonCode],
) -> tuple[bool, bool]:
    invalid = False
    review_required = False
    for dec in decs:
        if item.head_content_sha256 and item.head_content_sha256 not in dec.content_sha256s:
            reasons.add(ReasonCode.SNAPSHOT_MISMATCH)
            invalid = True
        if not set(item.origins).issubset(set(dec.origins)):
            reasons.add(ReasonCode.PROVENANCE_AMBIGUOUS)
            invalid = True
        has_mandatory_fact = any(
            f.fact == AIFact.MODEL_IDENTIFIER and f.availability == Availability.AVAILABLE
            for f in dec.ai_facts
        )
        if OriginKind.AI_GENERATED in item.origins and not has_mandatory_fact:
            reasons.add(ReasonCode.REQUIRED_OBLIGATION_UNSATISFIED)
            review_required = True
        for f in dec.ai_facts:
            if (
                f.availability == Availability.UNAVAILABLE
                and f.fact not in policy.ai_allowed_unavailable_facts
            ):
                reasons.add(ReasonCode.REQUIRED_OBLIGATION_UNSATISFIED)
                review_required = True
    return invalid, review_required


def _evaluate_item(
    item: SourceItem,
    bundle: SourceAdmissionBundle,
    policy: SourceAdmissionPolicy,
    origin_rules: dict[OriginKind, OriginRule],
    valid_reviews: set[str],
) -> ItemAdmissionDecision:
    reasons = set()
    decs = [d for d in bundle.declarations if item.item_id in d.item_ids]
    if not decs:
        reasons.add(ReasonCode.PROVENANCE_AMBIGUOUS)
    inv1, rev1 = _check_origins(item, origin_rules, reasons)
    inv2, rev2 = _check_declarations(item, decs, policy, reasons)
    rejected = (
        "ai-provider-tool-terms" not in item.obligation_refs
        and OriginKind.AI_GENERATED in item.origins
    )
    if rejected:
        reasons.add(ReasonCode.REQUIRED_OBLIGATION_UNSATISFIED)
    has_review = any(
        item.item_id in rev.item_ids and rev.review_id in valid_reviews for rev in bundle.reviews
    )
    if not has_review:
        reasons.add(ReasonCode.REVIEW_MISSING)

    invalid = inv1 or inv2
    review_required = rev1 or rev2 or not decs or not has_review
    if invalid:
        verdict = Verdict.INVALID
    elif rejected:
        verdict = Verdict.REJECTED
    elif review_required:
        verdict = Verdict.REVIEW_REQUIRED
    else:
        verdict = Verdict.ADMITTED
    return ItemAdmissionDecision(
        item_id=item.item_id,
        verdict=verdict,
        reason_codes=tuple(sorted(reasons)),
        evidence_complete=verdict == Verdict.ADMITTED,
    )


def _check_global(
    bundle: SourceAdmissionBundle,
    policy: SourceAdmissionPolicy,
    context: SourceAdmissionEvaluationContext,
) -> tuple[set[ReasonCode], bool, bool]:
    reasons: set[ReasonCode] = set()
    if bundle.subject != context.expected_subject:
        reasons.add(ReasonCode.SNAPSHOT_MISMATCH)
    if bundle.run_id != context.run_id:
        reasons.add(ReasonCode.IDENTITY_MISMATCH)
    if bundle.policy_ref != context.expected_policy_ref:
        reasons.add(ReasonCode.DIGEST_MISMATCH)
    if compute_policy_digest(policy) != context.expected_policy_ref.policy_sha256:
        reasons.add(ReasonCode.DIGEST_MISMATCH)
    if not bundle.items:
        reasons.add(ReasonCode.INCOMPLETE_INVENTORY)

    inv = bool(reasons)
    item_ids = {item.item_id for item in bundle.items}
    for dec in bundle.declarations:
        if not set(dec.item_ids).issubset(item_ids):
            reasons.add(ReasonCode.INCOMPLETE_INVENTORY)
            inv = True

    rej = False
    if bundle.subject.use_profile not in policy.use_profiles:
        reasons.add(ReasonCode.POLICY_FORBIDS_USE)
        rej = True
    if (
        bundle.subject.processor_profile == ProcessorProfile.EXTERNAL
        and policy.external_processors_forbidden
    ):
        reasons.add(ReasonCode.DISCLOSURE_FORBIDDEN)
        rej = True
    return reasons, inv, rej


def _check_reviews(
    bundle: SourceAdmissionBundle,
    policy: SourceAdmissionPolicy,
    item_ids: set[str],
    inv_digest: str,
    reasons: set[ReasonCode],
) -> tuple[set[str], bool]:
    valid = set()
    inv = False
    for rev in bundle.reviews:
        if not set(rev.item_ids).issubset(item_ids):
            reasons.add(ReasonCode.INCOMPLETE_INVENTORY)
            inv = True
        if rev.inventory_digest != inv_digest:
            reasons.add(ReasonCode.DIGEST_MISMATCH)
            inv = True
        if (
            rev.revoked
            or rev.superseded_by
            or not _is_approved_reviewer(rev.reviewer_identity_id, policy)
        ):
            reasons.add(ReasonCode.UNTRUSTED_REVIEW)
            inv = True
        elif rev.decision == ReviewDecision.APPROVED:
            valid.add(rev.review_id)
    return valid, inv


def _aggregate_verdict(decisions: list[ItemAdmissionDecision], inv: bool, rej: bool) -> Verdict:
    if inv or any(d.verdict == Verdict.INVALID for d in decisions):
        return Verdict.INVALID
    if rej or any(d.verdict == Verdict.REJECTED for d in decisions):
        return Verdict.REJECTED
    if any(d.verdict == Verdict.REVIEW_REQUIRED for d in decisions):
        return Verdict.REVIEW_REQUIRED
    return Verdict.ADMITTED


def evaluate_source_admission(
    bundle: SourceAdmissionBundle,
    policy: SourceAdmissionPolicy,
    context: SourceAdmissionEvaluationContext,
) -> SourceAdmissionReport:
    global_reasons, global_inv, global_rej = _check_global(bundle, policy, context)
    inv_digest = compute_inventory_digest(bundle)
    valid_reviews, rev_inv = _check_reviews(
        bundle, policy, {i.item_id for i in bundle.items}, inv_digest, global_reasons
    )

    origin_rules = {r.origin: r for r in policy.origin_rules}
    decisions = [
        _evaluate_item(item, bundle, policy, origin_rules, valid_reviews) for item in bundle.items
    ]

    all_reasons = set(global_reasons)
    for d in decisions:
        all_reasons.update(d.reason_codes)

    verdict = _aggregate_verdict(decisions, global_inv or rev_inv, global_rej)

    report = SourceAdmissionReport(
        schema_version=1,
        subject=bundle.subject,
        inventory_digest=inv_digest,
        declarations_digest=compute_declarations_digest(bundle),
        reviews_digest=compute_reviews_digest(bundle),
        policy_ref=bundle.policy_ref,
        evaluator_version=context.evaluator_version,
        item_decisions=tuple(decisions),
        verdict=verdict,
        reason_codes=tuple(sorted(all_reasons)),
        evidence_complete=verdict == Verdict.ADMITTED,
        coverage_description=bundle.subject.coverage_description,
        observed_at=context.observed_at,
        producer=context.producer,
        run_id=context.run_id,
        report_digest="0" * 64,
    )
    return SourceAdmissionReport(
        **{**report.model_dump(), "report_digest": compute_report_digest(report)}
    )
