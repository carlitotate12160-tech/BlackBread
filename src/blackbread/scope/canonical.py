"""Single-source canonical scope validation, reused by ledger and conductor.

Pure stdlib (``re``, ``ipaddress``); no pydantic, no I/O, no framework, no other
``blackbread`` package. Owns the four scope kinds and their canonicalization so no
consumer forks a weaker copy and no consumer reaches through a heavier layer for it
(anti Lyndon #6/#7). The conductor trust-spine contract depends only on this leaf
module — never on ``graph`` — so importing a proposal contract never drags the graph
read-model. ``graph`` still carries its own ``ScopeKind`` and dispatcher; converging
those is tracked as CONTRACT-GAP-001 and deliberately excluded here to avoid touching
released graph-projection code in this slice.
"""

from __future__ import annotations

import re
from ipaddress import IPv6Address, ip_address
from typing import Literal

ScopeKind = Literal["root_domain", "exact_host", "exact_address", "cloud_tenant"]
SCOPE_KINDS: tuple[ScopeKind, ...] = (
    "root_domain",
    "exact_host",
    "exact_address",
    "cloud_tenant",
)

_MAX_CLOUD_TENANT_LENGTH = 500
_DOMAIN_LABEL_PATTERN = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_LEGACY_IPV4_COMPONENT_PATTERN = re.compile(r"^(?:0x[0-9a-f]+|[0-9]+)$")
_MAX_IPV4_COMPONENTS = 4
_MIN_DOMAIN_LABELS = 2


def canonical_text(value: str, field: str, maximum: int) -> str:
    """Bounded canonical text: non-blank, trimmed, no NUL, valid UTF-8, within length."""
    if not value or value != value.strip():
        raise ValueError(f"{field} must be a canonical non-blank string")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    if "\x00" in value:
        raise ValueError(f"{field} contains a NUL character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} contains invalid Unicode") from exc
    return value


def ensure_canonical_text(value: str) -> str:
    """Single-argument canonical text for pydantic ``AfterValidator``.

    Enforces non-blank, trimmed, no NUL, and valid UTF-8. Length is enforced by the
    field's own ``Field(max_length=...)`` constraint, so it is not repeated here.
    """
    if not value or value != value.strip():
        raise ValueError("value must be non-blank with no surrounding whitespace")
    if "\x00" in value:
        raise ValueError("value must not contain a NUL character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("value must not contain invalid Unicode") from exc
    return value


def canonical_domain(value: str) -> str:
    """Validate a lowercase fully-qualified domain name; reject IP literals."""
    canonical_text(value, "domain", 253)
    try:
        ip_address(value)
    except ValueError:
        pass
    else:
        raise ValueError("domain fields cannot contain IP address literals")
    labels = value.split(".")
    if len(labels) <= _MAX_IPV4_COMPONENTS and all(
        _LEGACY_IPV4_COMPONENT_PATTERN.fullmatch(label) is not None for label in labels
    ):
        raise ValueError("domain fields cannot contain legacy IPv4 address spellings")
    if len(labels) < _MIN_DOMAIN_LABELS or value != value.lower():
        raise ValueError("domain must be a lowercase fully-qualified name")
    if any(_DOMAIN_LABEL_PATTERN.fullmatch(label) is None for label in labels):
        raise ValueError("domain is not canonical")
    return value


def canonical_address(value: str) -> str:
    """Validate an IP address in its canonical compressed spelling; reject scoped IPv6."""
    parsed = ip_address(value)
    if isinstance(parsed, IPv6Address) and parsed.scope_id is not None:
        raise ValueError("scoped IPv6 addresses are not valid engagement targets")
    if value != parsed.compressed:
        raise ValueError("IP address must use its canonical compressed spelling")
    return value


def canonical_target_value(target_type: ScopeKind, value: str) -> str:
    """Dispatch a scope value to its per-kind canonicalizer; raise if non-canonical."""
    if target_type in ("root_domain", "exact_host"):
        return canonical_domain(value)
    if target_type == "exact_address":
        return canonical_address(value)
    if target_type == "cloud_tenant":
        return canonical_text(value, "cloud tenant value", _MAX_CLOUD_TENANT_LENGTH)
    raise ValueError(f"unsupported scope kind: {target_type!r}")


def canonical_scope_value(kind: str, value: str) -> tuple[ScopeKind, str]:
    """Return ``(kind, canonical_value)`` for a scope value; raise ``ValueError`` if invalid.

    Reject-not-rewrite: the returned canonical value equals the input for a canonical
    value and this raises otherwise, so a caller can compare the two to detect a scope
    authority that ever starts normalizing instead of rejecting.
    """
    if kind not in SCOPE_KINDS:
        raise ValueError(f"unsupported scope kind: {kind!r}")
    return kind, canonical_target_value(kind, value)
