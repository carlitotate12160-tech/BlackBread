"""Direct unit contract for the single scope-canonicalization authority."""

from __future__ import annotations

import pytest

from blackbread.scope import canonical


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("exact_address", "example.com"),
        ("root_domain", "192.0.2.1"),
        ("exact_host", "EXAMPLE.COM"),
        ("exact_address", "2001:0db8::1"),
        ("cloud_tenant", "\ud800"),
        ("ip_range", "example.com"),
    ],
)
def test_canonical_scope_value_rejects_non_canonical_or_mistyped(kind: str, value: str) -> None:
    with pytest.raises(ValueError):
        canonical.canonical_scope_value(kind, value)


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("root_domain", "example.com"),
        ("exact_host", "host.example.com"),
        ("exact_address", "192.0.2.1"),
        ("exact_address", "2001:db8::1"),
        ("cloud_tenant", "aws:o-1234567890"),
    ],
)
def test_canonical_scope_value_returns_kind_and_unchanged_value(kind: str, value: str) -> None:
    returned_kind, returned_value = canonical.canonical_scope_value(kind, value)
    assert returned_kind == kind
    assert returned_value == value  # reject-not-rewrite: canonical input is returned verbatim


def test_ensure_canonical_text_rejects_surrogate_but_accepts_valid_utf8() -> None:
    assert canonical.ensure_canonical_text("café-münchen") == "café-münchen"
    with pytest.raises(ValueError):
        canonical.ensure_canonical_text("\ud800")
