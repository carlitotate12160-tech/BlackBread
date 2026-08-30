from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from blackbread.ledger.errors import LedgerAccessError, LedgerValidationError
from blackbread.ledger.event import AgentEvent
from blackbread.ledger.hashing import (
    GENESIS_PREV_HASH,
    HASH_ALGORITHM,
    HASH_VERSION,
    compute_event_hash,
    compute_payload_hash,
)
from blackbread.models.core import Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context


@dataclass(frozen=True, slots=True)
class ChainVerification:
    """The outcome of checking one tenant ledger at one committed snapshot."""

    ok: bool
    tenant_id: str
    engagement_id: UUID
    verified_event_count: int
    verified_head_hash: str | None
    broken_at_sequence: int | None = None
    reason: str | None = None

    @property
    def event_count(self) -> int:
        """Compatibility name for the number of rows examined."""
        return self.verified_event_count


@dataclass(frozen=True, slots=True)
class _LedgerAnchor:
    event_count: int
    head_hash: str


@dataclass(frozen=True, slots=True)
class _ChainScan:
    event_count: int
    head_hash: str
    broken_at_sequence: int | None = None
    reason: str | None = None


def _first_failure(
    event: AgentEvent,
    expected_sequence: int,
    tenant_id: str,
    expected_prev: str,
) -> str | None:
    invariant_checks = (
        (event.sequence != expected_sequence, "non-contiguous sequence"),
        (event.tenant_id != tenant_id, "tenant mismatch"),
        (event.prev_event_hash != expected_prev, "broken prev-hash link"),
        (
            event.hash_algorithm != HASH_ALGORITHM or event.hash_version != HASH_VERSION,
            "unsupported hash scheme",
        ),
    )
    invariant_failure = next(
        (reason for failed, reason in invariant_checks if failed),
        None,
    )
    if invariant_failure is not None:
        return invariant_failure
    try:
        payload_matches = compute_payload_hash(event.payload) == event.payload_hash
        event_matches = compute_event_hash(event) == event.event_hash
    except LedgerValidationError:
        return "non-canonical event data"
    if not payload_matches:
        return "payload hash mismatch"
    if not event_matches:
        return "event hash mismatch"
    return None


async def _load_anchor(
    connection: AsyncConnection,
    *,
    tenant_id: str,
    engagement_id: UUID,
) -> _LedgerAnchor:
    anchor = (
        await connection.execute(
            select(
                Engagement.ledger_event_count,
                Engagement.ledger_head_hash,
            ).where(
                Engagement.id == engagement_id,
                Engagement.tenant_id == tenant_id,
            )
        )
    ).one_or_none()
    if anchor is None:
        raise LedgerAccessError("engagement is unavailable for the requested tenant")
    return _LedgerAnchor(
        event_count=anchor.ledger_event_count,
        head_hash=anchor.ledger_head_hash,
    )


async def _scan_chain(
    connection: AsyncConnection,
    *,
    tenant_id: str,
    engagement_id: UUID,
    consumer: Callable[[AgentEvent], None] | None = None,
) -> _ChainScan:
    statement = (
        select(AgentEvent.__table__)
        .where(
            AgentEvent.engagement_id == engagement_id,
            AgentEvent.tenant_id == tenant_id,
        )
        .order_by(AgentEvent.sequence.asc())
        .execution_options(yield_per=500)
    )
    stream = await connection.stream(statement)
    expected_prev = GENESIS_PREV_HASH
    expected_sequence = 1
    event_count = 0
    try:
        async for row in stream.mappings():
            event = AgentEvent(**dict(row))
            event_count += 1
            failure = _first_failure(
                event,
                expected_sequence,
                tenant_id,
                expected_prev,
            )
            if failure is not None:
                return _ChainScan(
                    event_count=event_count,
                    head_hash=expected_prev,
                    broken_at_sequence=event.sequence,
                    reason=failure,
                )
            if consumer is not None:
                consumer(event)
            expected_prev = event.event_hash
            expected_sequence += 1
    finally:
        await stream.close()
    return _ChainScan(event_count=event_count, head_hash=expected_prev)


def _snapshot_result(
    scan: _ChainScan,
    anchor: _LedgerAnchor,
    *,
    tenant_id: str,
    engagement_id: UUID,
) -> ChainVerification:
    if scan.reason is not None:
        return ChainVerification(
            ok=False,
            tenant_id=tenant_id,
            engagement_id=engagement_id,
            verified_event_count=scan.event_count,
            verified_head_hash=None,
            broken_at_sequence=scan.broken_at_sequence,
            reason=scan.reason,
        )
    if scan.event_count != anchor.event_count:
        return ChainVerification(
            ok=False,
            tenant_id=tenant_id,
            engagement_id=engagement_id,
            verified_event_count=scan.event_count,
            verified_head_hash=None,
            broken_at_sequence=min(scan.event_count, anchor.event_count) + 1,
            reason="anchored event count mismatch",
        )
    if scan.head_hash != anchor.head_hash:
        return ChainVerification(
            ok=False,
            tenant_id=tenant_id,
            engagement_id=engagement_id,
            verified_event_count=scan.event_count,
            verified_head_hash=None,
            broken_at_sequence=scan.event_count or None,
            reason="anchored head hash mismatch",
        )
    return ChainVerification(
        ok=True,
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        verified_event_count=scan.event_count,
        verified_head_hash=scan.head_hash,
    )


async def _verify_in_snapshot(
    connection: AsyncConnection,
    *,
    tenant_id: str,
    engagement_id: UUID,
    consumer: Callable[[AgentEvent], None] | None = None,
) -> ChainVerification:
    anchor = await _load_anchor(
        connection,
        tenant_id=tenant_id,
        engagement_id=engagement_id,
    )
    scan = await _scan_chain(
        connection,
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        consumer=consumer,
    )
    return _snapshot_result(
        scan,
        anchor,
        tenant_id=tenant_id,
        engagement_id=engagement_id,
    )


async def verify_snapshot(
    connection: AsyncConnection,
    *,
    tenant_id: str,
    engagement_id: UUID,
    consumer: Callable[[AgentEvent], None] | None = None,
) -> ChainVerification:
    """Verify the ledger inside a caller-owned committed snapshot.

    The connection must have an open REPEATABLE READ, READ ONLY transaction with
    the tenant context already bound. The consumer receives events in sequence only
    after each event passes its chain invariants; callers must still require ``ok``
    before trusting any derived state.
    """
    return await _verify_in_snapshot(
        connection,
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        consumer=consumer,
    )


async def verify_chain(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    engagement_id: UUID,
) -> ChainVerification:
    """Verify a ledger using an independently owned committed PostgreSQL snapshot.

    A successful result describes only the exact REPEATABLE READ snapshot checked;
    concurrent commits can make its head stale before this function returns.
    """
    async with engine.connect() as acquired:
        connection = await acquired.execution_options(isolation_level="REPEATABLE READ")
        async with connection.begin():
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            await bind_tenant_context(connection, TenantContext(tenant_id))
            return await _verify_in_snapshot(
                connection,
                tenant_id=tenant_id,
                engagement_id=engagement_id,
            )
