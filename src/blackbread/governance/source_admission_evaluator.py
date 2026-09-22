"""Pure deterministic source-admission evaluator; derives verdicts and digests internally."""

from __future__ import annotations

from typing import Literal, NamedTuple

from blackbread.governance.source_admission_codec import (
    compute_declarations_digest,
    compute_inventory_digest,
    compute_report_digest,
    compute_reviews_digest,
)
from blackbread.governance.source_admission_contracts import (
    Availability,
    ChangeKind,
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
    Disposition,
    IdentityRole,
    ObligationRequirement,
    OriginKind,
    OriginRule,
    PermissionGrant,
    ProcessorProfile,
    SourceAdmissionPolicy,
    compute_policy_digest,
)

RC = ReasonCode
Obl = ObligationRequirement
IR = IdentityRole
# Origins whose rights the owner can control; owner-controlled grants may not exceed these.
_OWNER_CONTROLLED_ORIGINS = frozenset({OriginKind.REPOSITORY_AUTHORED, OriginKind.AI_GENERATED})
_Level = Literal["invalid", "rejected", "review_required"]


class SourceAdmissionEvaluationContext(_StrictModel):
    expected_subject: SourceSubject
    expected_policy_ref: SourcePolicyRef
    evaluator_version: Text
    observed_at: Timestamp
    producer: Text
    run_id: Text


class _EvalInputs(NamedTuple):
    policy: SourceAdmissionPolicy
    subject: SourceSubject
    origin_rules: dict[OriginKind, OriginRule]
    obligations: dict[str, ObligationRequirement]
    valid_reviews: frozenset[str]


class _Outcome:
    """Fail-closed finding accumulator; INVALID > REJECTED > REVIEW_REQUIRED."""

    def __init__(self) -> None:
        self.reasons: set[ReasonCode] = set()
        self.invalid = self.rejected = self.review_required = False

    def flag(self, code: ReasonCode, level: _Level) -> None:
        self.reasons.add(code)
        setattr(self, level, True)

    def flag_if(self, condition: bool, code: ReasonCode, level: _Level) -> None:
        if condition:
            self.flag(code, level)

    def verdict(self) -> Verdict:
        if self.invalid:
            return Verdict.INVALID
        if self.rejected:
            return Verdict.REJECTED
        return Verdict.REVIEW_REQUIRED if self.review_required else Verdict.ADMITTED


def _has_role(identity_id: str | None, role: IdentityRole, policy: SourceAdmissionPolicy) -> bool:
    return any(i.identity_id == identity_id and role in i.roles for i in policy.approved_identities)


def _check_origins(
    item: SourceItem, origin_rules: dict[OriginKind, OriginRule], out: _Outcome
) -> list[OriginRule]:
    pa_rules: list[OriginRule] = []
    out.flag_if(not item.origins, RC.PROVENANCE_AMBIGUOUS, "review_required")
    for origin in item.origins:
        rule = origin_rules.get(origin)
        pa = rule is not None and rule.disposition is Disposition.POTENTIALLY_ADMISSIBLE
        out.flag_if(rule is None, RC.POLICY_UNAVAILABLE, "invalid")
        # REVIEW_REQUIRED/NEVER_ADMITTED never admit, even after APPROVED review.
        out.flag_if(rule is not None and not pa, RC.ORIGIN_UNKNOWN, "review_required")
        if rule is not None and pa:
            pa_rules.append(rule)
    return pa_rules


def _check_declarations(
    item: SourceItem, decs: list[OriginDeclaration], out: _Outcome
) -> str | None:
    """Bind every covering declaration; return the unambiguous contributor."""
    bound = item.head_content_sha256
    if item.change_kind is ChangeKind.DELETED:
        bound = item.base_content_sha256
    for dec in decs:
        if bound is not None and bound not in dec.content_sha256s:
            out.flag(RC.SNAPSHOT_MISMATCH, "invalid")
        if set(dec.origins) != set(item.origins):
            out.flag(RC.PROVENANCE_AMBIGUOUS, "invalid")
    contributors = {dec.contributor_identity_id for dec in decs}
    out.flag_if(len(contributors) > 1, RC.PROVENANCE_AMBIGUOUS, "review_required")
    return contributors.pop() if len(contributors) == 1 else None


def _grant_level(
    grant: PermissionGrant,
    subject: SourceSubject,
    item: SourceItem,
    contributor: str | None,
    policy: SourceAdmissionPolicy,
) -> _Level | None:
    """Return the fail-closed level a grant defect maps to, or None when sound."""
    uncontrolled = set(grant.material_scope) - _OWNER_CONTROLLED_ORIGINS
    overreach = bool(
        grant.waives_third_party_rights
        or grant.merge_permission
        or grant.capability_permission
        or grant.target_permission
        or (grant.owner_controlled_rights_only and uncontrolled)
    )
    inconsistent = (
        overreach
        or not _has_role(grant.grantor_identity_id, IR.GRANTOR, policy)
        or grant.permitted_use not in policy.use_profiles
    )
    unpermitted = (
        grant.repository != subject.repository
        or grant.permitted_use != subject.use_profile
        or not set(item.origins) <= set(grant.material_scope)
    )
    if inconsistent:
        return "invalid"
    if unpermitted:
        return "rejected"
    # An owner-submitted-only grant whose submitter identity is not yet
    # established is a provenance gap, not a hard policy refusal.
    if grant.owner_submitted_only and not _has_role(contributor, IR.OWNER, policy):
        return "review_required"
    return None


def _check_grants(
    item: SourceItem,
    pa_rules: list[OriginRule],
    contributor: str | None,
    ctx: _EvalInputs,
    out: _Outcome,
) -> None:
    grants = {g.grant_id: g for g in ctx.policy.permission_grants}
    for rule in pa_rules:
        if rule.approved_contributor_required and not _has_role(
            contributor, IR.REPOSITORY_CONTRIBUTOR, ctx.policy
        ):
            out.flag(RC.PROVENANCE_AMBIGUOUS, "review_required")
        if rule.grant_id is None and not rule.exact_grant_required:
            continue
        grant = grants.get(rule.grant_id or "")
        level = (
            "invalid"
            if grant is None
            else _grant_level(grant, ctx.subject, item, contributor, ctx.policy)
        )
        out.flag_if(level == "invalid", RC.POLICY_UNAVAILABLE, "invalid")
        out.flag_if(level == "rejected", RC.POLICY_FORBIDS_USE, "rejected")
        out.flag_if(level == "review_required", RC.PROVENANCE_AMBIGUOUS, "review_required")


def _evaluate_item(
    item: SourceItem, bundle: SourceAdmissionBundle, ctx: _EvalInputs
) -> ItemAdmissionDecision:
    out = _Outcome()
    decs = [d for d in bundle.declarations if item.item_id in d.item_ids]
    out.flag_if(not decs, RC.PROVENANCE_AMBIGUOUS, "review_required")
    pa_rules = _check_origins(item, ctx.origin_rules, out)
    contributor = _check_declarations(item, decs, out)
    _check_grants(item, pa_rules, contributor, ctx, out)
    ai_item = OriginKind.AI_GENERATED in item.origins
    if ai_item:
        for fact in ctx.policy.ai_required_facts:
            evidence = [f for d in decs for f in d.ai_facts if f.fact is fact]
            values = {f.value for f in evidence if f.availability is Availability.AVAILABLE}
            unavailable = any(f.availability is Availability.UNAVAILABLE for f in evidence)
            allowed = unavailable and fact in ctx.policy.ai_allowed_unavailable_facts
            if len(values) > 1 or (values and unavailable):
                out.flag(RC.PROVENANCE_AMBIGUOUS, "review_required")
            elif not values and not allowed:
                out.flag(RC.REQUIRED_OBLIGATION_UNSATISFIED, "review_required")
    for obligation_id, req in ctx.obligations.items():
        if req is Obl.FORBIDDEN and obligation_id in item.obligation_refs:
            out.flag(RC.REQUIRED_OBLIGATION_UNSATISFIED, "rejected")
        if ai_item and req is Obl.MANDATORY_FOR_AI and obligation_id not in item.obligation_refs:
            out.flag(RC.REQUIRED_OBLIGATION_UNSATISFIED, "rejected")
    for ref in item.obligation_refs:
        out.flag_if(ref not in ctx.obligations, RC.PROVENANCE_AMBIGUOUS, "review_required")
    needs_review = any(r.human_review_required for r in pa_rules)
    reviewed = any(
        item.item_id in r.item_ids and r.review_id in ctx.valid_reviews for r in bundle.reviews
    )
    out.flag_if(needs_review and not reviewed, RC.REVIEW_MISSING, "review_required")
    verdict = out.verdict()
    return ItemAdmissionDecision(
        item_id=item.item_id,
        verdict=verdict,
        reason_codes=tuple(sorted(out.reasons)),
        evidence_complete=verdict is Verdict.ADMITTED,
    )


def _check_global(
    bundle: SourceAdmissionBundle,
    policy: SourceAdmissionPolicy,
    context: SourceAdmissionEvaluationContext,
    out: _Outcome,
) -> None:
    ref, subject = bundle.policy_ref, bundle.subject
    out.flag_if(subject != context.expected_subject, RC.SNAPSHOT_MISMATCH, "invalid")
    out.flag_if(bundle.run_id != context.run_id, RC.IDENTITY_MISMATCH, "invalid")
    out.flag_if(ref != context.expected_policy_ref, RC.DIGEST_MISMATCH, "invalid")
    if compute_policy_digest(policy) != ref.policy_sha256:
        out.flag(RC.DIGEST_MISMATCH, "invalid")
    # The ref must describe this exact policy and subject, not merely carry a
    # matching digest; commit/blob SHAs and protected-main provenance are B2.
    for field in ("policy_id", "policy_version", "retention"):
        out.flag_if(getattr(ref, field) != getattr(policy, field), RC.IDENTITY_MISMATCH, "invalid")
    for field in ("use_profile", "processor_profile"):
        out.flag_if(getattr(ref, field) != getattr(subject, field), RC.IDENTITY_MISMATCH, "invalid")
    out.flag_if(not bundle.items, RC.INCOMPLETE_INVENTORY, "invalid")
    if len({r.origin for r in policy.origin_rules}) != len(policy.origin_rules):
        out.flag(RC.POLICY_UNAVAILABLE, "invalid")
    item_ids = {item.item_id for item in bundle.items}
    for dec in bundle.declarations:
        if not set(dec.item_ids).issubset(item_ids):
            out.flag(RC.INCOMPLETE_INVENTORY, "invalid")
    if subject.use_profile not in policy.use_profiles:
        out.flag(RC.POLICY_FORBIDS_USE, "rejected")
    # Symmetric: the declared processor profile must equal the policy-permitted
    # profile, not merely avoid EXTERNAL while external is forbidden.
    if subject.processor_profile != policy.processor_profile:
        out.flag(RC.DISCLOSURE_FORBIDDEN, "rejected")
    if (
        subject.processor_profile is ProcessorProfile.EXTERNAL
        and policy.external_processors_forbidden
    ):
        out.flag(RC.DISCLOSURE_FORBIDDEN, "rejected")


def _check_reviews(
    bundle: SourceAdmissionBundle,
    policy: SourceAdmissionPolicy,
    item_ids: set[str],
    inv_digest: str,
    out: _Outcome,
) -> frozenset[str]:
    valid = set()
    for rev in bundle.reviews:
        if not set(rev.item_ids).issubset(item_ids):
            out.flag(RC.INCOMPLETE_INVENTORY, "invalid")
        out.flag_if(rev.inventory_digest != inv_digest, RC.DIGEST_MISMATCH, "invalid")
        untrusted = bool(rev.revoked or rev.superseded_by) or not _has_role(
            rev.reviewer_identity_id, IR.REVIEWER, policy
        )
        out.flag_if(untrusted, RC.UNTRUSTED_REVIEW, "invalid")
        if not untrusted and rev.decision is ReviewDecision.APPROVED:
            valid.add(rev.review_id)
    return frozenset(valid)


def evaluate_source_admission(
    bundle: SourceAdmissionBundle,
    policy: SourceAdmissionPolicy,
    context: SourceAdmissionEvaluationContext,
) -> SourceAdmissionReport:
    out = _Outcome()
    _check_global(bundle, policy, context, out)
    inv_digest = compute_inventory_digest(bundle)
    rules = {r.origin: r for r in policy.origin_rules}
    obligations = {o.obligation_id: o.requirement for o in policy.obligations}
    item_ids = {i.item_id for i in bundle.items}
    reviews = _check_reviews(bundle, policy, item_ids, inv_digest, out)
    ctx = _EvalInputs(policy, bundle.subject, rules, obligations, reviews)
    decisions = [_evaluate_item(item, bundle, ctx) for item in bundle.items]
    for d in decisions:
        out.reasons.update(d.reason_codes)
        out.invalid |= d.verdict is Verdict.INVALID
        out.rejected |= d.verdict is Verdict.REJECTED
        out.review_required |= d.verdict is Verdict.REVIEW_REQUIRED
    verdict = out.verdict()
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
        reason_codes=tuple(sorted(out.reasons)),
        evidence_complete=verdict is Verdict.ADMITTED,
        coverage_description=bundle.subject.coverage_description,
        observed_at=context.observed_at,
        producer=context.producer,
        run_id=context.run_id,
        report_digest="0" * 64,
    )
    return report.model_copy(update={"report_digest": compute_report_digest(report)})
