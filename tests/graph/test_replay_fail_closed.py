import asyncio
from collections.abc import Sequence
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from blackbread.graph import persistence
from blackbread.graph.domain import GraphProjectionError, ProjectionNotFoundError
from blackbread.graph.persistence import load_scope_projection, publish_scope_projection
from blackbread.graph.replay import rebuild_scope_projection
from blackbread.ledger import LedgerAccessError
from blackbread.ledger.event import AgentEvent
from blackbread.models.core import Client, Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context


async def _new_engagement(factory: async_sessionmaker[AsyncSession], tenant_id: str) -> Engagement:
    async with factory() as session:
        await bind_tenant_context(session, TenantContext(tenant_id))
        client = Client(name="separate-client", tenant_id=tenant_id)
        session.add(client)
        await session.flush()
        engagement = Engagement(client_id=client.id, tenant_id=tenant_id)
        session.add(engagement)
        await session.commit()
        return engagement


async def test_rebuild_requires_attested_scope(
    engine: AsyncEngine,
    engagement: Engagement,
) -> None:
    with pytest.raises(GraphProjectionError, match="no attestation"):
        await rebuild_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )
    with pytest.raises(ProjectionNotFoundError):
        await load_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )


async def test_unsupported_ledger_event_version_prevents_publication(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    payload = graph_events.attestation().to_ledger_payload()
    await graph_events.draft(session, engagement, "engagement.attested", 2, payload)

    with pytest.raises(GraphProjectionError, match=r"unsupported|unknown"):
        await rebuild_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )
    with pytest.raises(ProjectionNotFoundError):
        await load_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )


async def test_malformed_ledger_event_cannot_publish_graph_truth(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    await graph_events.draft(
        session,
        engagement,
        "engagement.attested",
        1,
        {"scope": {"root_domains": ["example.com"]}},
    )

    with pytest.raises(GraphProjectionError, match="payload"):
        await rebuild_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )
    with pytest.raises(ProjectionNotFoundError):
        await load_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )


async def test_tampered_ledger_cannot_be_projected(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    event = await graph_events.append(session, engagement, graph_events.attestation())
    await admin_session.execute(
        text("ALTER TABLE agent_events DISABLE TRIGGER agent_events_reject_mutation")
    )
    await admin_session.execute(
        AgentEvent.__table__.update()
        .where(AgentEvent.id == event.id)
        .values(payload={"tampered": True})
    )
    await admin_session.execute(
        text("ALTER TABLE agent_events ENABLE TRIGGER agent_events_reject_mutation")
    )
    await admin_session.commit()

    with pytest.raises(GraphProjectionError, match="ledger verification failed"):
        await rebuild_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )
    with pytest.raises(ProjectionNotFoundError):
        await load_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )


async def test_wrong_tenant_cannot_read_or_rebuild_projection(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    await graph_events.append(session, engagement, graph_events.attestation())
    await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    with pytest.raises(LedgerAccessError):
        await rebuild_scope_projection(
            engine, tenant_id="tenant-other", engagement_id=engagement.id
        )
    with pytest.raises(LedgerAccessError):
        await load_scope_projection(engine, tenant_id="tenant-other", engagement_id=engagement.id)


async def test_engagements_cannot_contaminate_each_other(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    engagement: Engagement,
    graph_events,
) -> None:
    other = await _new_engagement(session_factory, engagement.tenant_id)
    async with session_factory() as first_session:
        await graph_events.append(
            first_session,
            engagement,
            graph_events.attestation(root_domains=("first.example.com",)),
        )
    async with session_factory() as second_session:
        await graph_events.append(
            second_session,
            other,
            graph_events.attestation(root_domains=("second.example.com",)),
        )

    first = await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    second = await rebuild_scope_projection(
        engine, tenant_id=other.tenant_id, engagement_id=other.id
    )

    assert {node.canonical_value for node in first.nodes} == {"first.example.com"}
    assert {node.canonical_value for node in second.nodes} == {"second.example.com"}
    assert first.engagement_id != second.engagement_id


async def test_database_rejects_cross_engagement_source_relationship(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    other = await _new_engagement(session_factory, engagement.tenant_id)
    async with session_factory() as first_session:
        await graph_events.append(first_session, engagement, graph_events.attestation())
    async with session_factory() as second_session:
        other_event = await graph_events.append(second_session, other, graph_events.attestation())
    await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    with pytest.raises(IntegrityError, match="fk_graph_nodes_source_event"):
        await admin_session.execute(
            text(
                "UPDATE graph_nodes SET source_event_hash = :source "
                "WHERE engagement_id = :engagement"
            ),
            {"source": other_event.event_hash, "engagement": engagement.id},
        )
    await admin_session.rollback()


async def test_database_rejects_noncanonical_identity_values(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    await graph_events.append(session, engagement, graph_events.attestation())
    await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    for invalid_value in (" ", " example.com", "Example.com"):
        with pytest.raises(IntegrityError, match="ck_graph_nodes_canonical_value"):
            await admin_session.execute(
                text(
                    "UPDATE graph_nodes SET canonical_value = :value "
                    "WHERE engagement_id = :engagement"
                ),
                {"value": invalid_value, "engagement": engagement.id},
            )
        await admin_session.rollback()


async def test_postgresql_row_order_cannot_change_loaded_state_root(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await graph_events.append(
        session,
        engagement,
        graph_events.attestation(
            root_domains=("example.com",),
            exact_hosts=("api.example.com",),
            exact_addresses=("192.0.2.10",),
        ),
    )
    expected = await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    original = persistence._ProjectionStore.node_rows

    async def reversed_rows(store: object) -> Sequence[object]:
        rows = await original(store)
        return tuple(reversed(rows))

    monkeypatch.setattr(persistence._ProjectionStore, "node_rows", reversed_rows)
    loaded = await load_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )

    assert loaded.projection == expected
    assert loaded.projection.state_root == expected.state_root


async def test_publication_rejects_head_hash_not_bound_to_verified_sequence(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    await graph_events.append(session, engagement, graph_events.attestation())
    original = await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    await graph_events.append(session, engagement, graph_events.stopped)
    forged = replace(
        original,
        verified_event_count=2,
        verified_head_hash="f" * 64,
    )

    with pytest.raises(IntegrityError, match="fk_graph_projection_snapshot_anchor"):
        await publish_scope_projection(engine, forged)

    stored = await load_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    assert stored.projection == original
    assert stored.is_current is False


async def test_publication_rejects_anchor_ahead_of_committed_ledger(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    event = await graph_events.append(session, engagement, graph_events.attestation())
    original = await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    forged = replace(
        original,
        verified_event_count=2,
        verified_head_hash=event.event_hash,
    )

    with pytest.raises(IntegrityError, match="fk_graph_projection_snapshot_anchor"):
        await publish_scope_projection(engine, forged)

    stored = await load_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    assert stored.projection == original
    assert stored.is_current is True


async def test_projection_corruption_fails_closed_and_is_not_repaired(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events,
) -> None:
    await graph_events.append(session, engagement, graph_events.attestation())
    await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    await admin_session.execute(
        text(
            "UPDATE graph_projection_snapshots SET state_root = :root "
            "WHERE engagement_id = :engagement"
        ),
        {"root": "f" * 64, "engagement": engagement.id},
    )
    await admin_session.commit()
    await graph_events.append(session, engagement, graph_events.stopped)

    with pytest.raises(GraphProjectionError, match="state root"):
        await load_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )
    with pytest.raises(GraphProjectionError, match="state root"):
        await rebuild_scope_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )


async def test_cancelled_rebuild_releases_connection_and_preserves_snapshot(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await graph_events.append(session, engagement, graph_events.attestation())
    original_projection = await rebuild_scope_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    await graph_events.append(session, engagement, graph_events.stopped)
    constrained = create_async_engine(engine.url, pool_size=1, max_overflow=0)
    original_execute = AsyncConnection.execute
    deleted = asyncio.Event()
    never_resume = asyncio.Event()

    async def pause_after_delete(
        connection: AsyncConnection,
        statement: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        result = await original_execute(connection, statement, *args, **kwargs)
        if str(statement).startswith("DELETE FROM graph_nodes"):
            deleted.set()
            await never_resume.wait()
        return result

    monkeypatch.setattr(AsyncConnection, "execute", pause_after_delete)
    rebuilding = asyncio.create_task(
        rebuild_scope_projection(
            constrained,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )
    )
    await asyncio.wait_for(deleted.wait(), timeout=2)
    rebuilding.cancel()
    with pytest.raises(asyncio.CancelledError):
        await rebuilding
    monkeypatch.undo()
    try:
        stored = await load_scope_projection(
            constrained,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )
        assert stored.projection == original_projection
        assert stored.is_current is False
        assert constrained.pool.checkedout() == 0
    finally:
        await constrained.dispose()


async def test_publication_failure_releases_connection_and_leaves_no_snapshot(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
    graph_events,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await graph_events.append(session, engagement, graph_events.attestation())
    constrained = create_async_engine(engine.url, pool_size=1, max_overflow=0)
    original_execute = AsyncConnection.execute

    async def reject_node_insert(
        connection: AsyncConnection,
        statement: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        if str(statement).startswith("INSERT INTO graph_nodes"):
            raise RuntimeError("injected graph node publication failure")
        return await original_execute(connection, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncConnection, "execute", reject_node_insert)
    with pytest.raises(RuntimeError, match="injected graph node publication failure"):
        await rebuild_scope_projection(
            constrained,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )
    monkeypatch.undo()
    try:
        with pytest.raises(ProjectionNotFoundError):
            await load_scope_projection(
                constrained,
                tenant_id=engagement.tenant_id,
                engagement_id=engagement.id,
            )
        assert constrained.pool.checkedout() == 0
    finally:
        await constrained.dispose()
