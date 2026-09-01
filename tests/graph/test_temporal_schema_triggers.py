"""Migration 0006 temporal schema provenance trigger tests."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

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


async def _insert_root(
    conn: AsyncConnection,
    tenant: str,
    eid: uuid.UUID,
    node_id: str,
    value: str,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO graph_temporal_scope_roots "
            "(tenant_id, engagement_id, node_id, node_family, scope_kind, canonical_value) "
            "VALUES (:tid, :eid, :nid, 'ScopeRoot', 'root_domain', :cv)"
        ),
        {"tid": tenant, "eid": eid, "nid": node_id, "cv": value},
    )


async def _insert_revision(
    conn: AsyncConnection,
    tenant: str,
    eid: uuid.UUID,
    rev: ScopeRevision,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO graph_temporal_scope_revisions "
            "(tenant_id, engagement_id, revision_id, node_id, scope_kind, canonical_value, "
            "manifest_hash, valid_from, valid_until, source_sequence, source_event_hash, "
            "source_schema_name, source_schema_version, predecessor_attestation_event_hash) "
            "VALUES (:tid, :eid, :rid, :nid, :sk, :cv, :mh, :vf, "
            ":vu, :seq, :seh, :sn, :sv, :pred)"
        ),
        {
            "tid": tenant,
            "eid": eid,
            "rid": rev.revision_id,
            "nid": rev.node_id,
            "sk": rev.scope_kind,
            "cv": rev.canonical_value,
            "mh": rev.manifest_hash,
            "vf": rev.valid_from,
            "vu": rev.valid_until,
            "seq": rev.source_sequence,
            "seh": rev.source_event_hash,
            "sn": rev.source_schema_name,
            "sv": rev.source_schema_version,
            "pred": rev.predecessor_attestation_event_hash,
        },
    )


async def _seed_v2_attestation(
    admin: AsyncEngine, tenant: str, eid: uuid.UUID, prev_hash: str
) -> str:
    """Insert a v2 attestation event that supersedes the given predecessor."""
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
        "supersedes_event_hash": prev_hash,
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
                "VALUES (:id, :eid, :tid, :seq, 'engagement.attested', 2, 'conductor', "
                ":oa, :ra, CAST(:payload AS jsonb), :ph, :pe, :eh)"
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


class TestProvenanceTrigger:
    async def test_valid_v1_revision_accepted(self, admin_engine: AsyncEngine) -> None:
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

        async with admin_engine.begin() as conn:
            await _insert_root(conn, TENANT, eid, node_id, "example.com")
            await _insert_revision(conn, TENANT, eid, rev)

    async def test_wrong_manifest_hash_rejected(self, admin_engine: AsyncEngine) -> None:
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)
        event_hash = await _seed_attestation_event(admin_engine, TENANT, eid)

        node_id = scope_root_id("root_domain", "example.com")
        rev = ScopeRevision(
            node_id=node_id,
            scope_kind="root_domain",
            canonical_value="example.com",
            manifest_hash="b" * 64,
            valid_from=FIXED_TIME,
            valid_until=FIXED_TIME + timedelta(days=7),
            source_sequence=1,
            source_event_hash=event_hash,
            source_schema_name="engagement.attested",
            source_schema_version=1,
            predecessor_attestation_event_hash=None,
        )

        async with admin_engine.begin() as conn:
            await _insert_root(conn, TENANT, eid, node_id, "example.com")
            with pytest.raises(
                IntegrityError,
                match="temporal revision does not match attestation payload",
            ):
                await _insert_revision(conn, TENANT, eid, rev)

    async def test_wrong_scope_membership_rejected(self, admin_engine: AsyncEngine) -> None:
        """A revision claiming scope membership not in the payload is rejected."""
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)
        event_hash = await _seed_attestation_event(
            admin_engine, TENANT, eid, scope={"root_domains": ["example.com"]}
        )

        node_id = scope_root_id("root_domain", "other.com")
        rev = ScopeRevision(
            node_id=node_id,
            scope_kind="root_domain",
            canonical_value="other.com",
            manifest_hash="a" * 64,
            valid_from=FIXED_TIME,
            valid_until=FIXED_TIME + timedelta(days=7),
            source_sequence=1,
            source_event_hash=event_hash,
            source_schema_name="engagement.attested",
            source_schema_version=1,
            predecessor_attestation_event_hash=None,
        )

        async with admin_engine.begin() as conn:
            await _insert_root(conn, TENANT, eid, node_id, "other.com")
            with pytest.raises(
                IntegrityError,
                match="temporal revision does not match attestation payload",
            ):
                await _insert_revision(conn, TENANT, eid, rev)

    async def test_valid_v2_revision_accepted(self, admin_engine: AsyncEngine) -> None:
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)
        v1_hash = await _seed_attestation_event(admin_engine, TENANT, eid)
        v2_hash = await _seed_v2_attestation(admin_engine, TENANT, eid, v1_hash)

        node_id = scope_root_id("root_domain", "example.com")
        rev = ScopeRevision(
            node_id=node_id,
            scope_kind="root_domain",
            canonical_value="example.com",
            manifest_hash="a" * 64,
            valid_from=FIXED_TIME,
            valid_until=FIXED_TIME + timedelta(days=7),
            source_sequence=2,
            source_event_hash=v2_hash,
            source_schema_name="engagement.attested",
            source_schema_version=2,
            predecessor_attestation_event_hash=v1_hash,
        )

        async with admin_engine.begin() as conn:
            await _insert_root(conn, TENANT, eid, node_id, "example.com")
            await _insert_revision(conn, TENANT, eid, rev)

    async def test_v2_predecessor_mismatch_rejected(self, admin_engine: AsyncEngine) -> None:
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)
        v1_hash = await _seed_attestation_event(admin_engine, TENANT, eid)
        v2_hash = await _seed_v2_attestation(admin_engine, TENANT, eid, v1_hash)

        node_id = scope_root_id("root_domain", "example.com")
        rev = ScopeRevision(
            node_id=node_id,
            scope_kind="root_domain",
            canonical_value="example.com",
            manifest_hash="a" * 64,
            valid_from=FIXED_TIME,
            valid_until=FIXED_TIME + timedelta(days=7),
            source_sequence=2,
            source_event_hash=v2_hash,
            source_schema_name="engagement.attested",
            source_schema_version=2,
            predecessor_attestation_event_hash="1" * 64,
        )

        async with admin_engine.begin() as conn:
            await _insert_root(conn, TENANT, eid, node_id, "example.com")
            with pytest.raises(IntegrityError, match="v2 revision predecessor mismatch"):
                await _insert_revision(conn, TENANT, eid, rev)

    async def test_runtime_role_v1_insert_executes_trigger(
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
            manifest_hash="b" * 64,
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
            await _insert_root(conn, TENANT, eid, node_id, "example.com")
            with pytest.raises(
                IntegrityError,
                match="temporal revision does not match attestation payload",
            ):
                await _insert_revision(conn, TENANT, eid, rev)

    async def test_runtime_role_v2_insert_executes_trigger(
        self,
        admin_engine: AsyncEngine,
        runtime_engine: AsyncEngine,
    ) -> None:
        eid = uuid.uuid4()
        await _seed_engagement(admin_engine, TENANT, eid)
        v1_hash = await _seed_attestation_event(admin_engine, TENANT, eid)
        v2_hash = await _seed_v2_attestation(admin_engine, TENANT, eid, v1_hash)

        node_id = scope_root_id("root_domain", "example.com")
        rev = ScopeRevision(
            node_id=node_id,
            scope_kind="root_domain",
            canonical_value="example.com",
            manifest_hash="a" * 64,
            valid_from=FIXED_TIME,
            valid_until=FIXED_TIME + timedelta(days=7),
            source_sequence=2,
            source_event_hash=v2_hash,
            source_schema_name="engagement.attested",
            source_schema_version=2,
            predecessor_attestation_event_hash="1" * 64,
        )

        async with runtime_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('blackbread.tenant_id', :tid, true)"),
                {"tid": TENANT},
            )
            await _insert_root(conn, TENANT, eid, node_id, "example.com")
            with pytest.raises(IntegrityError, match="v2 revision predecessor mismatch"):
                await _insert_revision(conn, TENANT, eid, rev)
