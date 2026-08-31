import uuid
from collections.abc import Callable

import pytest

from blackbread.graph.domain import GraphProjectionError, ScopeProjector
from blackbread.ledger.catalog import EngagementAttested
from blackbread.ledger.event import AgentEvent


@pytest.mark.parametrize("foreign_binding", ["tenant_id", "engagement_id"])
def test_cross_binding_predecessor_is_not_admitted_to_local_chain(
    attestation_factory: Callable[..., EngagementAttested],
    event_factory: Callable[..., AgentEvent],
    foreign_binding: str,
) -> None:
    initial = event_factory(attestation_factory(), sequence=1)
    foreign = event_factory(attestation_factory(), sequence=9)
    foreign_value: object = "tenant-b"
    if foreign_binding == "engagement_id":
        foreign_value = uuid.UUID(int=200)
    setattr(foreign, foreign_binding, foreign_value)
    replacement = event_factory(
        attestation_factory(root_domains=("replacement.example",)),
        sequence=2,
    )
    replacement.schema_version = 2
    replacement.payload = {
        **replacement.payload,
        "supersedes_event_hash": foreign.event_hash,
    }
    assert (replacement.tenant_id, replacement.engagement_id) == (
        initial.tenant_id,
        initial.engagement_id,
    )
    assert (foreign.tenant_id, foreign.engagement_id) != (
        initial.tenant_id,
        initial.engagement_id,
    )
    projector = ScopeProjector()
    projector.consume(initial)

    with pytest.raises(
        GraphProjectionError,
        match="supersession predecessor is not an admitted attestation",
    ):
        projector.consume(replacement)
