import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blackbread.ledger.draft import EventDraft
from blackbread.ledger.errors import LedgerAccessError
from blackbread.ledger.event import AgentEvent
from blackbread.ledger.hashing import (
    GENESIS_PREV_HASH,
    HASH_ALGORITHM,
    HASH_VERSION,
    compute_event_hash,
    compute_payload_hash,
)
from blackbread.models.core import Engagement


async def append_event(session: AsyncSession, draft: EventDraft) -> AgentEvent:
    engagement = (
        await session.execute(
            select(Engagement)
            .where(
                Engagement.id == draft.engagement_id,
                Engagement.tenant_id == draft.tenant_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if engagement is None:
        raise LedgerAccessError("engagement is unavailable for the requested tenant")

    last = (
        await session.execute(
            select(AgentEvent)
            .where(
                AgentEvent.engagement_id == draft.engagement_id,
                AgentEvent.tenant_id == draft.tenant_id,
            )
            .order_by(AgentEvent.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    payload = draft.materialize_payload()
    sequence = 1 if last is None else last.sequence + 1
    prev_event_hash = GENESIS_PREV_HASH if last is None else last.event_hash
    event = AgentEvent(
        id=uuid.uuid4(),
        engagement_id=draft.engagement_id,
        tenant_id=draft.tenant_id,
        sequence=sequence,
        schema_name=draft.schema_name,
        schema_version=draft.schema_version,
        producer=draft.producer,
        correlation_id=draft.correlation_id,
        causation_id=draft.causation_id,
        occurred_at=draft.occurred_at,
        recorded_at=datetime.now(UTC),
        payload=payload,
        payload_hash=compute_payload_hash(payload),
        prev_event_hash=prev_event_hash,
        event_hash="",
        hash_algorithm=HASH_ALGORITHM,
        hash_version=HASH_VERSION,
        sensitivity=draft.sensitivity,
        redaction_refs=list(draft.redaction_refs),
    )
    event.event_hash = compute_event_hash(event)
    session.add(event)
    await session.flush()

    engagement.ledger_event_count += 1
    engagement.ledger_head_hash = event.event_hash
    await session.flush()
    return event
