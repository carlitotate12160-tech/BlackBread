from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    ok: bool
    event_count: int
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


async def verify_chain(
    session: AsyncSession,
    *,
    tenant_id: str,
    engagement_id: UUID,
) -> ChainVerification:
    engagement = (
        await session.execute(
            select(Engagement).where(
                Engagement.id == engagement_id,
                Engagement.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if engagement is None:
        raise LedgerAccessError("engagement is unavailable for the requested tenant")

    count_result = await session.execute(
        select(func.count())
        .select_from(AgentEvent)
        .where(
            AgentEvent.engagement_id == engagement_id,
            AgentEvent.tenant_id == tenant_id,
        )
    )
    event_count = int(count_result.scalar_one())
    statement = (
        select(AgentEvent)
        .where(
            AgentEvent.engagement_id == engagement_id,
            AgentEvent.tenant_id == tenant_id,
        )
        .order_by(AgentEvent.sequence.asc())
        .execution_options(populate_existing=True, yield_per=500)
    )
    stream = await session.stream_scalars(statement)
    expected_prev = GENESIS_PREV_HASH
    expected_sequence = 1
    try:
        async for event in stream:
            failure = _first_failure(
                event,
                expected_sequence,
                engagement.tenant_id,
                expected_prev,
            )
            if failure is not None:
                return ChainVerification(
                    ok=False,
                    event_count=event_count,
                    broken_at_sequence=event.sequence,
                    reason=failure,
                )
            expected_prev = event.event_hash
            expected_sequence += 1
    finally:
        await stream.close()

    return ChainVerification(ok=True, event_count=event_count)
