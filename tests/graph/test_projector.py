import uuid
from collections.abc import Callable
from copy import deepcopy

import pytest

from blackbread.graph.domain import (
    GraphProjectionError,
    ScopeProjector,
    compute_state_root,
    scope_root_id,
)
from blackbread.ledger.catalog import EngagementAttested, EngagementScope, ScopeExclusion
from blackbread.ledger.event import AgentEvent


def test_one_attested_root_domain_projects_one_scope_root(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    event = event_factory(attestation_factory(root_domains=("example.com",)))

    projector = ScopeProjector()
    projector.consume(event)

    assert len(projector.nodes) == 1
    node = projector.nodes[0]
    assert node.node_id == scope_root_id("root_domain", "example.com")
    assert node.node_family == "ScopeRoot"
    assert node.scope_kind == "root_domain"
    assert node.canonical_value == "example.com"
    assert node.authority == "attested_scope"
    assert node.source_event_hash == event.event_hash


def test_positive_scope_types_have_canonical_deterministic_identities(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    payload = attestation_factory(
        root_domains=("example.com",),
        exact_hosts=("api.example.com",),
        exact_addresses=("192.0.2.10", "2001:db8::10"),
        cloud_tenants=("aws:123456789012",),
    )
    first = ScopeProjector()
    second = ScopeProjector()

    first.consume(event_factory(payload))
    second.consume(event_factory(payload))

    expected = {
        ("root_domain", "example.com"),
        ("exact_host", "api.example.com"),
        ("exact_address", "192.0.2.10"),
        ("exact_address", "2001:db8::10"),
        ("cloud_tenant", "aws:123456789012"),
    }
    assert {(node.scope_kind, node.canonical_value) for node in first.nodes} == expected
    assert first.nodes == second.nodes
    assert len({node.node_id for node in first.nodes}) == len(expected)


def test_exclusions_and_boundaries_do_not_create_graph_truth(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    base = attestation_factory(root_domains=("example.com",))
    payload = EngagementAttested(
        manifest_hash=base.manifest_hash,
        manifest_signature_ref=base.manifest_signature_ref,
        attested_by=base.attested_by,
        mode=base.mode,
        scope=EngagementScope(
            root_domains=("example.com",),
            exclusions=(ScopeExclusion(target_type="exact_host", value="admin.example.com"),),
            third_party_boundaries=("shared-cdn",),
        ),
        valid_from=base.valid_from,
        expires_at=base.expires_at,
    )
    projector = ScopeProjector()

    projector.consume(event_factory(payload))

    assert [(node.scope_kind, node.canonical_value) for node in projector.nodes] == [
        ("root_domain", "example.com")
    ]


def test_state_root_ignores_node_and_mapping_insertion_order(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    payload = attestation_factory(
        root_domains=("example.com",),
        exact_hosts=("api.example.com",),
        exact_addresses=("192.0.2.10",),
    )
    original = event_factory(payload)
    reordered = event_factory(payload)
    reordered.payload = dict(reversed(list(deepcopy(original.payload).items())))
    first = ScopeProjector()
    second = ScopeProjector()
    first.consume(original)
    second.consume(reordered)

    root_one = compute_state_root(
        original.tenant_id,
        original.engagement_id,
        first.nodes,
    )
    root_two = compute_state_root(
        reordered.tenant_id,
        reordered.engagement_id,
        tuple(reversed(second.nodes)),
    )

    assert root_one == root_two


def test_explicit_stopped_event_handler_is_a_graph_noop(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
    stopped_event: object,
) -> None:
    projector = ScopeProjector()
    projector.consume(event_factory(attestation_factory()))
    expected = projector.nodes

    projector.consume(event_factory(stopped_event, sequence=2))

    assert projector.nodes == expected


def test_stop_before_attestation_fails_closed(
    event_factory: Callable[..., AgentEvent],
    stopped_event: object,
) -> None:
    with pytest.raises(GraphProjectionError, match="stop precedes attestation"):
        ScopeProjector().consume(event_factory(stopped_event))


@pytest.mark.parametrize(
    ("schema_name", "schema_version"),
    [("engagement.attested", 3), ("future.event", 1)],
)
def test_unsupported_event_schema_or_version_fails_closed(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
    schema_name: str,
    schema_version: int,
) -> None:
    event = event_factory(attestation_factory())
    event.schema_name = schema_name
    event.schema_version = schema_version

    with pytest.raises(GraphProjectionError, match=r"unsupported|unknown"):
        ScopeProjector().consume(event)


def test_malformed_attestation_cannot_create_graph_truth(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    event = event_factory(attestation_factory())
    event.payload = {"scope": {"root_domains": ["example.com"]}}
    projector = ScopeProjector()

    with pytest.raises(GraphProjectionError, match="payload"):
        projector.consume(event)

    assert projector.nodes == ()


def test_second_attestation_without_supersession_semantics_fails_closed(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    projector = ScopeProjector()
    projector.consume(event_factory(attestation_factory(), sequence=1))

    with pytest.raises(GraphProjectionError, match="second v1 attestation"):
        projector.consume(event_factory(attestation_factory(), sequence=2))


@pytest.mark.parametrize("projector_version", [0, 2])
def test_unsupported_projector_version_fails_closed(projector_version: int) -> None:
    with pytest.raises(GraphProjectionError, match="projector version"):
        ScopeProjector(version=projector_version)


@pytest.mark.parametrize("state_root_version", [0, 2])
def test_unsupported_state_root_version_fails_closed(state_root_version: int) -> None:
    with pytest.raises(GraphProjectionError, match="state-root version"):
        compute_state_root("tenant-a", uuid.UUID(int=100), (), version=state_root_version)
