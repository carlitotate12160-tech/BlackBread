"""Strict wire codec proofs for source-admission bundles and reports."""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import re
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from blackbread.governance.source_admission_codec import (
    SourceAdmissionWireError,
    canonical_bundle_bytes,
    canonical_report_bytes,
    compute_declarations_digest,
    compute_inventory_digest,
    compute_report_digest,
    compute_reviews_digest,
    parse_bundle_bytes,
    parse_report_bytes,
)
from blackbread.governance.source_admission_contracts import SourceAdmissionReport
from blackbread.governance.source_admission_policy import (
    compute_policy_digest,
    parse_policy_bytes,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "source-admission-policy.json"
SHA1_A, SHA1_B = "a" * 40, "b" * 40
SHA1_C, SHA1_D = "c" * 40, "d" * 40
SHA256_A, SHA256_B = "1" * 64, "2" * 64
SHA256_C, SHA256_D = "3" * 64, "4" * 64
KNOWN_POLICY_DIGEST = "ab0f6408d257fd8a5a38ddc5582900aad45be2ae2c438e1d7697cfcb75523463"
KNOWN_INVENTORY_DIGEST = "b10223bb9436df59a1a926d88fe6c0efa5ad170d7d4d5f40d6b61c08e765f6ab"
KNOWN_DECLARATIONS_DIGEST = "043302029a625160471badca0e80afac583647cea6dae8fe2e3954864f7372db"
KNOWN_REVIEWS_DIGEST = "54391af95d9191fbfd1f640acd57e2ac67d30c26d009e90a54b9033b32abd172"
KNOWN_REPORT_DIGEST = "0ec7db7759cbe4815fcb4c1fd8a52ec20dcf4b786b9f497a385a5ccd983bd2d5"

REPORT_DOMAIN = b"blackbread.source-admission.v1"
INVENTORY_DOMAIN = b"blackbread.source-admission.inventory.v1"
DECLARATIONS_DOMAIN = b"blackbread.source-admission.declarations.v1"
REVIEWS_DOMAIN = b"blackbread.source-admission.reviews.v1"

Parser = Callable[[bytes], Any]


def _path(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _encoded(raw: dict[str, Any]) -> bytes:
    return json.dumps(raw, ensure_ascii=False).encode("utf-8")


def _stdlib_digest(domain: bytes, payload: Any) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(domain + b"\0" + canonical).hexdigest()


def _subject() -> dict[str, Any]:
    return {
        "repository": "carlitotate12160-tech/BlackBread",
        "base_commit_sha1": SHA1_A,
        "head_commit_sha1": SHA1_B,
        "base_tree_sha1": SHA1_C,
        "head_tree_sha1": SHA1_D,
        "use_profile": "ENGINEERING_REVIEW",
        "processor_profile": "LOCAL_ONLY",
        "coverage_description": "Exact base-to-head inventory plus declared context.",
    }


def _item(item_id: str = "item-source") -> dict[str, Any]:
    return {
        "item_id": item_id,
        "change_kind": "MODIFIED",
        "base_path_b64": _path(b"src/example.py"),
        "head_path_b64": _path(b"src/example.py"),
        "base_object_kind": "BLOB",
        "head_object_kind": "BLOB",
        "base_mode": "100644",
        "head_mode": "100644",
        "base_object_sha1": SHA1_A,
        "head_object_sha1": SHA1_B,
        "base_content_sha256": SHA256_A,
        "head_content_sha256": SHA256_B,
        "origins": ["AI_GENERATED", "REPOSITORY_AUTHORED"],
        "lineage_refs": ["a-line", "z-line"],
        "dependency_refs": ["a-dep", "z-dep"],
        "obligation_refs": ["ai-provider-tool-terms"],
    }


def _declaration(declaration_id: str = "declaration-source") -> dict[str, Any]:
    return {
        "declaration_id": declaration_id,
        "item_ids": ["item-source"],
        "content_sha256s": [SHA256_A, SHA256_B],
        "origins": ["AI_GENERATED", "REPOSITORY_AUTHORED"],
        "contributor_identity_id": "github:carlitotate12160-tech",
        "ai_facts": [
            {
                "fact": "MODEL_IDENTIFIER",
                "availability": "AVAILABLE",
                "value": "gpt-5.6",
                "evidence_ref": "run:model",
                "evidence_sha256": SHA256_C,
            }
        ],
        "external_references": ["a-ref", "z-ref"],
        "license_expression": None,
        "declaration_evidence_ref": "run:declaration",
        "declaration_evidence_sha256": SHA256_A,
    }


def _review(review_id: str = "review-source") -> dict[str, Any]:
    return {
        "review_id": review_id,
        "reviewer_identity_id": "github:carlitotate12160-tech",
        "item_ids": ["item-extra", "item-source"],
        "inventory_digest": SHA256_B,
        "decision": "APPROVED",
        "rationale": "Exact-scope engineering review.",
        "evidence_ref": "github:review:1",
        "evidence_sha256": SHA256_C,
        "reviewed_at": "2026-09-21T03:00:00Z",
        "superseded_by": None,
        "revoked": False,
    }


def _policy_ref() -> dict[str, Any]:
    return {
        "policy_id": "blackbread-source-admission",
        "policy_version": "1",
        "source_commit_sha1": SHA1_A,
        "source_blob_sha1": SHA1_B,
        "policy_sha256": KNOWN_POLICY_DIGEST,
        "use_profile": "ENGINEERING_REVIEW",
        "processor_profile": "LOCAL_ONLY",
        "retention": json.loads(POLICY_PATH.read_text(encoding="utf-8"))["retention"],
    }


def _bundle_raw(**changes: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "subject": _subject(),
        "items": [_item()],
        "declarations": [_declaration()],
        "reviews": [_review()],
        "policy_ref": _policy_ref(),
        "collector_version": "collector-v1",
        "collected_at": "2026-09-21T03:01:00Z",
        "producer": "caller-controlled-producer",
        "run_id": "run-001",
    } | changes


def _report_fields(**changes: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "subject": _subject(),
        "inventory_digest": SHA256_A,
        "declarations_digest": SHA256_B,
        "reviews_digest": SHA256_C,
        "policy_ref": _policy_ref(),
        "evaluator_version": "evaluator-v1",
        "item_decisions": [_decision()],
        "verdict": "ADMITTED",
        "reason_codes": [],
        "evidence_complete": True,
        "coverage_description": "Only the represented base-to-head inventory.",
        "observed_at": "2026-09-21T03:02:00Z",
        "producer": "caller-controlled-producer",
        "run_id": "run-001",
    } | changes


def _decision(item_id: str = "item-source") -> dict[str, Any]:
    return {
        "item_id": item_id,
        "verdict": "ADMITTED",
        "reason_codes": [],
        "evidence_complete": True,
    }


def _resigned_report(fields: dict[str, Any]) -> dict[str, Any]:
    candidate = json.dumps(fields | {"report_digest": "0" * 64})
    model = SourceAdmissionReport.model_validate_json(candidate)
    return fields | {"report_digest": compute_report_digest(model)}


def _report_raw(**changes: Any) -> dict[str, Any]:
    return _resigned_report(_report_fields(**changes))


def _assert_code(payload: bytes, expected: str, parser: Parser = parse_bundle_bytes) -> None:
    with pytest.raises(SourceAdmissionWireError) as excinfo:
        parser(payload)
    assert excinfo.value.code == expected
    assert str(excinfo.value) == f"source admission wire rejected: {expected}"


@pytest.mark.parametrize("parser", [parse_bundle_bytes, parse_report_bytes])
@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"\xff\xfe", "SOURCE_WIRE_UTF8_INVALID"),
        (b"{not-json", "SOURCE_WIRE_JSON_MALFORMED"),
        (b"", "SOURCE_WIRE_JSON_MALFORMED"),
        (b'{"schema_version":1} {}', "SOURCE_WIRE_JSON_MALFORMED"),
        (b'{"schema_version":1,"schema_version":1}', "SOURCE_WIRE_JSON_DUPLICATE_KEY"),
        (b'{"schema_version":1,"subject":{"k":1,"k":2}}', "SOURCE_WIRE_JSON_DUPLICATE_KEY"),
        (b'{"schema_version":1.0}', "SOURCE_WIRE_FLOAT_FORBIDDEN"),
        (b'{"schema_version":1e0}', "SOURCE_WIRE_FLOAT_FORBIDDEN"),
        (b'{"schema_version":NaN}', "SOURCE_WIRE_FLOAT_FORBIDDEN"),
        (b'{"schema_version":Infinity}', "SOURCE_WIRE_FLOAT_FORBIDDEN"),
        (b'{"schema_version":-Infinity}', "SOURCE_WIRE_FLOAT_FORBIDDEN"),
        (b"[1,2]", "SOURCE_WIRE_SCHEMA_INVALID"),
        (b"null", "SOURCE_WIRE_SCHEMA_INVALID"),
        (b'{"subject":{}}', "SOURCE_WIRE_SCHEMA_MISSING"),
        (b'{"schema_version":"1"}', "SOURCE_WIRE_SCHEMA_INVALID"),
        (b'{"schema_version":true}', "SOURCE_WIRE_SCHEMA_INVALID"),
        (b'{"schema_version":null}', "SOURCE_WIRE_SCHEMA_INVALID"),
        (b'{"schema_version":2}', "SOURCE_WIRE_SCHEMA_UNSUPPORTED"),
    ],
)
def test_wire_rejections_carry_sanitized_codes(parser: Parser, payload: bytes, code: str) -> None:
    _assert_code(payload, code, parser)


@pytest.mark.parametrize("parser", [parse_bundle_bytes, parse_report_bytes])
@pytest.mark.parametrize("depth", [150, 2000])
def test_excessive_nesting_is_sanitized_without_recursion_leak(parser: Parser, depth: int) -> None:
    payload = b'{"schema_version":1,"nested":' + b"[" * depth + b"0" + b"]" * depth + b"}"
    _assert_code(payload, "SOURCE_WIRE_JSON_MALFORMED", parser)


def test_strict_schema_and_model_validation_fail_closed() -> None:
    _assert_code(_encoded(_bundle_raw() | {"unknown": True}), "SOURCE_WIRE_SCHEMA_INVALID")
    coerced = _bundle_raw()
    coerced["items"][0]["base_mode"] = 100644
    _assert_code(_encoded(coerced), "SOURCE_WIRE_SCHEMA_INVALID")
    bad_hash = _bundle_raw()
    bad_hash["subject"]["base_commit_sha1"] = "A" * 40
    _assert_code(_encoded(bad_hash), "SOURCE_WIRE_SCHEMA_INVALID")
    missing = _bundle_raw()
    del missing["producer"]
    _assert_code(_encoded(missing), "SOURCE_WIRE_SCHEMA_INVALID")
    invalid_semantics = _bundle_raw()
    invalid_semantics["items"][0]["head_path_b64"] = _path(b"src/other.py")
    _assert_code(_encoded(invalid_semantics), "SOURCE_WIRE_SCHEMA_INVALID")


def test_duplicate_logical_identities_fail_within_each_container() -> None:
    for section in ("items", "declarations", "reviews"):
        raw = _bundle_raw()
        raw[section].append(deepcopy(raw[section][0]))
        _assert_code(_encoded(raw), "SOURCE_WIRE_SCHEMA_INVALID")
    report = _report_raw()
    report["item_decisions"].append(deepcopy(report["item_decisions"][0]))
    _assert_code(_encoded(report), "SOURCE_WIRE_SCHEMA_INVALID", parse_report_bytes)


def test_canonical_bytes_are_deterministic_idempotent_and_key_order_invariant() -> None:
    bundle = parse_bundle_bytes(_encoded(_bundle_raw()))
    reparsed = parse_bundle_bytes(canonical_bundle_bytes(bundle))
    assert canonical_bundle_bytes(reparsed) == canonical_bundle_bytes(bundle)
    shuffled = dict(reversed(list(_bundle_raw().items())))
    assert canonical_bundle_bytes(parse_bundle_bytes(_encoded(shuffled))) == (
        canonical_bundle_bytes(bundle)
    )
    report = parse_report_bytes(_encoded(_report_raw()))
    assert canonical_report_bytes(parse_report_bytes(canonical_report_bytes(report))) == (
        canonical_report_bytes(report)
    )


def test_documented_set_reorder_does_not_change_digests() -> None:
    reordered = _bundle_raw()
    reordered["items"][0]["origins"] = ["REPOSITORY_AUTHORED", "AI_GENERATED"]
    reordered["items"][0]["dependency_refs"] = ["z-dep", "a-dep"]
    reordered["declarations"][0]["content_sha256s"] = [SHA256_B, SHA256_A]
    reordered["reviews"][0]["item_ids"] = ["item-source", "item-extra"]
    baseline = parse_bundle_bytes(_encoded(_bundle_raw()))
    shuffled = parse_bundle_bytes(_encoded(reordered))
    assert compute_inventory_digest(shuffled) == compute_inventory_digest(baseline)
    assert compute_declarations_digest(shuffled) == compute_declarations_digest(baseline)
    assert compute_reviews_digest(shuffled) == compute_reviews_digest(baseline)
    fields = _report_fields(
        verdict="REVIEW_REQUIRED", reason_codes=["ORIGIN_UNKNOWN", "REVIEW_MISSING"]
    )
    reordered_fields = deepcopy(fields)
    reordered_fields["reason_codes"] = ["REVIEW_MISSING", "ORIGIN_UNKNOWN"]
    report_a = parse_report_bytes(_encoded(_resigned_report(fields)))
    report_b = parse_report_bytes(_encoded(_resigned_report(reordered_fields)))
    assert compute_report_digest(report_a) == compute_report_digest(report_b)


def test_semantic_array_order_changes_the_corresponding_digest() -> None:
    items = [_item(), _item("item-second")]
    bundle_a = parse_bundle_bytes(_encoded(_bundle_raw(items=items)))
    bundle_b = parse_bundle_bytes(_encoded(_bundle_raw(items=items[::-1])))
    assert compute_inventory_digest(bundle_a) != compute_inventory_digest(bundle_b)
    declarations = [_declaration(), _declaration("declaration-second")]
    bundle_a = parse_bundle_bytes(_encoded(_bundle_raw(declarations=declarations)))
    bundle_b = parse_bundle_bytes(_encoded(_bundle_raw(declarations=declarations[::-1])))
    assert compute_declarations_digest(bundle_a) != compute_declarations_digest(bundle_b)
    reviews = [_review(), _review("review-second")]
    bundle_a = parse_bundle_bytes(_encoded(_bundle_raw(reviews=reviews)))
    bundle_b = parse_bundle_bytes(_encoded(_bundle_raw(reviews=reviews[::-1])))
    assert compute_reviews_digest(bundle_a) != compute_reviews_digest(bundle_b)
    second = _decision("item-second") | {"verdict": "REJECTED"}
    decisions = _report_fields()["item_decisions"] + [second]
    report_a = parse_report_bytes(_encoded(_report_raw(item_decisions=decisions)))
    report_b = parse_report_bytes(_encoded(_report_raw(item_decisions=decisions[::-1])))
    assert compute_report_digest(report_a) != compute_report_digest(report_b)


def test_inventory_digest_changes_for_alternate_subject_or_item() -> None:
    baseline = compute_inventory_digest(parse_bundle_bytes(_encoded(_bundle_raw())))
    other_subject = _bundle_raw()
    other_subject["subject"]["head_commit_sha1"] = SHA1_A
    other_subject["subject"]["coverage_description"] = "Alternate snapshot coverage."
    changed = parse_bundle_bytes(_encoded(other_subject))
    assert compute_inventory_digest(changed) != baseline
    other_item = _bundle_raw(items=[_item("item-alternate")])
    assert compute_inventory_digest(parse_bundle_bytes(_encoded(other_item))) != baseline


def test_declaration_and_review_digests_track_only_their_section() -> None:
    baseline = parse_bundle_bytes(_encoded(_bundle_raw()))
    dec = parse_bundle_bytes(_encoded(_bundle_raw(declarations=[_declaration("declaration-b")])))
    rev = parse_bundle_bytes(_encoded(_bundle_raw(reviews=[_review("review-b")])))
    assert compute_declarations_digest(dec) != compute_declarations_digest(baseline)
    assert compute_inventory_digest(dec) == compute_inventory_digest(baseline)
    assert compute_reviews_digest(dec) == compute_reviews_digest(baseline)
    assert compute_reviews_digest(rev) != compute_reviews_digest(baseline)
    assert compute_inventory_digest(rev) == compute_inventory_digest(baseline)
    assert compute_declarations_digest(rev) == compute_declarations_digest(baseline)


def test_digest_domains_are_distinct() -> None:
    payload = {"subject": _subject(), "items": [_item()]}
    domains = (REPORT_DOMAIN, INVENTORY_DOMAIN, DECLARATIONS_DOMAIN, REVIEWS_DOMAIN)
    assert len({_stdlib_digest(domain, payload) for domain in domains}) == 4


def test_digests_match_independent_known_answers() -> None:
    raw = _bundle_raw()
    bundle = parse_bundle_bytes(_encoded(raw))
    report = parse_report_bytes(_encoded(_report_raw()))
    inventory = _stdlib_digest(INVENTORY_DOMAIN, {"subject": raw["subject"], "items": raw["items"]})
    declarations = _stdlib_digest(DECLARATIONS_DOMAIN, {"declarations": raw["declarations"]})
    reviews = _stdlib_digest(REVIEWS_DOMAIN, {"reviews": raw["reviews"]})
    report_digest = _stdlib_digest(REPORT_DOMAIN, _report_fields())
    assert inventory == KNOWN_INVENTORY_DIGEST == compute_inventory_digest(bundle)
    assert declarations == KNOWN_DECLARATIONS_DIGEST == compute_declarations_digest(bundle)
    assert reviews == KNOWN_REVIEWS_DIGEST == compute_reviews_digest(bundle)
    assert report_digest == KNOWN_REPORT_DIGEST == compute_report_digest(report)
    assert _report_raw()["report_digest"] == KNOWN_REPORT_DIGEST
    policy = parse_policy_bytes(POLICY_PATH.read_bytes())
    assert compute_policy_digest(policy) == KNOWN_POLICY_DIGEST


def _set_field(raw: dict[str, Any], path: tuple[Any, ...], value: Any) -> None:
    target: Any = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


@pytest.mark.parametrize(
    "mutation",
    [
        (("subject", "repository"), "owner/alternate"),
        (("subject", "head_tree_sha1"), SHA1_A),
        (("inventory_digest",), SHA256_D),
        (("declarations_digest",), SHA256_D),
        (("reviews_digest",), SHA256_D),
        (("policy_ref", "policy_version"), "2"),
        (("evaluator_version",), "evaluator-v2"),
        (("item_decisions", 0, "verdict"), "REVIEW_REQUIRED"),
        (("verdict",), "REJECTED"),
        (("reason_codes",), ["REVIEW_MISSING"]),
        (("evidence_complete",), False),
        (("coverage_description",), "Whole repository claimed without evidence."),
        (("observed_at",), "2026-09-21T03:03:00Z"),
        (("producer",), "attacker-controlled-producer"),
        (("run_id",), "run-002"),
    ],
)
def test_stale_report_digest_is_rejected_for_every_semantic_field(
    mutation: tuple[tuple[Any, ...], Any],
) -> None:
    raw = _report_raw()
    _set_field(raw, mutation[0], mutation[1])
    _assert_code(_encoded(raw), "SOURCE_WIRE_REPORT_DIGEST_MISMATCH", parse_report_bytes)


def test_recomputed_digest_parses_structurally_but_confers_no_authority() -> None:
    raw = _report_raw()
    _set_field(raw, ("producer",), "attacker-controlled-producer")
    parsed = parse_report_bytes(_encoded(_resigned_report(raw)))
    assert parsed.producer == "attacker-controlled-producer"
    assert not hasattr(parsed, "is_authoritative")
    assert not hasattr(parsed, "verify_digest")


def test_codec_is_intentionally_unwired_and_has_no_effect_reachability() -> None:
    codec_path = ROOT / "src" / "blackbread" / "governance" / "source_admission_codec.py"
    source = codec_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    allowed = {
        "__future__",
        "hashlib",
        "hmac",
        "json",
        "pydantic",
        "typing",
        "blackbread.governance.source_admission_contracts",
    }
    assert imported <= allowed
    for forbidden in (
        "merge_readiness",
        "WorkOrder",
        "subprocess",
        "socket",
        "verify_",
        "trusted",
        "authenticat",
        "authoritative",
    ):
        assert not re.search(rf"\b{forbidden}", source)
    for path in (ROOT / "src" / "blackbread").rglob("*.py"):
        if path != codec_path:
            assert "source_admission_codec" not in path.read_text(encoding="utf-8")
