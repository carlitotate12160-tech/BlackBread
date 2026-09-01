"""Migration 0006 temporal schema privilege and RLS tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.graph.conftest import (
    SCHEMA_TENANT as TENANT,
)
from tests.graph.conftest import (
    _seed_attestation_event,
    _seed_engagement,
)


class TestPrivileges:
    async def test_snapshot_insert_allowed(
        self,
        admin_engine: AsyncEngine,
        runtime_engine: AsyncEngine,
    ) -> None:
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)
        event_hash = await _seed_attestation_event(admin_engine, TENANT, eid)

        async with runtime_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('blackbread.tenant_id', :tid, true)"),
                {"tid": TENANT},
            )
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_projection_snapshots "
                    "(tenant_id, engagement_id, verified_event_count, verified_head_hash, "
                    "ledger_hash_algorithm, ledger_hash_version, temporal_projector_version, "
                    "state_root_version, scope_canonicalization_version, state_root, "
                    "lineage_head_hash, lineage_head_sequence) "
                    "VALUES (:tid, :eid, 1, :eh, 'sha256', 1, 2, 2, 1, :sr, :eh, 1)"
                ),
                {"tid": TENANT, "eid": eid, "eh": event_hash, "sr": "b" * 64},
            )

    async def test_roots_delete_denied(
        self,
        admin_engine: AsyncEngine,
        runtime_engine: AsyncEngine,
    ) -> None:
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)

        async with runtime_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('blackbread.tenant_id', :tid, true)"),
                {"tid": TENANT},
            )
            with pytest.raises(DBAPIError) as err:
                await conn.execute(
                    text(
                        "DELETE FROM graph_temporal_scope_roots "
                        "WHERE tenant_id = :tid AND engagement_id = :eid"
                    ),
                    {"tid": TENANT, "eid": eid},
                )
        assert err.value.orig.sqlstate == "42501"

    async def test_revisions_update_denied(
        self,
        admin_engine: AsyncEngine,
        runtime_engine: AsyncEngine,
    ) -> None:
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)

        async with runtime_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('blackbread.tenant_id', :tid, true)"),
                {"tid": TENANT},
            )
            with pytest.raises(DBAPIError) as err:
                await conn.execute(
                    text(
                        "UPDATE graph_temporal_scope_revisions "
                        "SET manifest_hash = :mh "
                        "WHERE tenant_id = :tid AND engagement_id = :eid"
                    ),
                    {"tid": TENANT, "eid": eid, "mh": "c" * 64},
                )
        assert err.value.orig.sqlstate == "42501"

    async def test_head_nodes_update_denied(
        self,
        admin_engine: AsyncEngine,
        runtime_engine: AsyncEngine,
    ) -> None:
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)

        async with runtime_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('blackbread.tenant_id', :tid, true)"),
                {"tid": TENANT},
            )
            with pytest.raises(DBAPIError) as err:
                await conn.execute(
                    text(
                        "UPDATE graph_temporal_head_nodes "
                        "SET revision_id = :rid "
                        "WHERE tenant_id = :tid AND engagement_id = :eid"
                    ),
                    {"tid": TENANT, "eid": eid, "rid": "d" * 64},
                )
        assert err.value.orig.sqlstate == "42501"
