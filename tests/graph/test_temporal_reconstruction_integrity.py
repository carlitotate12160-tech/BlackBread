from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from blackbread.graph.domain import GraphProjectionError
from blackbread.graph.temporal_reconstruction import load_temporal_projection
from blackbread.models.core import Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context
from tests.graph.conftest import _seed_attestation_event, _seed_engagement
from tests.graph.test_temporal_reconstruction import (
    GraphEvents,
    _publish_v1,
    _publish_v2,
)


async def test_real_cross_tenant_isolation(  # noqa: PLR0913, PLR0917
    engine: AsyncEngine,
    admin_engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    # A is real, published
    await _publish_v1(session, engine, engagement, graph_events)

    tenant_b = "tenant-b-real"
    eng_b_id = uuid.uuid4()

    await _seed_engagement(admin_engine, tenant_b, eng_b_id)
    event_hash = await _seed_attestation_event(admin_engine, tenant_b, eng_b_id)

    # We must insert into graph_temporal_projection_snapshots directly to prove isolation
    await admin_session.execute(
        text(
            "INSERT INTO graph_temporal_projection_snapshots ("
            "tenant_id, engagement_id, verified_event_count, verified_head_hash, "
            "ledger_hash_algorithm, ledger_hash_version, temporal_projector_version, "
            "state_root_version, scope_canonicalization_version, state_root, "
            "lineage_head_hash, lineage_head_sequence) "
            "VALUES (:tid, :eid, 1, :hash, 'sha256', 1, 2, 2, 1, :hash, :hash, 1)"
        ),
        {"tid": tenant_b, "eid": eng_b_id, "hash": event_hash},
    )
    await admin_session.commit()

    # Admin verifies BOTH exist physically
    rows = (
        (
            await admin_session.execute(
                text("SELECT tenant_id, engagement_id FROM graph_temporal_projection_snapshots")
            )
        )
        .mappings()
        .all()
    )
    found = {(r["tenant_id"], r["engagement_id"]) for r in rows}
    assert (engagement.tenant_id, engagement.id) in found
    assert (tenant_b, eng_b_id) in found

    # --- RLS backstop (F3) --------------------------------------------------
    # The composite WHERE clause (tenant_id + engagement_id) alone cannot prove
    # isolation: (tenant_b, eng_A) simply has no row, so a None result is scoping,
    # not security. To prove RLS *blocks* the cross-tenant read of A's physically-
    # existing (A, eng_A) row, bind a runtime connection to tenant B and query by
    # A's engagement_id with NO tenant_id filter. RLS must yield zero rows. Binding
    # to tenant A (or admin) here would leak A's row and fail this assertion, which
    # is precisely what makes it exercise RLS rather than the WHERE clause.
    async with engine.connect() as conn, conn.begin():
        await bind_tenant_context(conn, TenantContext(tenant_b))
        leaked = (
            (
                await conn.execute(
                    text(
                        "SELECT tenant_id FROM graph_temporal_projection_snapshots "
                        "WHERE engagement_id = :eid"
                    ),
                    {"eid": engagement.id},
                )
            )
            .scalars()
            .all()
        )
    assert leaked == []

    # Prove that emptiness is isolation, not absence: the identical engagement_id
    # query under the RLS-bypassing admin engine DOES return A's row.
    admin_view = (
        (
            await admin_session.execute(
                text(
                    "SELECT tenant_id FROM graph_temporal_projection_snapshots "
                    "WHERE engagement_id = :eid"
                ),
                {"eid": engagement.id},
            )
        )
        .scalars()
        .all()
    )
    assert admin_view == [engagement.tenant_id]

    # --- Composite-scoping assertions (retained, additive, still valid) -----
    # B loading A's engagement -> None
    b_loads_a = await load_temporal_projection(
        engine, tenant_id=tenant_b, engagement_id=engagement.id
    )
    assert b_loads_a is None

    # A loading B's engagement -> None
    a_loads_b = await load_temporal_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=eng_b_id
    )
    assert a_loads_b is None


async def test_stable_roots_extra_root_tamper(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    await _publish_v2(session, engine, engagement, graph_events)

    result = await load_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    assert result is not None
    assert len(result.lineage.revisions) > 0

    victim_rev = result.lineage.revisions[0]
    fake_node_id = "f" * 64

    # Insert an extra fake root to simulate a tamper
    await admin_session.execute(
        text(
            "INSERT INTO graph_temporal_scope_roots (tenant_id, engagement_id, node_id, "
            "node_family, scope_kind, canonical_value) "
            "VALUES (:tid, :eid, :nid, 'ScopeRoot', :skind, 'tampered.example')"
        ),
        {
            "tid": engagement.tenant_id,
            "eid": engagement.id,
            "nid": fake_node_id,
            "skind": victim_rev.scope_kind,
        },
    )
    await admin_session.commit()

    with pytest.raises(
        GraphProjectionError,
        match="reconstructed stable roots do not match lineage",
    ):
        await load_temporal_projection(
            engine,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )

    # Remove the fake root to restore integrity
    await admin_session.execute(
        text(
            "DELETE FROM graph_temporal_scope_roots "
            "WHERE tenant_id = :tid AND engagement_id = :eid "
            "AND node_id = :nid AND canonical_value = 'tampered.example'"
        ),
        {
            "tid": engagement.tenant_id,
            "eid": engagement.id,
            "nid": fake_node_id,
        },
    )
    await admin_session.commit()

    # Reconstruct again should succeed
    restored = await load_temporal_projection(
        engine,
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
    )
    assert restored is not None


async def test_stable_roots_missing_root_tamper(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    await _publish_v2(session, engine, engagement, graph_events)

    result = await load_temporal_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    assert result is not None
    assert len(result.lineage.revisions) > 0

    victim = result.lineage.revisions[0]
    key = {"tid": engagement.tenant_id, "eid": engagement.id, "nid": victim.node_id}

    # A referenced stable root cannot be DELETEd through the revisions->roots FK
    # (ondelete RESTRICT is the first fail-closed layer). Inject the corrupt state
    # past the FK trigger to prove the reconstruction backstop *also* fails closed.
    saved = (
        (
            await admin_session.execute(
                text(
                    "SELECT node_family, scope_kind, canonical_value "
                    "FROM graph_temporal_scope_roots "
                    "WHERE tenant_id = :tid AND engagement_id = :eid AND node_id = :nid"
                ),
                key,
            )
        )
        .mappings()
        .one()
    )
    await admin_session.execute(text("ALTER TABLE graph_temporal_scope_roots DISABLE TRIGGER ALL"))
    await admin_session.execute(
        text(
            "DELETE FROM graph_temporal_scope_roots "
            "WHERE tenant_id = :tid AND engagement_id = :eid AND node_id = :nid"
        ),
        key,
    )
    await admin_session.execute(text("ALTER TABLE graph_temporal_scope_roots ENABLE TRIGGER ALL"))
    await admin_session.commit()

    with pytest.raises(
        GraphProjectionError,
        match="reconstructed stable roots do not match lineage",
    ):
        await load_temporal_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )

    # Restore the deleted root; reconstruction succeeds again.
    await admin_session.execute(
        text(
            "INSERT INTO graph_temporal_scope_roots "
            "(tenant_id, engagement_id, node_id, node_family, scope_kind, canonical_value) "
            "VALUES (:tid, :eid, :nid, :nf, :sk, :cv)"
        ),
        {
            **key,
            "nf": saved["node_family"],
            "sk": saved["scope_kind"],
            "cv": saved["canonical_value"],
        },
    )
    await admin_session.commit()

    restored = await load_temporal_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    assert restored is not None


async def test_stable_roots_altered_root_tamper(
    engine: AsyncEngine,
    session: AsyncSession,
    admin_session: AsyncSession,
    engagement: Engagement,
    graph_events: GraphEvents,
) -> None:
    await _publish_v2(session, engine, engagement, graph_events)

    result = await load_temporal_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    assert result is not None
    assert len(result.lineage.revisions) > 0

    victim = result.lineage.revisions[0]
    key = {"tid": engagement.tenant_id, "eid": engagement.id, "nid": victim.node_id}
    original_value = (
        await admin_session.execute(
            text(
                "SELECT canonical_value FROM graph_temporal_scope_roots "
                "WHERE tenant_id = :tid AND engagement_id = :eid AND node_id = :nid"
            ),
            key,
        )
    ).scalar_one()

    # canonical_value participates in the revisions->roots FK, so a live UPDATE is
    # blocked (the FK is the first fail-closed layer). Inject past the FK trigger to
    # prove the reconstruction backstop *also* fails closed on an altered root.
    await admin_session.execute(text("ALTER TABLE graph_temporal_scope_roots DISABLE TRIGGER ALL"))
    await admin_session.execute(
        text(
            "UPDATE graph_temporal_scope_roots SET canonical_value = 'altered.example' "
            "WHERE tenant_id = :tid AND engagement_id = :eid AND node_id = :nid"
        ),
        key,
    )
    await admin_session.execute(text("ALTER TABLE graph_temporal_scope_roots ENABLE TRIGGER ALL"))
    await admin_session.commit()

    with pytest.raises(
        GraphProjectionError,
        match="reconstructed stable roots do not match lineage",
    ):
        await load_temporal_projection(
            engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
        )

    # Restore the original canonical_value; reconstruction succeeds again.
    await admin_session.execute(text("ALTER TABLE graph_temporal_scope_roots DISABLE TRIGGER ALL"))
    await admin_session.execute(
        text(
            "UPDATE graph_temporal_scope_roots SET canonical_value = :cv "
            "WHERE tenant_id = :tid AND engagement_id = :eid AND node_id = :nid"
        ),
        {**key, "cv": original_value},
    )
    await admin_session.execute(text("ALTER TABLE graph_temporal_scope_roots ENABLE TRIGGER ALL"))
    await admin_session.commit()

    restored = await load_temporal_projection(
        engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id
    )
    assert restored is not None
