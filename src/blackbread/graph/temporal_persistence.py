"""Durable temporal publication PostgreSQL adapter.

B3a scope: publish-only. Cold reconstruction is b3b.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from blackbread.graph.domain import GraphProjectionError
from blackbread.graph.revision import ScopeRevision
from blackbread.graph.temporal_publication import (
    TemporalPublication,
    TemporalPublicationRead,
    validate_temporal_publication,
)
from blackbread.ledger.errors import LedgerAccessError
from blackbread.tenancy import TenantContext, bind_tenant_context

_ANCHOR = text(
    "SELECT ledger_event_count, ledger_head_hash FROM engagements WHERE tenant_id = :tenant_id AND id = :engagement_id FOR UPDATE"
)
_ANCHOR_SHARED = text(
    "SELECT ledger_event_count, ledger_head_hash FROM engagements WHERE tenant_id = :tenant_id AND id = :engagement_id"
)
_SELECT_SNAPSHOT = text(
    "SELECT * FROM graph_temporal_projection_snapshots WHERE tenant_id = :tenant_id AND engagement_id = :engagement_id"
)
_SELECT_ROOTS = text(
    "SELECT * FROM graph_temporal_scope_roots WHERE tenant_id = :tenant_id AND engagement_id = :engagement_id"
)
_SELECT_REVISIONS = text(
    "SELECT * FROM graph_temporal_scope_revisions WHERE tenant_id = :tenant_id AND engagement_id = :engagement_id ORDER BY source_sequence, revision_id"
)
_SELECT_HEADS = text(
    "SELECT * FROM graph_temporal_head_nodes WHERE tenant_id = :tenant_id AND engagement_id = :engagement_id"
)
_DEFER_HEAD_FK = text("SET CONSTRAINTS fk_graph_temporal_head_lineage DEFERRED")
_FORCE_HEAD_FK = text("SET CONSTRAINTS fk_graph_temporal_head_lineage IMMEDIATE")
_INSERT_ROOT = text(
    "INSERT INTO graph_temporal_scope_roots (tenant_id, engagement_id, node_id, node_family, scope_kind, canonical_value) VALUES (:tenant_id, :engagement_id, :node_id, 'ScopeRoot', :scope_kind, :canonical_value) ON CONFLICT (tenant_id, engagement_id, node_id) DO NOTHING"
)
_INSERT_REVISION = text(
    "INSERT INTO graph_temporal_scope_revisions (tenant_id, engagement_id, revision_id, node_id, scope_kind, canonical_value, manifest_hash, valid_from, valid_until, source_sequence, source_event_hash, source_schema_name, source_schema_version, predecessor_attestation_event_hash) VALUES (:tenant_id, :engagement_id, :revision_id, :node_id, :scope_kind, :canonical_value, :manifest_hash, :valid_from, :valid_until, :source_sequence, :source_event_hash, :source_schema_name, :source_schema_version, :predecessor_attestation_event_hash) ON CONFLICT (tenant_id, engagement_id, revision_id) DO NOTHING"
)
_UPSERT_SNAPSHOT = text(
    "INSERT INTO graph_temporal_projection_snapshots (tenant_id, engagement_id, verified_event_count, verified_head_hash, ledger_hash_algorithm, ledger_hash_version, temporal_projector_version, state_root_version, scope_canonicalization_version, state_root, lineage_head_hash, lineage_head_sequence) VALUES (:tenant_id, :engagement_id, :verified_event_count, :verified_head_hash, 'sha256', 1, 2, 2, 1, :state_root, :lineage_head_hash, :lineage_head_sequence) ON CONFLICT (tenant_id, engagement_id) DO UPDATE SET verified_event_count = EXCLUDED.verified_event_count, verified_head_hash = EXCLUDED.verified_head_hash, state_root = EXCLUDED.state_root, lineage_head_hash = EXCLUDED.lineage_head_hash, lineage_head_sequence = EXCLUDED.lineage_head_sequence"
)
_DELETE_HEADS = text(
    "DELETE FROM graph_temporal_head_nodes WHERE tenant_id = :tenant_id AND engagement_id = :engagement_id"
)
_INSERT_HEAD = text(
    "INSERT INTO graph_temporal_head_nodes (tenant_id, engagement_id, node_id, revision_id, source_event_hash) VALUES (:tenant_id, :engagement_id, :node_id, :revision_id, :source_event_hash)"
)


def _root_key(node_id: str, scope_kind: str, canonical_value: str) -> tuple[str, str, str]:
    return node_id, scope_kind, canonical_value


def _revision_fields(rev: ScopeRevision) -> dict[str, object]:
    return {k: getattr(rev, k) for k in ("revision_id", "node_id", "scope_kind", "canonical_value", "manifest_hash", "valid_from", "valid_until", "source_sequence", "source_event_hash", "source_schema_name", "source_schema_version", "predecessor_attestation_event_hash")}


def _row_matches_revision(row: RowMapping, rev: ScopeRevision) -> bool:
    return all((row[key] == value for key, value in _revision_fields(rev).items()))


def _row_matches_root(row: RowMapping, root: tuple[str, str, str]) -> bool:
    return bool(row["node_id"] == root[0] and row["scope_kind"] == root[1] and row["canonical_value"] == root[2])


class _TemporalStore:
    def __init__(self, conn: AsyncConnection, tenant_id: str, eid: UUID) -> None:
        self._conn = conn
        self._key: dict[str, object] = {"tenant_id": tenant_id, "engagement_id": eid}

    async def lock_anchor(self) -> tuple[int, str]:
        row = (await self._conn.execute(_ANCHOR, self._key)).one_or_none()
        if row is None:
            raise LedgerAccessError("engagement unavailable")
        return row.ledger_event_count, row.ledger_head_hash

    async def existing_snapshot(self) -> RowMapping | None:
        return (await self._conn.execute(_SELECT_SNAPSHOT, self._key)).mappings().one_or_none()

    async def existing_roots(self) -> Sequence[RowMapping]:
        return (await self._conn.execute(_SELECT_ROOTS, self._key)).mappings().all()

    async def existing_revisions(self) -> Sequence[RowMapping]:
        return (await self._conn.execute(_SELECT_REVISIONS, self._key)).mappings().all()

    async def publish(self, pub: TemporalPublication) -> TemporalPublicationRead:
        live_count, live_hash = await self.lock_anchor()
        # -- linearization-point freshness --
        if pub.verified_event_count == live_count and pub.verified_head_hash != live_hash:
            raise GraphProjectionError("verified candidate diverges from live ledger anchor")
        if pub.verified_event_count > live_count:
            raise GraphProjectionError("candidate anchor exceeds live ledger")
        is_current = (pub.verified_event_count, pub.verified_head_hash) == (live_count, live_hash)
        # -- monotonic history --
        snap = await self.existing_snapshot()
        if snap is not None:
            return await self._update(pub, snap, is_current)
        await self._first_publish(pub)
        return TemporalPublicationRead(pub, is_current)

    async def _first_publish(self, pub: TemporalPublication) -> None:
        await self._insert_roots(pub)
        await self._insert_revisions(pub)
        await self._conn.execute(_UPSERT_SNAPSHOT, self._snapshot_params(pub))
        await self._insert_heads(pub)

    async def _update(
        self,
        pub: TemporalPublication,
        snap: RowMapping,
        is_current: bool,
    ) -> TemporalPublicationRead:
        existing_count = snap["verified_event_count"]
        if pub.verified_event_count < existing_count:
            raise GraphProjectionError("publication anchor regression")
        if pub.verified_event_count == existing_count:
            if (pub.verified_head_hash == snap["verified_head_hash"] and pub.state_root == snap["state_root"] and pub.lineage.lineage_head_hash == snap["lineage_head_hash"]):
                return TemporalPublicationRead(pub, is_current)
            raise GraphProjectionError("publication diverges from existing snapshot at same anchor")
        # newer anchor — validate monotonic history
        await self._validate_monotonic_history(pub)
        head_changed = pub.lineage.lineage_head_hash != snap["lineage_head_hash"]
        root_changed = pub.state_root != snap["state_root"]
        if head_changed or root_changed:
            await self._insert_roots(pub)
            await self._insert_revisions(pub)
            await self._conn.execute(_UPSERT_SNAPSHOT, self._snapshot_params(pub))
            await self._conn.execute(_DELETE_HEADS, self._key)
            await self._insert_heads(pub)
        else:
            # graph-no-op anchor advance
            await self._conn.execute(_UPSERT_SNAPSHOT, self._snapshot_params(pub))
        return TemporalPublicationRead(pub, is_current)

    async def _validate_monotonic_history(self, pub: TemporalPublication) -> None:
        existing_roots = await self.existing_roots()
        incoming_root_keys = {
            (r.node_id, r.scope_kind, r.canonical_value)
            for g in pub.lineage.groups
            for r in g.revisions
        }
        for row in existing_roots:
            key = (row["node_id"], row["scope_kind"], row["canonical_value"])
            if key not in incoming_root_keys:
                raise GraphProjectionError("publication truncates persisted stable root")
            if not _row_matches_root(row, key):
                raise GraphProjectionError("publication rewrites persisted stable root")
        existing_revisions = await self.existing_revisions()
        incoming_revisions = {r.revision_id: r for g in pub.lineage.groups for r in g.revisions}
        for row in existing_revisions:
            rid = row["revision_id"]
            if rid not in incoming_revisions:
                raise GraphProjectionError("publication truncates persisted history")
            if not _row_matches_revision(row, incoming_revisions[rid]):
                raise GraphProjectionError("publication rewrites persisted revision")

    async def _insert_roots(self, pub: TemporalPublication) -> None:
        seen: set[str] = set()
        for group in pub.lineage.groups:
            for rev in group.revisions:
                if rev.node_id in seen:
                    continue
                seen.add(rev.node_id)
                params = {
                    **self._key,
                    "node_id": rev.node_id,
                    "scope_kind": rev.scope_kind,
                    "canonical_value": rev.canonical_value,
                }
                result = await self._conn.execute(_INSERT_ROOT, params)
                if result.rowcount == 0:
                    rows = await self.existing_roots()
                    match = next((r for r in rows if r["node_id"] == rev.node_id), None)
                    if match is None or not _row_matches_root(
                        match, (rev.node_id, rev.scope_kind, rev.canonical_value)
                    ):
                        raise GraphProjectionError("stable root identity conflict")

    async def _insert_revisions(self, pub: TemporalPublication) -> None:
        for group in pub.lineage.groups:
            for rev in group.revisions:
                params = {**self._key, **_revision_fields(rev)}
                result = await self._conn.execute(_INSERT_REVISION, params)
                if result.rowcount == 0:
                    rows = await self.existing_revisions()
                    match = next((r for r in rows if r["revision_id"] == rev.revision_id), None)
                    if match is None or not _row_matches_revision(match, rev):
                        raise GraphProjectionError("revision identity conflict")

    async def _insert_heads(self, pub: TemporalPublication) -> None:
        final_group = pub.lineage.groups[-1]
        for rev in final_group.revisions:
            params = {
                **self._key,
                "node_id": rev.node_id,
                "revision_id": rev.revision_id,
                "source_event_hash": final_group.source_event_hash,
            }
            await self._conn.execute(_INSERT_HEAD, params)

    def _snapshot_params(self, pub: TemporalPublication) -> dict[str, object]:
        final_group = pub.lineage.groups[-1]
        return {
            **self._key,
            "verified_event_count": pub.verified_event_count,
            "verified_head_hash": pub.verified_head_hash,
            "state_root": pub.state_root,
            "lineage_head_hash": pub.lineage.lineage_head_hash,
            "lineage_head_sequence": final_group.source_sequence,
        }


async def _publish_temporal_publication(
    engine: AsyncEngine,
    publication: TemporalPublication,
) -> TemporalPublicationRead:
    """Validate and atomically persist a temporal publication."""
    validate_temporal_publication(publication)
    async with engine.begin() as connection:
        await bind_tenant_context(connection, TenantContext(publication.tenant_id))
        await connection.execute(_DEFER_HEAD_FK)
        store = _TemporalStore(connection, publication.tenant_id, publication.engagement_id)
        result = await store.publish(publication)
        await connection.execute(_FORCE_HEAD_FK)
        return result
