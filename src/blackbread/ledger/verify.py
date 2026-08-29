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


async def _verify_in_snapshot(
    connection: AsyncConnection,
    *,
    tenant_id: str,
    engagement_id: UUID,
) -> ChainVerification:
    anchor = (
        await connection.execute(
            select(
                Engagement.tenant_id,
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
                return ChainVerification(
                    ok=False,
                    tenant_id=tenant_id,
                    engagement_id=engagement_id,
                    verified_event_count=event_count,
                    verified_head_hash=None,
                    broken_at_sequence=event.sequence,
                    reason=failure,
                )
            expected_prev = event.event_hash
            expected_sequence += 1
    finally:
        await stream.close()

    if event_count != anchor.ledger_event_count:
        return ChainVerification(
            ok=False,
            tenant_id=tenant_id,
            engagement_id=engagement_id,
            verified_event_count=event_count,
            verified_head_hash=None,
            broken_at_sequence=min(event_count, anchor.ledger_event_count) + 1,
            reason="anchored event count mismatch",
        )
    if expected_prev != anchor.ledger_head_hash:
        return ChainVerification(
            ok=False,
            tenant_id=tenant_id,
            engagement_id=engagement_id,
            verified_event_count=event_count,
            verified_head_hash=None,
            broken_at_sequence=event_count or None,
            reason="anchored head hash mismatch",
        )
    return ChainVerification(
        ok=True,
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        verified_event_count=event_count,
        verified_head_hash=expected_prev,
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
            return await _verify_in_snapshot(
                connection,
                tenant_id=tenant_id,
                engagement_id=engagement_id,
            )
