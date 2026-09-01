"""Migration 0006 temporal schema deferred-foreign-key tests."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from blackbread.graph.domain import scope_root_id
from blackbread.graph.revision import ScopeRevision
from tests.graph.conftest import (
    FIXED_TIME,
    _seed_attestation_event,
    _seed_engagement,
)
from tests.graph.conftest import (
    SCHEMA_TENANT as TENANT,
)


async def _seed_successor_attestation(
    admin: AsyncEngine, tenant: str, eid: uuid.UUID, prev_hash: str
) -> str:
    """Insert a second v1 attestation in the same engagement, advancing the ledger head."""
    manifest = "a" * 64
    valid_from = FIXED_TIME
    expires_at = FIXED_TIME + timedelta(days=7)
    scope = {"root_domains": ["example.com"]}
    payload = {
        "manifest_hash": manifest,
        "manifest_signature_ref": "vault://test",
        "attested_by": "tester",
        "mode": {
            "knowledge": "blind",
            "execution": "covert",
            "tier": "recon_only",
            "pacing": "short",
        },
        "scope": scope,
        "valid_from": valid_from.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    payload_json = json.dumps(payload, sort_keys=True, default=str)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
    nonce = uuid.uuid4().hex
    preimage = f"{prev_hash}:{payload_hash}:{eid}:{nonce}:2"
    event_hash = hashlib.sha256(preimage.encode()).hexdigest()
    event_id = uuid.uuid4()

    async with admin.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO agent_events "
                "(id, engagement_id, tenant_id, sequence, schema_name, schema_version, "
                "producer, occurred_at, recorded_at, payload, payload_hash, "
                "prev_event_hash, event_hash) "
                "VALUES (:id, :eid, :tid, :seq, 'engagement.attested', 1, "
                "'conductor', :oa, :ra, CAST(:payload AS jsonb), :ph, :pe, :eh)"
            ),
            {
                "id": event_id,
                "eid": eid,
                "tid": tenant,
                "seq": 2,
                "oa": FIXED_TIME,
                "ra": FIXED_TIME,
                "payload": payload_json,
                "ph": payload_hash,
                "pe": prev_hash,
                "eh": event_hash,
            },
        )
    return event_hash


class TestDeferredFK:
    async def test_snapshot_head_deferred_fk_accepted(
        self,
        admin_engine: AsyncEngine,
        runtime_engine: AsyncEngine,
    ) -> None:
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)
        event_hash = await _seed_attestation_event(admin_engine, TENANT, eid)

        node_id = scope_root_id("root_domain", "example.com")
        rev = ScopeRevision(
            node_id=node_id,
            scope_kind="root_domain",
            canonical_value="example.com",
            manifest_hash="a" * 64,
            valid_from=FIXED_TIME,
            valid_until=FIXED_TIME + timedelta(days=7),
            source_sequence=1,
            source_event_hash=event_hash,
            source_schema_name="engagement.attested",
            source_schema_version=1,
            predecessor_attestation_event_hash=None,
        )

        async with runtime_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('blackbread.tenant_id', :tid, true)"),
                {"tid": TENANT},
            )
            await conn.execute(text("SET CONSTRAINTS fk_graph_temporal_head_lineage DEFERRED"))
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_scope_roots "
                    "(tenant_id, engagement_id, node_id, node_family, "
                    "scope_kind, canonical_value) "
                    "VALUES (:tid, :eid, :nid, 'ScopeRoot', 'root_domain', 'example.com')"
                ),
                {"tid": TENANT, "eid": eid, "nid": node_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_scope_revisions "
                    "(tenant_id, engagement_id, revision_id, node_id, scope_kind, "
                    "canonical_value, manifest_hash, valid_from, valid_until, "
                    "source_sequence, source_event_hash, source_schema_name, "
                    "source_schema_version, predecessor_attestation_event_hash) "
                    "VALUES (:tid, :eid, :rid, :nid, 'root_domain', 'example.com', "
                    ":mh, :vf, :vu, :seq, :seh, 'engagement.attested', 1, NULL)"
                ),
                {
                    "tid": TENANT,
                    "eid": eid,
                    "rid": rev.revision_id,
                    "nid": node_id,
                    "mh": "a" * 64,
                    "vf": FIXED_TIME,
                    "vu": FIXED_TIME + timedelta(days=7),
                    "seq": 1,
                    "seh": event_hash,
                },
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
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_head_nodes "
                    "(tenant_id, engagement_id, node_id, revision_id, source_event_hash) "
                    "VALUES (:tid, :eid, :nid, :rid, :seh)"
                ),
                {
                    "tid": TENANT,
                    "eid": eid,
                    "nid": node_id,
                    "rid": rev.revision_id,
                    "seh": event_hash,
                },
            )
            await conn.execute(text("SET CONSTRAINTS fk_graph_temporal_head_lineage IMMEDIATE"))

    async def test_head_wrong_source_rejected(
        self,
        admin_engine: AsyncEngine,
        runtime_engine: AsyncEngine,
    ) -> None:
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)
        event_a = await _seed_attestation_event(admin_engine, TENANT, eid)
        event_b = await _seed_successor_attestation(admin_engine, TENANT, eid, event_a)

        node_id = scope_root_id("root_domain", "example.com")
        rev_a = ScopeRevision(
            node_id=node_id,
            scope_kind="root_domain",
            canonical_value="example.com",
            manifest_hash="a" * 64,
            valid_from=FIXED_TIME,
            valid_until=FIXED_TIME + timedelta(days=7),
            source_sequence=1,
            source_event_hash=event_a,
            source_schema_name="engagement.attested",
            source_schema_version=1,
            predecessor_attestation_event_hash=None,
        )
        rev_b = ScopeRevision(
            node_id=node_id,
            scope_kind="root_domain",
            canonical_value="example.com",
            manifest_hash="a" * 64,
            valid_from=FIXED_TIME,
            valid_until=FIXED_TIME + timedelta(days=7),
            source_sequence=2,
            source_event_hash=event_b,
            source_schema_name="engagement.attested",
            source_schema_version=1,
            predecessor_attestation_event_hash=None,
        )

        async with runtime_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('blackbread.tenant_id', :tid, true)"),
                {"tid": TENANT},
            )
            await conn.execute(text("SET CONSTRAINTS fk_graph_temporal_head_lineage DEFERRED"))
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_scope_roots "
                    "(tenant_id, engagement_id, node_id, node_family, "
                    "scope_kind, canonical_value) "
                    "VALUES (:tid, :eid, :nid, 'ScopeRoot', 'root_domain', 'example.com')"
                ),
                {"tid": TENANT, "eid": eid, "nid": node_id},
            )
            for revision in (rev_a, rev_b):
                await conn.execute(
                    text(
                        "INSERT INTO graph_temporal_scope_revisions "
                        "(tenant_id, engagement_id, revision_id, node_id, scope_kind, "
                        "canonical_value, manifest_hash, valid_from, valid_until, "
                        "source_sequence, source_event_hash, source_schema_name, "
                        "source_schema_version, predecessor_attestation_event_hash) "
                        "VALUES (:tid, :eid, :rid, :nid, 'root_domain', 'example.com', "
                        ":mh, :vf, :vu, :seq, :seh, 'engagement.attested', 1, NULL)"
                    ),
                    {
                        "tid": TENANT,
                        "eid": eid,
                        "rid": revision.revision_id,
                        "nid": node_id,
                        "mh": "a" * 64,
                        "vf": FIXED_TIME,
                        "vu": FIXED_TIME + timedelta(days=7),
                        "seq": revision.source_sequence,
                        "seh": revision.source_event_hash,
                    },
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
                {"tid": TENANT, "eid": eid, "eh": event_a, "sr": "b" * 64},
            )
            await conn.execute(
                text(
                    "INSERT INTO graph_temporal_head_nodes "
                    "(tenant_id, engagement_id, node_id, revision_id, source_event_hash) "
                    "VALUES (:tid, :eid, :nid, :rid, :seh)"
                ),
                {
                    "tid": TENANT,
                    "eid": eid,
                    "nid": node_id,
                    "rid": rev_b.revision_id,
                    "seh": event_b,
                },
            )
            with pytest.raises(IntegrityError, match="fk_graph_temporal_head_lineage"):
                await conn.execute(text("SET CONSTRAINTS fk_graph_temporal_head_lineage IMMEDIATE"))
