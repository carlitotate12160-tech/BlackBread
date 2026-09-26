"""Adversarial proofs for the pure deterministic source-admission evaluator."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

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
    ApprovedIdentity,
    IdentityRole,
    OriginKind,
    PermissionGrant,
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
RC = ReasonCode
V = Verdict
_SUBJECT_D: dict[str, Any] = {
    "repository": "carlitotate12160-tech/BlackBread",
    "base_commit_sha1": "a" * 40,
    "head_commit_sha1": "b" * 40,
    "base_tree_sha1": "c" * 40,
    "head_tree_sha1": "d" * 40,
    "use_profile": UseProfile.ENGINEERING_REVIEW,
    "processor_profile": ProcessorProfile.LOCAL_ONLY,
    "coverage_description": "Full exact coverage",
}
_ITEM_D: dict[str, Any] = {
    "change_kind": ChangeKind.MODIFIED,
    "base_path_b64": "c3JjL2V4YW1wbGUucHk=",
    "head_path_b64": "c3JjL2V4YW1wbGUucHk=",
    "base_object_kind": ObjectKind.BLOB,
    "head_object_kind": ObjectKind.BLOB,
    "base_mode": "100644",
    "head_mode": "100644",
    "base_object_sha1": "a" * 40,
    "head_object_sha1": "b" * 40,
    "base_content_sha256": "1" * 64,
    "head_content_sha256": "2" * 64,
    "origins": (OriginKind.REPOSITORY_AUTHORED, OriginKind.AI_GENERATED),
    "lineage_refs": ("lineage-01",),
    "dependency_refs": ("dep-01",),
    "obligation_refs": ("ai-provider-tool-terms",),
}
_DECL_D: dict[str, Any] = {
    "declaration_id": "dec-01",
    "content_sha256s": ("2" * 64,),
    "contributor_identity_id": OWNER,
    "external_references": ("ext-01",),
    "license_expression": None,
    "declaration_evidence_ref": "dec-ref",
    "declaration_evidence_sha256": "4" * 64,
}
_REF_D: dict[str, Any] = {
    "source_commit_sha1": "e" * 40,
    "source_blob_sha1": "f" * 40,
    "use_profile": UseProfile.ENGINEERING_REVIEW,
    "processor_profile": ProcessorProfile.LOCAL_ONLY,
}
_REV_D: dict[str, Any] = {
    "review_id": "rev-01",
    "reviewer_identity_id": OWNER,
    "decision": ReviewDecision.APPROVED,
    "rationale": "Looks good",
    "evidence_ref": "rev-ref",
    "evidence_sha256": "5" * 64,
    "reviewed_at": "2026-09-22T01:00:00Z",
    "superseded_by": None,
    "revoked": False,
}
_BUNDLE_D: dict[str, Any] = {
    "schema_version": 1,
    "collector_version": "v1",
    "collected_at": "2026-09-22T00:00:00Z",
    "producer": "prod",
    "run_id": "run-001",
}
_CONTEXT_D: dict[str, Any] = {
    "evaluator_version": "v1",
    "observed_at": "2026-09-22T02:00:00Z",
    "producer": "eval",
    "run_id": "run-001",
}


def _mutate[M: BaseModel](model: M, **overrides: object) -> M:
    return model.model_validate({**model.model_dump(), **overrides})


def _policy() -> SourceAdmissionPolicy:
    return parse_policy_bytes(POLICY_PATH.read_bytes())


def _pmut(**over: object) -> SourceAdmissionPolicy:
    return _mutate(_policy(), **over)


def _subject(**over: object) -> SourceSubject:
    return SourceSubject.model_validate({**_SUBJECT_D, **over})


def _policy_ref(policy: SourceAdmissionPolicy | None = None) -> SourcePolicyRef:
    p = policy or _policy()
    base = {
        **_REF_D,
        "policy_id": p.policy_id,
        "policy_version": p.policy_version,
        "retention": p.retention,
    }
    return SourcePolicyRef.model_validate({**base, "policy_sha256": compute_policy_digest(p)})


def _item(item_id: str = "item-01", **over: object) -> SourceItem:
    return SourceItem.model_validate({**_ITEM_D, "item_id": item_id, **over})


def _fact(fact: AIFact, available: bool = True) -> AIFactEvidence:
    return AIFactEvidence(
        fact=fact,
        availability=Availability.AVAILABLE if available else Availability.UNAVAILABLE,
        value="v" if available else None,
        evidence_ref="r" if available else None,
        evidence_sha256="3" * 64 if available else None,
    )


_AI_FACTS = tuple(_fact(f, f is not AIFact.MODEL_VERSION) for f in AIFact)


def _declaration(
    item_ids: tuple[str, ...], origins: tuple[OriginKind, ...], **over: object
) -> OriginDeclaration:
    over.setdefault("ai_facts", _AI_FACTS)
    return OriginDeclaration.model_validate(
        {**_DECL_D, "item_ids": item_ids, "origins": origins, **over}
    )


def _bundle(
    items: tuple[SourceItem, ...],
    declarations: tuple[OriginDeclaration, ...],
    reviews: tuple[ReviewEvidence, ...],
    **over: object,
) -> SourceAdmissionBundle:
    over.setdefault("subject", _subject())
    over.setdefault("policy_ref", _policy_ref())
    over.update(items=items, declarations=declarations, reviews=reviews)
    return SourceAdmissionBundle.model_validate({**_BUNDLE_D, **over})


def _review_for(
    bundle: SourceAdmissionBundle, item_ids: tuple[str, ...], **over: object
) -> ReviewEvidence:
    over.setdefault("inventory_digest", compute_inventory_digest(bundle))
    return ReviewEvidence.model_validate({**_REV_D, "item_ids": item_ids, **over})


def _context(
    policy: SourceAdmissionPolicy | None = None,
    subject: SourceSubject | None = None,
    **over: object,
) -> SourceAdmissionEvaluationContext:
    over.setdefault("expected_subject", subject or _subject())
    over.setdefault("expected_policy_ref", _policy_ref(policy))
    return SourceAdmissionEvaluationContext.model_validate({**_CONTEXT_D, **over})


def _assemble(item: SourceItem, dec: OriginDeclaration, **over: object) -> SourceAdmissionBundle:
    partial = _bundle((item,), (dec,), (), **over)
    return _bundle((item,), (dec,), (_review_for(partial, (item.item_id,)),), **over)


def _eval(
    bundle: SourceAdmissionBundle,
    policy: SourceAdmissionPolicy | None = None,
    ctx: SourceAdmissionEvaluationContext | None = None,
) -> SourceAdmissionReport:
    policy = policy or _policy()
    return evaluate_source_admission(bundle, policy, ctx or _context(policy, bundle.subject))


def _expect(bundle: SourceAdmissionBundle, verdict: Verdict, code: ReasonCode, **kw: Any) -> None:
    report = _eval(bundle, **kw)
    assert report.verdict is verdict
    assert code in report.reason_codes


def _grant(**over: object) -> PermissionGrant:
    return _mutate(_policy().permission_grants[0], **over)


def _bmut(**over: object) -> SourceAdmissionBundle:
    return _mutate(_VALID, **over)


def _dec_mut(**over: object) -> OriginDeclaration:
    return _mutate(_DEC, **over)


def _rev_mut(**over: object) -> ReviewEvidence:
    return _mutate(_REV, **over)


def _case(
    bundle: SourceAdmissionBundle, verdict: Verdict, code: ReasonCode, **kw: Any
) -> tuple[SourceAdmissionBundle, dict[str, Any], Verdict, ReasonCode]:
    return (bundle, kw, verdict, code)


_ITEM = _item()
_DEC = _declaration((_ITEM.item_id,), _ITEM.origins)
_REV = _review_for(_bundle((_ITEM,), (_DEC,), ()), (_ITEM.item_id,))
_VALID = _bundle((_ITEM,), (_DEC,), (_REV,))
_CTX = _context()
_NON_ADMISSIBLE_ORIGINS = tuple(
    set(OriginKind) - {OriginKind.REPOSITORY_AUTHORED, OriginKind.AI_GENERATED}
)
_REF_FORGERIES: dict[str, Any] = {
    "policy_id": "forged-policy",
    "policy_version": "999",
    "use_profile": UseProfile.PUBLIC_DISTRIBUTION,
    "processor_profile": ProcessorProfile.EXTERNAL,
}
AMBIGUOUS = RC.PROVENANCE_AMBIGUOUS
UNSAT = RC.REQUIRED_OBLIGATION_UNSATISFIED
INCOMPLETE = RC.INCOMPLETE_INVENTORY
ID_MISMATCH = RC.IDENTITY_MISMATCH
DIGEST_MISMATCH = RC.DIGEST_MISMATCH
SNAP_MISMATCH = RC.SNAPSHOT_MISMATCH
NO_POLICY = RC.POLICY_UNAVAILABLE
UNTRUSTED = RC.UNTRUSTED_REVIEW
_REQ_FACTS = sorted(_policy().ai_required_facts)
_AI_FACT_CASES = [(f, "omit") for f in _REQ_FACTS] + [
    (f, "unavail") for f in _REQ_FACTS if f not in _policy().ai_allowed_unavailable_facts
]
_TP_SCOPE: dict[str, Any] = {"material_scope": (OriginKind.THIRD_PARTY_SOURCE,)}
_GRANT_DEFECTS: list[tuple[dict[str, Any], Verdict]] = [
    ({"repository": "other/repo"}, V.REJECTED),
    ({"permitted_use": UseProfile.PUBLIC_DISTRIBUTION}, V.INVALID),
    ({"merge_permission": True}, V.INVALID),
    ({"capability_permission": True}, V.INVALID),
    ({"target_permission": True}, V.INVALID),
    ({"waives_third_party_rights": True}, V.INVALID),
    ({"grantor_identity_id": "ghost:nobody"}, V.INVALID),
    (_TP_SCOPE, V.INVALID),
    ({**_TP_SCOPE, "owner_controlled_rights_only": False}, V.REJECTED),
]
_CONTRIB_IDENTITY = ApprovedIdentity(
    identity_id="github:contrib", roles=(IdentityRole.REPOSITORY_CONTRIBUTOR,)
)
_CONTRIB_POLICY = _pmut(approved_identities=(*_policy().approved_identities, _CONTRIB_IDENTITY))
_DANGLE_RULES = tuple(
    _mutate(r, grant_id="dangling") if r.grant_id else r for r in _policy().origin_rules
)
_NO_AI_RULES = tuple(r for r in _policy().origin_rules if r.origin is not OriginKind.AI_GENERATED)
_DUP_POLICY = SourceAdmissionPolicy.model_construct(
    **{n: getattr(_p := _policy(), n) for n in SourceAdmissionPolicy.model_fields}
    | {"origin_rules": (*_p.origin_rules, _p.origin_rules[0])}
)
_ORPHAN_DEC = _declaration(("missing-item",), _ITEM.origins)
_ORPHAN_REV = _review_for(_bundle((_ITEM,), (_ORPHAN_DEC,), ()), ("missing-item",))
_BAD_DIGEST_REF = _mutate(_policy_ref(), policy_sha256="8" * 64)
_ALT_SUBJECT = _subject(head_commit_sha1="e" * 40)
_EXT_SUBJECT = _subject(processor_profile=ProcessorProfile.EXTERNAL)
_EXT_REF = _mutate(_policy_ref(), processor_profile=ProcessorProfile.EXTERNAL)
_EXT_BUNDLE = _assemble(_ITEM, _DEC, subject=_EXT_SUBJECT, policy_ref=_EXT_REF)
_EXT_CTX = _context(subject=_EXT_SUBJECT, expected_policy_ref=_EXT_REF)
_EXT_POLICY = _pmut(
    processor_profile=ProcessorProfile.EXTERNAL, external_processors_forbidden=False
)
_EXT_POLICY_REF = _policy_ref(_EXT_POLICY)
_GHOST_BUNDLE = _assemble(_ITEM, _dec_mut(contributor_identity_id="ghost:unapproved"))
_NO_CONTRIB_BUNDLE = _assemble(_ITEM, _dec_mut(contributor_identity_id=None))
_CONTRIB_REF = _policy_ref(_CONTRIB_POLICY)
_CONTRIB_BUNDLE = _assemble(
    _ITEM, _dec_mut(contributor_identity_id="github:contrib"), policy_ref=_CONTRIB_REF
)
_SUBSET_BUNDLE = _assemble(_ITEM, _dec_mut(origins=(OriginKind.REPOSITORY_AUTHORED,)))
_SUPERSET_BUNDLE = _assemble(_ITEM, _dec_mut(origins=(*_ITEM.origins, OriginKind.VENDORED_SOURCE)))
_FORBID_OBL_ITEM = _item(obligation_refs=("ai-provider-tool-terms", "target-use"))
_STALE_REV = _rev_mut(inventory_digest="8" * 64)
_GHOST_REV = _rev_mut(reviewer_identity_id="ghost")
_CONFLICT_BUNDLE = _bundle(
    (_ITEM,), (_DEC, _dec_mut(declaration_id="d2", contributor_identity_id="gh:o")), (_REV,)
)
_FAIL_CASES = [
    _case(_bundle((), (), ()), V.INVALID, INCOMPLETE),
    _case(_bundle((_ITEM,), (_ORPHAN_DEC,), (_ORPHAN_REV,)), V.INVALID, INCOMPLETE),
    _case(_bundle((_ITEM,), (), (_REV,)), V.REVIEW_REQUIRED, AMBIGUOUS),
    _case(_bundle((_ITEM,), (_DEC,), ()), V.REVIEW_REQUIRED, RC.REVIEW_MISSING),
    _case(_bmut(subject=_ALT_SUBJECT), V.INVALID, SNAP_MISMATCH, ctx=_CTX),
    _case(_bmut(run_id="alt-run"), V.INVALID, ID_MISMATCH, ctx=_CTX),
    _case(_bmut(policy_ref=_BAD_DIGEST_REF), V.INVALID, DIGEST_MISMATCH, ctx=_CTX),
    _case(_VALID, V.INVALID, NO_POLICY, policy=_pmut(permission_grants=())),
    _case(_VALID, V.INVALID, NO_POLICY, policy=_pmut(origin_rules=_DANGLE_RULES)),
    _case(_VALID, V.INVALID, NO_POLICY, policy=_pmut(origin_rules=_NO_AI_RULES)),
    _case(_VALID, V.INVALID, NO_POLICY, policy=_DUP_POLICY),
    _case(_EXT_BUNDLE, V.REJECTED, RC.DISCLOSURE_FORBIDDEN, ctx=_EXT_CTX),
    _case(
        _bmut(policy_ref=_EXT_POLICY_REF),
        V.REJECTED,
        RC.DISCLOSURE_FORBIDDEN,
        policy=_EXT_POLICY,
    ),
    _case(_GHOST_BUNDLE, V.REVIEW_REQUIRED, AMBIGUOUS),
    _case(_NO_CONTRIB_BUNDLE, V.REVIEW_REQUIRED, AMBIGUOUS),
    _case(_CONTRIB_BUNDLE, V.REVIEW_REQUIRED, AMBIGUOUS, policy=_CONTRIB_POLICY),
    _case(_CONFLICT_BUNDLE, V.REVIEW_REQUIRED, AMBIGUOUS),
    _case(_SUBSET_BUNDLE, V.INVALID, AMBIGUOUS),
    _case(_SUPERSET_BUNDLE, V.INVALID, AMBIGUOUS),
    _case(_assemble(_FORBID_OBL_ITEM, _DEC), V.REJECTED, UNSAT),
    _case(_assemble(_item(obligation_refs=()), _DEC), V.REJECTED, UNSAT),
    _case(_bundle((_ITEM,), (_DEC,), (_STALE_REV,)), V.INVALID, DIGEST_MISMATCH),
    _case(_bundle((_ITEM,), (_DEC,), (_rev_mut(revoked=True),)), V.INVALID, UNTRUSTED),
    _case(_bundle((_ITEM,), (_DEC,), (_rev_mut(superseded_by="rev-99"),)), V.INVALID, UNTRUSTED),
    _case(_bundle((_ITEM,), (_DEC,), (_GHOST_REV,)), V.INVALID, UNTRUSTED),
]


@pytest.mark.parametrize(("bundle", "kw", "verdict", "code"), _FAIL_CASES)
def test_fail_closed_matrix(bundle, kw, verdict, code):
    _expect(bundle, verdict, code, **kw)


def test_adjacent_valid_owner_authored_ai_fixture_admitted():
    report = _eval(_VALID)
    assert report.verdict is V.ADMITTED and report.item_decisions[0].verdict is V.ADMITTED
    assert not report.reason_codes and report.evidence_complete


@pytest.mark.parametrize("origin", _NON_ADMISSIBLE_ORIGINS)
def test_non_admissible_origin_never_admits_even_with_approved_review(origin):
    item = _item(origins=(origin,))
    dec = _declaration((item.item_id,), item.origins)
    _expect(_assemble(item, dec), V.REVIEW_REQUIRED, RC.ORIGIN_UNKNOWN)


@pytest.mark.parametrize(("overrides", "expected"), _GRANT_DEFECTS)
def test_incompatible_or_overreaching_grant_fails_closed(overrides, expected):
    policy = _pmut(permission_grants=(_grant(**overrides),))
    bundle = _bmut(policy_ref=_policy_ref(policy))
    assert _eval(bundle, policy=policy).verdict is expected


@pytest.mark.parametrize(("fact", "mode"), _AI_FACT_CASES)
def test_required_ai_fact_defect_never_admits(fact, mode):
    if mode == "omit":
        facts = tuple(f for f in _DEC.ai_facts if f.fact is not fact)
    else:
        facts = tuple(_fact(f.fact, False) if f.fact is fact else f for f in _DEC.ai_facts)
    _expect(_assemble(_ITEM, _mutate(_DEC, ai_facts=facts)), V.REVIEW_REQUIRED, UNSAT)


@pytest.mark.parametrize("field", (*_REF_FORGERIES, "retention"))
def test_forged_policy_ref_field_invalid_even_with_authentic_digest(field):
    value = _REF_FORGERIES.get(field) or _mutate(_policy().retention, metadata_report_days=99)
    forged = _mutate(_VALID.policy_ref, **{field: value})
    ctx = _context(expected_policy_ref=forged)
    _expect(_bmut(policy_ref=forged), V.INVALID, ID_MISMATCH, ctx=ctx)


def test_deleted_item_binds_base_digest():
    null_head = {k: None for k in _ITEM_D if k.startswith("head_")}
    item = _item(change_kind=ChangeKind.DELETED, **null_head)
    dec = _declaration((item.item_id,), item.origins)
    _expect(_assemble(item, dec), V.INVALID, RC.SNAPSHOT_MISMATCH)
    dec_ok = _mutate(dec, content_sha256s=("1" * 64,))
    assert _eval(_assemble(item, dec_ok)).verdict is V.ADMITTED


def test_verdict_dominance():
    bad = _item("bad", obligation_refs=("ai-provider-tool-terms", "target-use"))
    items = (_item("good"), _item("unreviewed"), bad)
    decs = (
        _declaration(("good", "unreviewed"), items[0].origins),
        _declaration(("bad",), bad.origins, declaration_id="dec-02"),
    )
    rev = _review_for(_bundle(items, decs, ()), ("good",))
    bundle = _bundle(items, decs, (rev,))
    report = _eval(bundle)
    expected = {"good": V.ADMITTED, "unreviewed": V.REVIEW_REQUIRED, "bad": V.REJECTED}
    assert {d.item_id: d.verdict for d in report.item_decisions} == expected
    assert report.verdict is V.REJECTED
    forged = _mutate(bundle.policy_ref, policy_id="forged")
    ctx = _context(expected_policy_ref=forged)
    _expect(_mutate(bundle, policy_ref=forged), V.INVALID, ID_MISMATCH, ctx=ctx)


def test_digests_match_codec_and_report_roundtrip():
    report = _eval(_VALID)
    assert report.inventory_digest == compute_inventory_digest(_VALID)
    assert report.declarations_digest == compute_declarations_digest(_VALID)
    assert report.reviews_digest == compute_reviews_digest(_VALID)
    assert report.report_digest == compute_report_digest(report)
    assert parse_report_bytes(canonical_report_bytes(report)).report_digest == report.report_digest
    assert compute_policy_digest(_policy()) == KNOWN_DIGEST


def test_evaluator_signature_admits_no_report_input_and_stays_isolated():
    sig = inspect.signature(evaluate_source_admission)
    assert "report" not in sig.parameters
    assert all(p.annotation is not SourceAdmissionReport for p in sig.parameters.values())
    for path in (ROOT / "src" / "blackbread").rglob("*.py"):
        if path.name != "source_admission_evaluator.py":
            assert "source_admission_evaluator" not in path.read_text(encoding="utf-8")
