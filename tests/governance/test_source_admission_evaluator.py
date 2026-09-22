"""Strict proofs for the pure deterministic source-admission evaluator.

Verifies semantic evaluation without relying on authenticity, signatures, or effects.
"""

from __future__ import annotations

import inspect
from copy import deepcopy
from pathlib import Path

import pytest

from blackbread.governance.source_admission_codec import (
    canonical_report_bytes,
    compute_declarations_digest,
    compute_inventory_digest,
    compute_report_digest,
    compute_reviews_digest,
    parse_report_bytes,
)
from blackbread.governance.source_admission_contracts import (
    AIFactEvidence,
    Availability,
    ChangeKind,
    ObjectKind,
    OriginDeclaration,
    ReasonCode,
    ReviewDecision,
    ReviewEvidence,
    SourceAdmissionBundle,
    SourceAdmissionReport,
    SourceItem,
    SourcePolicyRef,
    SourceSubject,
    Verdict,
)
from blackbread.governance.source_admission_evaluator import (
    SourceAdmissionEvaluationContext,
    evaluate_source_admission,
)
from blackbread.governance.source_admission_policy import (
    AIFact,
    OriginKind,
    ProcessorProfile,
    SourceAdmissionPolicy,
    UseProfile,
    compute_policy_digest,
    parse_policy_bytes,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "source-admission-policy.json"
KNOWN_DIGEST = "ab0f6408d257fd8a5a38ddc5582900aad45be2ae2c438e1d7697cfcb75523463"
OWNER = "github:carlitotate12160-tech"


def _policy() -> SourceAdmissionPolicy:
    return parse_policy_bytes(POLICY_PATH.read_bytes())


def _subject() -> SourceSubject:
    return SourceSubject(
        repository="carlitotate12160-tech/BlackBread",
        base_commit_sha1="a" * 40,
        head_commit_sha1="b" * 40,
        base_tree_sha1="c" * 40,
        head_tree_sha1="d" * 40,
        use_profile=UseProfile.ENGINEERING_REVIEW,
        processor_profile=ProcessorProfile.LOCAL_ONLY,
        coverage_description="Full exact coverage",
    )


def _policy_ref() -> SourcePolicyRef:
    policy = _policy()
    return SourcePolicyRef(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        source_commit_sha1="e" * 40,
        source_blob_sha1="f" * 40,
        policy_sha256=compute_policy_digest(policy),
        use_profile=UseProfile.ENGINEERING_REVIEW,
        processor_profile=ProcessorProfile.LOCAL_ONLY,
        retention=policy.retention,
    )


def _item(
    item_id: str = "item-01",
    origins: tuple[OriginKind, ...] = (OriginKind.REPOSITORY_AUTHORED, OriginKind.AI_GENERATED),
) -> SourceItem:
    return SourceItem(
        item_id=item_id,
        change_kind=ChangeKind.MODIFIED,
        base_path_b64="c3JjL2V4YW1wbGUucHk=",
        head_path_b64="c3JjL2V4YW1wbGUucHk=",
        base_object_kind=ObjectKind.BLOB,
        head_object_kind=ObjectKind.BLOB,
        base_mode="100644",
        head_mode="100644",
        base_object_sha1="a" * 40,
        head_object_sha1="b" * 40,
        base_content_sha256="1" * 64,
        head_content_sha256="2" * 64,
        origins=origins,
        lineage_refs=("lineage-01",),
        dependency_refs=("dep-01",),
        obligation_refs=("ai-provider-tool-terms",),
    )


def _declaration(item_ids: tuple[str, ...], origins: tuple[OriginKind, ...]) -> OriginDeclaration:
    ai_facts = [
        AIFactEvidence(
            fact=f,
            availability=Availability.AVAILABLE,
            value="v",
            evidence_ref="r",
            evidence_sha256="3" * 64,
        )
        for f in AIFact
        if f != AIFact.MODEL_VERSION
    ]
    ai_facts.append(
        AIFactEvidence(
            fact=AIFact.MODEL_VERSION,
            availability=Availability.UNAVAILABLE,
            value=None,
            evidence_ref=None,
            evidence_sha256=None,
        )
    )
    return OriginDeclaration(
        declaration_id="dec-01",
        item_ids=item_ids,
        content_sha256s=("2" * 64,),
        origins=origins,
        contributor_identity_id=OWNER,
        ai_facts=tuple(ai_facts),
        external_references=("ext-01",),
        license_expression=None,
        declaration_evidence_ref="dec-ref",
        declaration_evidence_sha256="4" * 64,
    )


def _bundle(  # noqa: PLR0913, PLR0917
    items: tuple[SourceItem, ...],
    declarations: tuple[OriginDeclaration, ...],
    reviews: tuple[ReviewEvidence, ...],
    subject: SourceSubject | None = None,
    policy_ref: SourcePolicyRef | None = None,
    run_id: str = "run-001",
) -> SourceAdmissionBundle:
    return SourceAdmissionBundle(
        schema_version=1,
        subject=subject or _subject(),
        items=items,
        declarations=declarations,
        reviews=reviews,
        policy_ref=policy_ref or _policy_ref(),
        collector_version="v1",
        collected_at="2026-09-22T00:00:00Z",
        producer="prod",
        run_id=run_id,
    )


def _review_for(bundle: SourceAdmissionBundle, item_ids: tuple[str, ...]) -> ReviewEvidence:
    return ReviewEvidence(
        review_id="rev-01",
        reviewer_identity_id=OWNER,
        item_ids=item_ids,
        inventory_digest=compute_inventory_digest(bundle),
        decision=ReviewDecision.APPROVED,
        rationale="Looks good",
        evidence_ref="rev-ref",
        evidence_sha256="5" * 64,
        reviewed_at="2026-09-22T01:00:00Z",
        superseded_by=None,
        revoked=False,
    )


def _context() -> SourceAdmissionEvaluationContext:
    return SourceAdmissionEvaluationContext(
        expected_subject=_subject(),
        expected_policy_ref=_policy_ref(),
        evaluator_version="v1",
        observed_at="2026-09-22T02:00:00Z",
        producer="eval",
        run_id="run-001",
    )


def test_adjacent_fully_complete_owner_authored_ai_generated_fixture_admitted() -> None:
    item = _item()
    dec = _declaration((item.item_id,), item.origins)
    bundle_partial = _bundle((item,), (dec,), ())
    rev = _review_for(bundle_partial, (item.item_id,))
    bundle = _bundle((item,), (dec,), (rev,))

    report = evaluate_source_admission(bundle, _policy(), _context())

    assert report.verdict is Verdict.ADMITTED
    assert len(report.item_decisions) == 1
    assert report.item_decisions[0].verdict is Verdict.ADMITTED
    assert not report.reason_codes
    assert report.evidence_complete is True


def test_alternate_valid_subject_policy_ref_run_id_or_policy_digest_invalid() -> None:
    item = _item()
    dec = _declaration((item.item_id,), item.origins)
    bundle_partial = _bundle((item,), (dec,), ())
    rev = _review_for(bundle_partial, (item.item_id,))

    policy = _policy()
    ctx = _context()

    # Mismatch subject
    alt_subject = deepcopy(ctx.expected_subject)
    alt_subject = SourceSubject(**{**alt_subject.model_dump(), "head_commit_sha1": "e" * 40})
    bundle = _bundle((item,), (dec,), (rev,), subject=alt_subject)
    report = evaluate_source_admission(bundle, policy, ctx)
    assert report.verdict is Verdict.INVALID
    assert ReasonCode.SNAPSHOT_MISMATCH in report.reason_codes

    # Mismatch run_id
    bundle = _bundle((item,), (dec,), (rev,), run_id="alt-run")
    report = evaluate_source_admission(bundle, policy, ctx)
    assert report.verdict is Verdict.INVALID
    assert ReasonCode.IDENTITY_MISMATCH in report.reason_codes

    # Mismatch policy ref
    alt_ref = deepcopy(ctx.expected_policy_ref)
    alt_ref = SourcePolicyRef(**{**alt_ref.model_dump(), "policy_sha256": "8" * 64})
    bundle = _bundle((item,), (dec,), (rev,), policy_ref=alt_ref)
    report = evaluate_source_admission(bundle, policy, ctx)
    assert report.verdict is Verdict.INVALID
    assert ReasonCode.DIGEST_MISMATCH in report.reason_codes


def test_empty_inventory_and_orphan_references_invalid() -> None:
    policy = _policy()
    ctx = _context()

    # Empty inventory
    bundle = _bundle((), (), ())
    report = evaluate_source_admission(bundle, policy, ctx)
    assert report.verdict is Verdict.INVALID
    assert ReasonCode.INCOMPLETE_INVENTORY in report.reason_codes

    # Orphan declaration/review refs
    item = _item()
    dec = _declaration(("missing-item",), item.origins)
    bundle_partial = _bundle((item,), (dec,), ())
    rev = _review_for(bundle_partial, ("missing-item",))
    bundle = _bundle((item,), (dec,), (rev,))

    report = evaluate_source_admission(bundle, policy, ctx)
    assert report.verdict is Verdict.INVALID
    assert ReasonCode.INCOMPLETE_INVENTORY in report.reason_codes


def test_stale_review_digest_revoked_or_unapproved_reviewer_invalid() -> None:
    item = _item()
    dec = _declaration((item.item_id,), item.origins)
    bundle_partial = _bundle((item,), (dec,), ())

    # Stale digest
    rev_stale = ReviewEvidence(
        **{
            **_review_for(bundle_partial, (item.item_id,)).model_dump(),
            "inventory_digest": "8" * 64,
        }
    )
    bundle = _bundle((item,), (dec,), (rev_stale,))
    report = evaluate_source_admission(bundle, _policy(), _context())
    assert report.verdict is Verdict.INVALID
    assert ReasonCode.DIGEST_MISMATCH in report.reason_codes

    # Revoked
    rev_revoked = ReviewEvidence(
        **{**_review_for(bundle_partial, (item.item_id,)).model_dump(), "revoked": True}
    )
    bundle = _bundle((item,), (dec,), (rev_revoked,))
    report = evaluate_source_admission(bundle, _policy(), _context())
    assert report.verdict is Verdict.INVALID
    assert ReasonCode.UNTRUSTED_REVIEW in report.reason_codes

    # Unapproved reviewer
    rev_unapproved = ReviewEvidence(
        **{
            **_review_for(bundle_partial, (item.item_id,)).model_dump(),
            "reviewer_identity_id": "unapproved",
        }
    )
    bundle = _bundle((item,), (dec,), (rev_unapproved,))
    report = evaluate_source_admission(bundle, _policy(), _context())
    assert report.verdict is Verdict.INVALID
    assert ReasonCode.UNTRUSTED_REVIEW in report.reason_codes


def test_missing_declaration_missing_review_incomplete_ai_facts_never_admitted() -> None:
    item = _item()
    dec = _declaration((item.item_id,), item.origins)
    bundle_partial = _bundle((item,), (dec,), ())
    rev = _review_for(bundle_partial, (item.item_id,))
    policy = _policy()
    ctx = _context()

    # Missing declaration
    bundle = _bundle((item,), (), (rev,))
    report = evaluate_source_admission(bundle, policy, ctx)
    assert report.verdict is Verdict.REVIEW_REQUIRED
    assert ReasonCode.PROVENANCE_AMBIGUOUS in report.reason_codes

    # Missing review
    bundle = _bundle((item,), (dec,), ())
    report = evaluate_source_admission(bundle, policy, ctx)
    assert report.verdict is Verdict.REVIEW_REQUIRED
    assert ReasonCode.REVIEW_MISSING in report.reason_codes

    # Incomplete AI facts (missing mandatory fact)
    ai_facts = [f for f in dec.ai_facts if f.fact != AIFact.MODEL_IDENTIFIER]
    dec_bad_ai = OriginDeclaration(**{**dec.model_dump(), "ai_facts": tuple(ai_facts)})
    bundle = _bundle((item,), (dec_bad_ai,), (rev,))
    report = evaluate_source_admission(bundle, policy, ctx)
    assert report.verdict is Verdict.REVIEW_REQUIRED
    assert ReasonCode.REQUIRED_OBLIGATION_UNSATISFIED in report.reason_codes

    # Disallowed unavailable fact
    ai_facts2 = [
        AIFactEvidence(
            fact=f.fact,
            availability=Availability.UNAVAILABLE,
            value=None,
            evidence_ref=None,
            evidence_sha256=None,
        )
        if f.fact == AIFact.MODEL_IDENTIFIER
        else f
        for f in dec.ai_facts
    ]
    dec_bad_unavail = OriginDeclaration(**{**dec.model_dump(), "ai_facts": tuple(ai_facts2)})
    bundle = _bundle((item,), (dec_bad_unavail,), (rev,))
    report = evaluate_source_admission(bundle, policy, ctx)
    assert report.verdict is Verdict.REVIEW_REQUIRED
    assert ReasonCode.REQUIRED_OBLIGATION_UNSATISFIED in report.reason_codes

    # Non-admissible origins
    item_bad = SourceItem(**{**item.model_dump(), "origins": (OriginKind.UNKNOWN,)})
    dec_bad_orig = OriginDeclaration(
        **{**dec.model_dump(), "item_ids": (item_bad.item_id,), "origins": (OriginKind.UNKNOWN,)}
    )
    bundle_partial2 = _bundle((item_bad,), (dec_bad_orig,), ())
    rev2 = _review_for(bundle_partial2, (item_bad.item_id,))
    bundle = _bundle((item_bad,), (dec_bad_orig,), (rev2,))
    report = evaluate_source_admission(bundle, policy, ctx)
    assert report.verdict is Verdict.REVIEW_REQUIRED
    assert ReasonCode.ORIGIN_UNKNOWN in report.reason_codes


def test_forbidden_processor_missing_mandatory_ai_obligation_rejected() -> None:
    item = _item(origins=(OriginKind.AI_GENERATED,))
    # Missing obligation ref ai-provider-tool-terms
    item = SourceItem(**{**item.model_dump(), "obligation_refs": ()})
    dec = _declaration((item.item_id,), item.origins)
    bundle_partial = _bundle((item,), (dec,), ())
    rev = _review_for(bundle_partial, (item.item_id,))
    bundle = _bundle((item,), (dec,), (rev,))

    report = evaluate_source_admission(bundle, _policy(), _context())
    # Fails mandatory ai obligation
    assert report.verdict is Verdict.REJECTED
    assert ReasonCode.REQUIRED_OBLIGATION_UNSATISFIED in report.reason_codes

    # Forbidden processor
    subj = SourceSubject(
        **{**_subject().model_dump(), "processor_profile": ProcessorProfile.EXTERNAL}
    )
    bundle_partial2 = _bundle((item,), (dec,), (), subject=subj)
    rev2 = _review_for(bundle_partial2, (item.item_id,))
    bundle = _bundle((item,), (dec,), (rev2,), subject=subj)
    ctx = SourceAdmissionEvaluationContext(**{**_context().model_dump(), "expected_subject": subj})
    report = evaluate_source_admission(bundle, _policy(), ctx)
    assert report.verdict is Verdict.REJECTED
    assert ReasonCode.DISCLOSURE_FORBIDDEN in report.reason_codes


def test_every_item_receives_exactly_one_decision_and_aggregate_precedence() -> None:
    item1 = _item("item-1")
    item2 = _item("item-2")
    dec = _declaration((item1.item_id, item2.item_id), item1.origins)
    bundle_partial = _bundle((item1, item2), (dec,), ())

    # Review only covers item1, so item2 is REVIEW_REQUIRED
    rev = _review_for(bundle_partial, (item1.item_id,))
    bundle = _bundle((item1, item2), (dec,), (rev,))
    report = evaluate_source_admission(bundle, _policy(), _context())

    assert len(report.item_decisions) == 2
    assert {d.item_id for d in report.item_decisions} == {"item-1", "item-2"}

    item1_verdict = next(d.verdict for d in report.item_decisions if d.item_id == "item-1")
    item2_verdict = next(d.verdict for d in report.item_decisions if d.item_id == "item-2")
    assert item1_verdict is Verdict.ADMITTED
    assert item2_verdict is Verdict.REVIEW_REQUIRED

    # Aggregate precedence: REVIEW_REQUIRED > ADMITTED
    assert report.verdict is Verdict.REVIEW_REQUIRED


def test_digests_equal_codec_recomputation_and_report_validates() -> None:
    item = _item()
    dec = _declaration((item.item_id,), item.origins)
    bundle_partial = _bundle((item,), (dec,), ())
    rev = _review_for(bundle_partial, (item.item_id,))
    bundle = _bundle((item,), (dec,), (rev,))
    report = evaluate_source_admission(bundle, _policy(), _context())

    assert report.inventory_digest == compute_inventory_digest(bundle)
    assert report.declarations_digest == compute_declarations_digest(bundle)
    assert report.reviews_digest == compute_reviews_digest(bundle)
    assert report.report_digest == compute_report_digest(report)

    # Validate through parse_report_bytes
    parsed = parse_report_bytes(canonical_report_bytes(report))
    assert parsed.report_digest == report.report_digest


def test_changing_semantic_field_invalidates_report_digest() -> None:
    item = _item()
    dec = _declaration((item.item_id,), item.origins)
    bundle_partial = _bundle((item,), (dec,), ())
    rev = _review_for(bundle_partial, (item.item_id,))
    bundle = _bundle((item,), (dec,), (rev,))
    report = evaluate_source_admission(bundle, _policy(), _context())

    # Change verdict manually without recomputing digest
    tampered = SourceAdmissionReport(**{**report.model_dump(), "verdict": Verdict.REJECTED})
    # Cannot parse due to mismatched digest
    with pytest.raises(ValueError, match="SOURCE_WIRE_REPORT_DIGEST_MISMATCH"):
        parse_report_bytes(canonical_report_bytes(tampered))


def test_evaluator_signature_has_no_report_input_and_bypassing_impossible() -> None:
    sig = inspect.signature(evaluate_source_admission)
    assert "report" not in sig.parameters
    for param in sig.parameters.values():
        assert param.annotation is not SourceAdmissionReport

    # Because evaluate_source_admission computes everything from bundle, policy, context,
    # you cannot feed it a forged report.


def test_evaluator_isolation() -> None:
    evaluator_path = ROOT / "src" / "blackbread" / "governance" / "source_admission_evaluator.py"
    assert evaluator_path.exists()

    # Check that no other production module imports evaluator
    for path in (ROOT / "src" / "blackbread").rglob("*.py"):
        if path == evaluator_path:
            continue
        text = path.read_text(encoding="utf-8")
        assert "source_admission_evaluator" not in text


def test_checked_in_policy_digest_remains_unchanged() -> None:
    assert compute_policy_digest(_policy()) == KNOWN_DIGEST
