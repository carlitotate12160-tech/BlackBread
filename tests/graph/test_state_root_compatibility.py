from datetime import UTC, datetime
from uuid import UUID

import pytest

from blackbread.graph.domain import (
    GraphProjectionError,
    ScopeRoot,
    compute_state_root,
    scope_root_id,
)

_IDENTITIES = (
    (
        "root_domain",
        "example.com",
        "c66143d56bf019db83961bde80f8506226d04441623f4e756429b27f49875204",
    ),
    (
        "exact_host",
        "api.example.com",
        "bbe7ec1f8ab28b85cefe254d2aa05fbb42b5c7963279f9051f0b64ddd48b30fb",
    ),
    (
        "exact_address",
        "2001:db8::10",
        "75f20e8d0f2d436ae52ae5cccac43a402c85c86090d7c53f7edc80f878501f6f",
    ),
    (
        "cloud_tenant",
        "aws:123456789012",
        "927e0b7a74adb51af77bf81b31ca905316f83055efe2567168071e9840b63bd4",
    ),
)
_NONCANONICAL = (
    ("root_domain", "Example.com"),
    ("exact_host", " api.example.com"),
    ("root_domain", "b\u00fccher.example"),
    ("exact_address", "2001:0db8::10"),
    ("cloud_tenant", "aws:123456789012 "),
)


def test_state_root_v1_compatibility_vector_is_frozen() -> None:
    for kind, value, expected in _IDENTITIES:
        assert scope_root_id(kind, value) == expected
    for kind, value in _NONCANONICAL:
        with pytest.raises(GraphProjectionError, match="canonical"):
            scope_root_id(kind, value)

    nodes = tuple(
        ScopeRoot(
            node_id,
            kind,
            value,
            "a" * 64,
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 2, 1, tzinfo=UTC),
            1,
            "b" * 64,
        )
        for kind, value, node_id in _IDENTITIES
    )
    assert (
        compute_state_root(
            "tenant-a",
            UUID("00000000-0000-0000-0000-000000000064"),
            nodes,
        )
        == "9ec7fea31baec61c14a76a4353055450084969599ecba285a38fdf8f20068699"
    )


@pytest.mark.parametrize("source_version", [2, True])
def test_state_root_v1_rejects_v2_provenance(source_version: object) -> None:
    node = ScopeRoot(
        scope_root_id("root_domain", "example.com"),
        "root_domain",
        "example.com",
        "a" * 64,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 2, 1, tzinfo=UTC),
        1,
        "b" * 64,
        source_schema_version=source_version,
    )

    with pytest.raises(GraphProjectionError, match="v1 state root requires v1 provenance"):
        compute_state_root("tenant-a", UUID(int=100), (node,))
