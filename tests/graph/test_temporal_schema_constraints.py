"""Migration 0006 temporal schema constraint tests."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from blackbread.graph.domain import scope_root_id
from tests.graph.conftest import (
    FIXED_TIME,
    _seed_attestation_event,
    _seed_engagement,
)
from tests.graph.conftest import (
    SCHEMA_TENANT as TENANT,
)


class TestConstraints:
    async def test_verified_event_count_minimum(self, admin_engine: AsyncEngine) -> None:
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)

        async with admin_engine.begin() as conn:
            with pytest.raises(IntegrityError, match="ck_graph_temporal_snapshots_event_count"):
                await conn.execute(
                    text(
                        "INSERT INTO graph_temporal_projection_snapshots "
                        "(tenant_id, engagement_id, verified_event_count, verified_head_hash, "
                        "ledger_hash_algorithm, ledger_hash_version, temporal_projector_version, "
                        "state_root_version, scope_canonicalization_version, state_root, "
                        "lineage_head_hash, lineage_head_sequence) "
                        "VALUES (:tid, :eid, 0, :eh, 'sha256', 1, 2, 2, 1, :sr, :eh, 1)"
                    ),
                    {"tid": TENANT, "eid": eid, "eh": "a" * 64, "sr": "b" * 64},
                )

    async def test_lineage_head_sequence_constraints(self, admin_engine: AsyncEngine) -> None:
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)
        event_hash = await _seed_attestation_event(admin_engine, TENANT, eid)

        async with admin_engine.begin() as conn:
            with pytest.raises(
                IntegrityError, match="ck_graph_temporal_snapshots_lineage_head_seq_max"
            ):
                await conn.execute(
                    text(
                        "INSERT INTO graph_temporal_projection_snapshots "
                        "(tenant_id, engagement_id, verified_event_count, verified_head_hash, "
                        "ledger_hash_algorithm, ledger_hash_version, temporal_projector_version, "
                        "state_root_version, scope_canonicalization_version, state_root, "
                        "lineage_head_hash, lineage_head_sequence) "
                        "VALUES (:tid, :eid, 1, :eh, 'sha256', 1, 2, 2, 1, :sr, :eh, 2)"
                    ),
                    {"tid": TENANT, "eid": eid, "eh": event_hash, "sr": "b" * 64},
                )

    async def test_revision_predecessor_constraint(self, admin_engine: AsyncEngine) -> None:
        """v1 attestation must have NULL predecessor; v2 must have non-NULL."""
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)
        event_hash = await _seed_attestation_event(admin_engine, TENANT, eid)

        node_id = scope_root_id("root_domain", "example.com")
        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_scope_roots "
                    "(tenant_id, engagement_id, node_id, node_family, scope_kind, canonical_value) "
                    "VALUES (:tid, :eid, :nid, 'ScopeRoot', 'root_domain', 'example.com')"
                ),
                {"tid": TENANT, "eid": eid, "nid": node_id},
            )
            with pytest.raises(IntegrityError, match="ck_graph_temporal_revisions_predecessor"):
                await conn.execute(
                    text(
                        "INSERT INTO graph_temporal_scope_revisions "
                        "(tenant_id, engagement_id, revision_id, node_id, scope_kind, "
                        "canonical_value, manifest_hash, valid_from, valid_until, "
                        "source_sequence, source_event_hash, source_schema_name, "
                        "source_schema_version, predecessor_attestation_event_hash) "
                        "VALUES (:tid, :eid, :rid, :nid, 'root_domain', 'example.com', "
                        ":mh, :vf, :vu, 1, :eh, 'engagement.attested', 1, :pred)"
                    ),
                    {
                        "tid": TENANT,
                        "eid": eid,
                        "rid": "c" * 64,
                        "nid": node_id,
                        "mh": "a" * 64,
                        "vf": FIXED_TIME,
                        "vu": FIXED_TIME + timedelta(days=7),
                        "eh": event_hash,
                        "pred": "d" * 64,
                    },
                )
