"""Semantic model proofs for source-admission inputs and outputs."""

from __future__ import annotations

import ast
import base64
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from blackbread.governance import source_admission_contracts as contracts
from blackbread.governance.source_admission_contracts import (
    AIFactEvidence,
    Availability,
    ChangeKind,
    ItemAdmissionDecision,
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
from blackbread.governance.source_admission_policy import (
    AIFact,
    OriginKind,
    ProcessorProfile,
    UseProfile,
    parse_policy_bytes,
)

ROOT = Path(__file__).resolve().parents[2]
SHA1_A, SHA1_B = "a" * 40, "b" * 40
SHA1_C, SHA1_D = "c" * 40, "d" * 40
SHA256_A, SHA256_B = "1" * 64, "2" * 64
SHA256_C, SHA256_D = "3" * 64, "4" * 64
UNICODE_TIMESTAMP = "".join(
    chr(0x0660 + int(character)) if character.isdigit() else character
    for character in "2026-09-21T03:02:00Z"
)


def _path(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _subject() -> SourceSubject:
    return SourceSubject(
        repository="carlitotate12160-tech/BlackBread",
        base_commit_sha1=SHA1_A,
        head_commit_sha1=SHA1_B,
        base_tree_sha1=SHA1_C,
        head_tree_sha1=SHA1_D,
        use_profile=UseProfile.ENGINEERING_REVIEW,
        processor_profile=ProcessorProfile.LOCAL_ONLY,
        coverage_description="Exact base-to-head inventory plus declared context.",
    )


def _item_values() -> dict[str, Any]:
    return {
        "item_id": "item-source",
        "change_kind": ChangeKind.MODIFIED,
        "base_path_b64": _path(b"src/example.py"),
        "head_path_b64": _path(b"src/example.py"),
        "base_object_kind": ObjectKind.BLOB,
        "head_object_kind": ObjectKind.BLOB,
        "base_mode": "100644",
        "head_mode": "100644",
        "base_object_sha1": SHA1_A,
        "head_object_sha1": SHA1_B,
        "base_content_sha256": SHA256_A,
        "head_content_sha256": SHA256_B,
        "origins": (OriginKind.AI_GENERATED, OriginKind.REPOSITORY_AUTHORED),
        "lineage_refs": ("lineage:owner",),
        "dependency_refs": (),
        "obligation_refs": ("ai-provider-tool-terms",),
    }


def _item(**changes: Any) -> SourceItem:
    return SourceItem(**(_item_values() | changes))


def _ai_fact() -> AIFactEvidence:
    return AIFactEvidence(
        fact=AIFact.MODEL_IDENTIFIER,
        availability=Availability.AVAILABLE,
        value="gpt-5.6",
        evidence_ref="run:model",
        evidence_sha256=SHA256_C,
    )


def _declaration(identifier: str = "declaration-source") -> OriginDeclaration:
    return OriginDeclaration(
        declaration_id=identifier,
        item_ids=("item-source",),
        content_sha256s=(SHA256_A, SHA256_B),
        origins=(OriginKind.AI_GENERATED, OriginKind.REPOSITORY_AUTHORED),
        contributor_identity_id="github:carlitotate12160-tech",
        ai_facts=(_ai_fact(),),
        external_references=(),
        license_expression=None,
        declaration_evidence_ref="run:declaration",
        declaration_evidence_sha256=SHA256_A,
    )


def _review(identifier: str = "review-source") -> ReviewEvidence:
    return ReviewEvidence(
        review_id=identifier,
        reviewer_identity_id="github:carlitotate12160-tech",
        item_ids=("item-source",),
        inventory_digest=SHA256_B,
        decision=ReviewDecision.APPROVED,
        rationale="Exact-scope engineering review.",
        evidence_ref="github:review:1",
        evidence_sha256=SHA256_C,
        reviewed_at="2026-09-21T03:00:00Z",
        superseded_by=None,
        revoked=False,
    )


def _policy_ref() -> SourcePolicyRef:
    return SourcePolicyRef(
        policy_id="blackbread-source-admission",
        policy_version="1",
        source_commit_sha1=SHA1_A,
        source_blob_sha1=SHA1_B,
        policy_sha256=SHA256_D,
        use_profile=UseProfile.ENGINEERING_REVIEW,
        processor_profile=ProcessorProfile.LOCAL_ONLY,
        retention=parse_policy_bytes(
            (ROOT / "config" / "source-admission-policy.json").read_bytes()
        ).retention,
    )


def _bundle(
    *,
    items: tuple[SourceItem, ...] | None = None,
    declarations: tuple[OriginDeclaration, ...] | None = None,
    reviews: tuple[ReviewEvidence, ...] | None = None,
) -> SourceAdmissionBundle:
    return SourceAdmissionBundle(
        schema_version=1,
        subject=_subject(),
        items=items or (_item(),),
        declarations=declarations or (_declaration(),),
        reviews=reviews or (_review(),),
        policy_ref=_policy_ref(),
        collector_version="collector-v1",
        collected_at="2026-09-21T03:01:00Z",
        producer="caller-controlled-producer",
        run_id="run-001",
    )


def _decision(identifier: str = "item-source") -> ItemAdmissionDecision:
    return ItemAdmissionDecision(
        item_id=identifier,
        verdict=Verdict.ADMITTED,
        reason_codes=(),
        evidence_complete=True,
    )


def _report(*, decisions: tuple[ItemAdmissionDecision, ...] | None = None) -> SourceAdmissionReport:
    return SourceAdmissionReport(
        schema_version=1,
        subject=_subject(),
        inventory_digest=SHA256_A,
        declarations_digest=SHA256_B,
        reviews_digest=SHA256_C,
        policy_ref=_policy_ref(),
        evaluator_version="evaluator-v1",
        item_decisions=decisions or (_decision(),),
        verdict=Verdict.ADMITTED,
        reason_codes=(),
        evidence_complete=True,
        coverage_description="Only the represented base-to-head inventory.",
        observed_at="2026-09-21T03:02:00Z",
        producer="caller-controlled-producer",
        run_id="run-001",
        report_digest="0" * 64,
    )


def test_adjacent_valid_construction_covers_every_public_model() -> None:
    models = (_subject(), _item(), _ai_fact(), _declaration(), _review())
    models += (_policy_ref(), _bundle(), _decision(), _report())

    assert all(model.model_config["frozen"] for model in models)
    assert all(model.model_config["strict"] for model in models)
    assert all(model.model_config["extra"] == "forbid" for model in models)
    with pytest.raises(ValidationError):
        _subject().repository = "changed"  # type: ignore[misc]


def test_missing_unknown_fields_and_coercions_are_rejected() -> None:
    raw = _report().model_dump(mode="json")
    del raw["producer"]
    with pytest.raises(ValidationError):
        SourceAdmissionReport.model_validate_json(json.dumps(raw))
    raw = _report().model_dump(mode="json") | {"unknown": True}
    with pytest.raises(ValidationError):
        SourceAdmissionReport.model_validate_json(json.dumps(raw))

    raw_bundle = _bundle().model_dump(mode="json")
    for version in (True, "1", 1.0, None, 2):
        raw_bundle["schema_version"] = version
        with pytest.raises(ValidationError):
            SourceAdmissionBundle.model_validate_json(json.dumps(raw_bundle))


@pytest.mark.parametrize("value", ["", "   ", "x" * 501])
def test_required_text_is_bounded_and_non_blank(value: str) -> None:
    with pytest.raises(ValidationError):
        SourceSubject.model_validate(_subject().model_dump() | {"repository": value})


@pytest.mark.parametrize("value", ["A" * 40, "a" * 39, "g" * 40, 7])
def test_hashes_require_exact_lowercase_hex(value: Any) -> None:
    with pytest.raises(ValidationError):
        SourceSubject.model_validate(_subject().model_dump() | {"base_commit_sha1": value})
    with pytest.raises(ValidationError):
        SourceAdmissionReport.model_validate(_report().model_dump() | {"report_digest": value})


@pytest.mark.parametrize(
    ("factory", "field"),
    [(_review, "reviewed_at"), (_bundle, "collected_at"), (_report, "observed_at")],
)
@pytest.mark.parametrize("value", [UNICODE_TIMESTAMP, "2026-99-99T25:61:61Z"])
def test_timestamps_require_ascii_and_real_utc_instants(
    factory: Any, field: str, value: str
) -> None:
    model = factory()
    with pytest.raises(ValidationError):
        type(model).model_validate(model.model_dump() | {field: value})


def test_timestamps_accept_adjacent_valid_controls_including_leap_date() -> None:
    value = "2024-02-29T23:59:59Z"
    timestamp_fields = (
        (_review, "reviewed_at"),
        (_bundle, "collected_at"),
        (_report, "observed_at"),
    )
    for factory, field in timestamp_fields:
        model = factory()
        validated = type(model).model_validate(model.model_dump() | {field: value})
        assert getattr(validated, field) == value


def test_set_members_are_unique_and_normalized_but_semantic_arrays_keep_order() -> None:
    with pytest.raises(ValidationError):
        _item(lineage_refs=("same", "same"))
    reordered = _item(
        origins=(OriginKind.REPOSITORY_AUTHORED, OriginKind.AI_GENERATED),
        lineage_refs=("z", "a"),
    )
    assert reordered.origins == (OriginKind.AI_GENERATED, OriginKind.REPOSITORY_AUTHORED)
    assert reordered.lineage_refs == ("a", "z")

    first, second = _item(), _item(item_id="item-second")
    assert _bundle(items=(second, first)).items == (second, first)


def _without_side(values: dict[str, Any], prefix: str) -> None:
    for name in tuple(values):
        if name.startswith(prefix):
            values[name] = None


def test_every_change_kind_has_one_valid_shape_and_adjacent_invalid_shapes() -> None:
    added = _item_values() | {"change_kind": ChangeKind.ADDED}
    _without_side(added, "base_")
    deleted = _item_values() | {"change_kind": ChangeKind.DELETED}
    _without_side(deleted, "head_")
    renamed = _item_values() | {
        "change_kind": ChangeKind.RENAMED,
        "head_path_b64": _path(b"src/renamed.py"),
    }
    assert SourceItem(**added).change_kind is ChangeKind.ADDED
    assert SourceItem(**deleted).change_kind is ChangeKind.DELETED
    assert SourceItem(**renamed).change_kind is ChangeKind.RENAMED

    for invalid in (
        _item_values() | {"change_kind": ChangeKind.ADDED},
        _item_values() | {"change_kind": ChangeKind.DELETED},
        _item_values() | {"change_kind": ChangeKind.RENAMED},
        _item_values() | {"base_path_b64": None},
    ):
        with pytest.raises(ValidationError):
            SourceItem(**invalid)


def test_git_paths_round_trip_as_bytes_and_supported_or_unsupported_objects_are_data() -> None:
    unusual = b"src/\xff-name.py"
    encoded = _path(unusual)
    item = _item(base_path_b64=encoded, head_path_b64=encoded)
    assert base64.b64decode(item.head_path_b64, validate=True) == unusual
    with pytest.raises(ValidationError):
        _item(head_path_b64="not base64!")

    for kind, mode in (
        (ObjectKind.SYMLINK, "120000"),
        (ObjectKind.SUBMODULE, "160000"),
        (ObjectKind.UNSUPPORTED, "100640"),
    ):
        assert _item(base_object_kind=kind, head_object_kind=kind, base_mode=mode, head_mode=mode)
    with pytest.raises(ValidationError):
        _item(head_object_kind=ObjectKind.SYMLINK, head_mode="100644")


def test_object_mode_policy_mutation_cannot_change_validation_outcome() -> None:
    with pytest.raises(ValidationError):
        _item(head_object_kind=ObjectKind.SYMLINK, head_mode="100644")
    with pytest.raises(TypeError):
        contracts._OBJECT_MODES[0] = (ObjectKind.SYMLINK, "100644")
    with pytest.raises(ValidationError):
        _item(head_object_kind=ObjectKind.SYMLINK, head_mode="100644")


def test_duplicate_logical_identifiers_fail_within_each_container() -> None:
    with pytest.raises(ValidationError):
        _bundle(items=(_item(), _item()))
    with pytest.raises(ValidationError):
        _bundle(declarations=(_declaration(), _declaration()))
    with pytest.raises(ValidationError):
        _bundle(reviews=(_review(), _review()))
    with pytest.raises(ValidationError):
        _report(decisions=(_decision(), _decision()))


def test_declaration_review_and_policy_references_carry_only_structural_bindings() -> None:
    declaration = _declaration()
    review = _review()
    policy_ref = _policy_ref()

    assert declaration.item_ids == ("item-source",)
    assert declaration.content_sha256s == (SHA256_A, SHA256_B)
    assert review.inventory_digest == SHA256_B
    assert review.revoked is False and review.superseded_by is None
    assert policy_ref.retention.metadata_report_days == 30
    assert policy_ref.source_commit_sha1 == SHA1_A


def test_ai_fact_and_reason_codes_enforce_local_coherence_and_set_semantics() -> None:
    with pytest.raises(ValidationError):
        AIFactEvidence(
            fact=AIFact.MODEL_VERSION,
            availability=Availability.UNAVAILABLE,
            value="invented",
            evidence_ref=None,
            evidence_sha256=None,
        )
    report = SourceAdmissionReport.model_validate(
        _report().model_dump()
        | {
            "verdict": Verdict.REVIEW_REQUIRED,
            "reason_codes": (ReasonCode.REVIEW_MISSING, ReasonCode.ORIGIN_UNKNOWN),
        }
    )
    assert report.reason_codes == (ReasonCode.ORIGIN_UNKNOWN, ReasonCode.REVIEW_MISSING)
    with pytest.raises(ValidationError):
        SourceAdmissionReport.model_validate(
            _report().model_dump()
            | {"reason_codes": (ReasonCode.REVIEW_MISSING, ReasonCode.REVIEW_MISSING)}
        )


def test_caller_constructed_admitted_report_has_no_authority_or_integrity_proof() -> None:
    report = _report()
    assert report.verdict is Verdict.ADMITTED
    assert report.report_digest == "0" * 64
    assert not hasattr(report, "verify_digest")
    assert not hasattr(report, "is_authoritative")


def test_module_has_no_codec_digest_transport_persistence_or_effect_reachability() -> None:
    module_path = ROOT / "src" / "blackbread" / "governance" / "source_admission_contracts.py"
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert not any(
        name.startswith(("parse_", "canonical_", "compute_", "verify_")) for name in functions
    )
    forbidden_imports = {"hashlib", "json", "subprocess", "socket"}
    forbidden_imports |= {"httpx", "sqlalchemy", "pathlib"}
    assert imported.isdisjoint(forbidden_imports)
    for forbidden in ("merge_readiness", "WorkOrder", "Capability", "GitHub"):
        assert forbidden not in source
