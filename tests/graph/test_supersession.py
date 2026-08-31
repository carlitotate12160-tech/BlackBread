import uuid
from collections.abc import Callable
from copy import deepcopy

import pytest

from blackbread.graph.domain import (
    GraphProjectionError,
    ScopeProjector,
    ScopeRoot,
    compute_state_root,
    scope_root_id,
)
from blackbread.graph.supersession import (
    AttestationChain,
    SupersessionError,
    select_supersession_head,
)
from blackbread.ledger.catalog import EngagementAttested
from blackbread.ledger.event import AgentEvent


def _v2_event(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
    *,
    supersedes: str,
    sequence: int,
    root_domains: tuple[str, ...],
) -> AgentEvent:
    event = event_factory(
        attestation_factory(root_domains=root_domains),
        sequence=sequence,
    )
    event.schema_version = 2
    event.payload = {**event.payload, "supersedes_event_hash": supersedes}
    return event


def test_v2_replacement_selects_head_and_preserves_stable_identity(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    initial = event_factory(
        attestation_factory(root_domains=("example.com", "removed.example")),
        sequence=1,
    )
    replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=2,
        root_domains=("example.com", "new.example"),
    )
    projector = ScopeProjector()

    projector.consume(initial)
    original_id = next(
        node.node_id for node in projector.nodes if node.canonical_value == "example.com"
    )
    projector.consume(replacement)

    assert {(node.canonical_value, node.source_schema_version) for node in projector.nodes} == {
        ("example.com", 2),
        ("new.example", 2),
    }
    retained = next(node for node in projector.nodes if node.canonical_value == "example.com")
    assert retained.node_id == original_id
    assert retained.source_event_hash == replacement.event_hash


def test_retained_value_keeps_node_id_but_gets_distinct_revision(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    initial = event_factory(attestation_factory(), sequence=1)
    replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=2,
        root_domains=("example.com",),
    )
    projector = ScopeProjector()

    projector.consume(initial)
    projector.consume(replacement)

    revisions = tuple(
        revision
        for revision in getattr(projector, "revisions", ())
        if revision.canonical_value == "example.com"
    )
    assert len(revisions) == 2
    assert len({revision.node_id for revision in revisions}) == 1
    assert len({revision.revision_id for revision in revisions}) == 2


def test_removed_value_absent_from_head_but_revision_retained(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    initial = event_factory(
        attestation_factory(root_domains=("example.com", "removed.example")),
        sequence=1,
    )
    replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=2,
        root_domains=("example.com",),
    )
    projector = ScopeProjector()

    projector.consume(initial)
    projector.consume(replacement)

    assert {node.canonical_value for node in projector.nodes} == {"example.com"}
    assert any(
        revision.canonical_value == "removed.example"
        and revision.source_event_hash == initial.event_hash
        for revision in getattr(projector, "revisions", ())
    )


def test_second_v1_attestation_fails_closed(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    projector = ScopeProjector()
    projector.consume(event_factory(attestation_factory(), sequence=1))

    with pytest.raises(GraphProjectionError, match="second v1 attestation"):
        projector.consume(event_factory(attestation_factory(), sequence=2))

    assert len(getattr(projector, "revisions", ())) == 1


def test_fork_and_noncurrent_predecessor_fail_closed(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    initial = event_factory(attestation_factory(), sequence=1)
    replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=2,
        root_domains=("example.com",),
    )
    fork = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=3,
        root_domains=("fork.example",),
    )
    projector = ScopeProjector()
    projector.consume(initial)
    projector.consume(replacement)

    with pytest.raises(GraphProjectionError, match="current supersession head"):
        projector.consume(fork)

    assert {node.canonical_value for node in projector.nodes} == {"example.com"}


def test_three_attestation_chain_selects_final_replacement(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    initial = event_factory(attestation_factory(), sequence=1)
    second = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=2,
        root_domains=("second.example",),
    )
    third = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=second.event_hash,
        sequence=3,
        root_domains=("third.example",),
    )
    projector = ScopeProjector()

    for event in (initial, second, third):
        projector.consume(event)

    assert {node.canonical_value for node in projector.nodes} == {"third.example"}
    assert {revision.source_event_hash for revision in projector.revisions} == {
        initial.event_hash,
        second.event_hash,
        third.event_hash,
    }


@pytest.mark.parametrize(
    ("predecessor", "message"),
    [(None, "payload"), ("A" * 64, "payload"), ("f" * 64, "not an admitted")],
)
def test_missing_malformed_or_unknown_predecessor_fails_closed(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
    predecessor: str | None,
    message: str,
) -> None:
    initial = event_factory(attestation_factory(), sequence=1)
    replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=predecessor or initial.event_hash,
        sequence=2,
        root_domains=("replacement.example",),
    )
    if predecessor is None:
        replacement.payload.pop("supersedes_event_hash")
    projector = ScopeProjector()
    projector.consume(initial)

    with pytest.raises(GraphProjectionError, match=message):
        projector.consume(replacement)

    assert {node.canonical_value for node in projector.nodes} == {"example.com"}


def test_v2_without_existing_attestation_fails_closed(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes="f" * 64,
        sequence=1,
        root_domains=("replacement.example",),
    )

    with pytest.raises(GraphProjectionError, match="requires an existing attestation"):
        ScopeProjector().consume(replacement)


def test_forward_or_cycle_shaped_reference_fails_closed(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    initial = event_factory(attestation_factory(), sequence=1)
    replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=2,
        root_domains=("replacement.example",),
    )
    replacement.payload["supersedes_event_hash"] = replacement.event_hash
    projector = ScopeProjector()
    projector.consume(initial)

    with pytest.raises(GraphProjectionError, match="cycle"):
        projector.consume(replacement)


def test_source_sequence_regression_fails_closed(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    initial = event_factory(attestation_factory(), sequence=2)
    replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=1,
        root_domains=("replacement.example",),
    )
    projector = ScopeProjector()
    projector.consume(initial)

    with pytest.raises(GraphProjectionError, match="sequence regressed"):
        projector.consume(replacement)


@pytest.mark.parametrize("binding_field", ["tenant_id", "engagement_id"])
def test_cross_binding_predecessor_fails_closed(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
    binding_field: str,
) -> None:
    initial = event_factory(attestation_factory(), sequence=1)
    replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=2,
        root_domains=("replacement.example",),
    )
    replacement_value: object = "tenant-b"
    if binding_field == "engagement_id":
        replacement_value = uuid.UUID(int=200)
    setattr(replacement, binding_field, replacement_value)
    projector = ScopeProjector()
    projector.consume(initial)

    with pytest.raises(GraphProjectionError, match="binding changed"):
        projector.consume(replacement)


def test_stopped_event_does_not_replace_semantic_predecessor(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
    stopped_event: object,
) -> None:
    initial = event_factory(attestation_factory(), sequence=1)
    stopped = event_factory(stopped_event, sequence=2)
    replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=3,
        root_domains=("replacement.example",),
    )
    projector = ScopeProjector()

    for event in (initial, stopped, replacement):
        projector.consume(event)

    assert {node.canonical_value for node in projector.nodes} == {"replacement.example"}
    revision = next(
        item for item in projector.revisions if item.source_event_hash == replacement.event_hash
    )
    assert revision.predecessor_attestation_event_hash == initial.event_hash


def test_stopped_event_hash_is_not_an_attestation_predecessor(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
    stopped_event: object,
) -> None:
    initial = event_factory(attestation_factory(), sequence=1)
    stopped = event_factory(stopped_event, sequence=2)
    replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=stopped.event_hash,
        sequence=3,
        root_domains=("replacement.example",),
    )
    projector = ScopeProjector()
    projector.consume(initial)
    projector.consume(stopped)

    with pytest.raises(GraphProjectionError, match="not an admitted attestation"):
        projector.consume(replacement)


def test_revision_set_ignores_payload_mapping_insertion_order(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    initial = event_factory(attestation_factory(), sequence=1)
    replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=2,
        root_domains=("example.com", "replacement.example"),
    )
    reordered_initial = event_factory(attestation_factory(), sequence=1)
    reordered_replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=reordered_initial.event_hash,
        sequence=2,
        root_domains=("example.com", "replacement.example"),
    )
    reordered_replacement.payload = dict(reversed(list(deepcopy(replacement.payload).items())))
    first = ScopeProjector()
    second = ScopeProjector()

    for projector, events in (
        (first, (initial, replacement)),
        (second, (reordered_initial, reordered_replacement)),
    ):
        for event in events:
            projector.consume(event)

    assert first.revisions == second.revisions
    assert first.revisions == tuple(sorted(first.revisions, key=lambda item: item.revision_id))


def test_structural_head_selection_ignores_collection_order() -> None:
    initial = "1".zfill(64)
    second = "2".zfill(64)
    third = "3".zfill(64)

    assert AttestationChain().head_hash is None
    assert select_supersession_head((initial, second, third), (initial, second)) == third
    assert select_supersession_head((third, initial, second), (second, initial)) == third
    with pytest.raises(SupersessionError, match="one structural head"):
        select_supersession_head((initial, second), ())
    with pytest.raises(SupersessionError, match="one structural head"):
        select_supersession_head((initial,), (initial,))


@pytest.mark.parametrize(("sequence", "event_hash"), [(0, "0" * 64), (1, "A" * 64)])
def test_invalid_attestation_source_fails_closed(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
    sequence: int,
    event_hash: str,
) -> None:
    event = event_factory(attestation_factory(), sequence=sequence)
    event.event_hash = event_hash

    with pytest.raises(GraphProjectionError, match="source is invalid"):
        ScopeProjector().consume(event)


def test_duplicate_attestation_event_hash_fails_closed(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    initial = event_factory(attestation_factory(), sequence=1)
    replacement = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=2,
        root_domains=("replacement.example",),
    )
    replacement.event_hash = initial.event_hash
    projector = ScopeProjector()
    projector.consume(initial)

    with pytest.raises(GraphProjectionError, match="already admitted"):
        projector.consume(replacement)


def test_unsupported_v3_and_malformed_v2_fail_closed(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    initial = event_factory(attestation_factory(), sequence=1)
    unsupported = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=2,
        root_domains=("replacement.example",),
    )
    unsupported.schema_version = 3
    malformed = _v2_event(
        attestation_factory,
        event_factory,
        supersedes=initial.event_hash,
        sequence=2,
        root_domains=("replacement.example",),
    )
    malformed.payload.pop("scope")

    for event in (unsupported, malformed):
        projector = ScopeProjector()
        projector.consume(initial)
        with pytest.raises(GraphProjectionError, match="unsupported schema or malformed payload"):
            projector.consume(event)


def test_v1_only_projection_and_state_root_are_byte_identical(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
) -> None:
    payload = attestation_factory()
    event = event_factory(payload, sequence=1)
    projector = ScopeProjector()

    projector.consume(event)

    expected = ScopeRoot(
        scope_root_id("root_domain", "example.com"),
        "root_domain",
        "example.com",
        "a" * 64,
        payload.valid_from,
        payload.expires_at,
        1,
        event.event_hash,
    )
    assert projector.nodes == (expected,)
    assert compute_state_root(event.tenant_id, event.engagement_id, projector.nodes) == (
        compute_state_root(event.tenant_id, event.engagement_id, (expected,))
    )
    assert len(projector.revisions) == 1
    assert projector.revisions[0].node_id == expected.node_id
