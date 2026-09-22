"""Strict wire codec for source-admission bundles and reports.

Converts untrusted bytes into the strict semantic models, emits canonical JSON,
and computes domain-separated content digests. A digest proves only that the
decoded content and the embedded digest field agree; it never proves producer
identity, freshness, authorization, or admission. The codec is read-only,
side-effect-free, and intentionally unwired: the named next consumer is
GOV-IP-PROVENANCE-001B1c, which owns recomputation and cross-checking against
the bundle it received in the same call.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, NoReturn

from pydantic import BaseModel

from blackbread.governance.source_admission_contracts import (
    SourceAdmissionBundle,
    SourceAdmissionReport,
)

_REPORT_DOMAIN = b"blackbread.source-admission.v1"
_INVENTORY_DOMAIN = b"blackbread.source-admission.inventory.v1"
_DECLARATIONS_DOMAIN = b"blackbread.source-admission.declarations.v1"
_REVIEWS_DOMAIN = b"blackbread.source-admission.reviews.v1"
_MAX_JSON_DEPTH = 100


class SourceAdmissionWireError(ValueError):
    """Sanitized wire rejection carrying a stable machine code."""

    def __init__(self, code: str) -> None:
        super().__init__(f"source admission wire rejected: {code}")
        self.code = code


def _fail(code: str) -> NoReturn:
    raise SourceAdmissionWireError(code) from None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, value in pairs:
        if key in decoded:
            _fail("SOURCE_WIRE_JSON_DUPLICATE_KEY")
        decoded[key] = value
    return decoded


def _reject_json_float(_: str) -> NoReturn:
    _fail("SOURCE_WIRE_FLOAT_FORBIDDEN")


def _reject_deep_json(value: Any) -> None:
    # Iterative walk: attacker-controlled nesting must never reach the
    # interpreter recursion limit inside the decoder or the validator.
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > _MAX_JSON_DEPTH:
            _fail("SOURCE_WIRE_JSON_MALFORMED")
        if isinstance(item, dict | list):
            children = item.values() if isinstance(item, dict) else item
            stack.extend((child, depth + 1) for child in children)


def _decode_strict(payload: bytes) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _fail("SOURCE_WIRE_UTF8_INVALID")
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_json_float,
            parse_constant=_reject_json_float,
        )
    except SourceAdmissionWireError:
        raise
    except (ValueError, RecursionError):
        # ValueError also covers the parse_int digit-limit escape, which is not
        # a JSONDecodeError; decoder failures stay sanitized and fail closed.
        _fail("SOURCE_WIRE_JSON_MALFORMED")
    _reject_deep_json(decoded)
    if not isinstance(decoded, dict):
        _fail("SOURCE_WIRE_SCHEMA_INVALID")
    if "schema_version" not in decoded:
        _fail("SOURCE_WIRE_SCHEMA_MISSING")
    version = decoded["schema_version"]
    if type(version) is not int:
        _fail("SOURCE_WIRE_SCHEMA_INVALID")
    if version != 1:
        _fail("SOURCE_WIRE_SCHEMA_UNSUPPORTED")
    return decoded


def _validate[Model: BaseModel](model: type[Model], decoded: dict[str, Any]) -> Model:
    try:
        normalized = json.dumps(decoded, ensure_ascii=False, allow_nan=False)
        return model.model_validate_json(normalized)
    except RecursionError:
        _fail("SOURCE_WIRE_JSON_MALFORMED")
    except (TypeError, ValueError):
        _fail("SOURCE_WIRE_SCHEMA_INVALID")


def _canonical(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(domain: bytes, payload: Any) -> str:
    return hashlib.sha256(domain + b"\0" + _canonical(payload)).hexdigest()


def parse_bundle_bytes(payload: bytes) -> SourceAdmissionBundle:
    return _validate(SourceAdmissionBundle, _decode_strict(payload))


def canonical_bundle_bytes(bundle: SourceAdmissionBundle) -> bytes:
    return _canonical(bundle.model_dump(mode="json"))


def compute_inventory_digest(bundle: SourceAdmissionBundle) -> str:
    payload = {
        "subject": bundle.subject.model_dump(mode="json"),
        "items": [item.model_dump(mode="json") for item in bundle.items],
    }
    return _digest(_INVENTORY_DOMAIN, payload)


def compute_declarations_digest(bundle: SourceAdmissionBundle) -> str:
    payload = {"declarations": [item.model_dump(mode="json") for item in bundle.declarations]}
    return _digest(_DECLARATIONS_DOMAIN, payload)


def compute_reviews_digest(bundle: SourceAdmissionBundle) -> str:
    payload = {"reviews": [item.model_dump(mode="json") for item in bundle.reviews]}
    return _digest(_REVIEWS_DOMAIN, payload)


def parse_report_bytes(payload: bytes) -> SourceAdmissionReport:
    report = _validate(SourceAdmissionReport, _decode_strict(payload))
    # The digest binds the report's own content only; recomputing it after a
    # mutation stays possible and proves consistency, never provenance.
    if not hmac.compare_digest(report.report_digest, compute_report_digest(report)):
        _fail("SOURCE_WIRE_REPORT_DIGEST_MISMATCH")
    return report


def canonical_report_bytes(report: SourceAdmissionReport) -> bytes:
    return _canonical(report.model_dump(mode="json"))


def compute_report_digest(report: SourceAdmissionReport) -> str:
    payload = report.model_dump(mode="json")
    del payload["report_digest"]
    return _digest(_REPORT_DOMAIN, payload)
