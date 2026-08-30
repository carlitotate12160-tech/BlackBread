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
from blackbread.tenancy import TenantContext, bind_tenant_context
from blackbread.tenancy.errors import TenantContextError


async def _establish_tenant_context(
    session: AsyncSession,
    draft: EventDraft,
    tenant_context: TenantContext,
) -> None:
    if tenant_context.tenant_id != draft.tenant_id:
        raise TenantContextError("tenant context does not match the event draft tenant")
    await bind_tenant_context(session, tenant_context)


async def _lock_engagement(session: AsyncSession, draft: EventDraft) -> Engagement:
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
    return engagement


async def _last_event(session: AsyncSession, draft: EventDraft) -> AgentEvent | None:
    return (
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


def _build_event(draft: EventDraft, sequence: int, prev_event_hash: str) -> AgentEvent:
    payload = draft.materialize_payload()
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
    return event


async def append_event(
    session: AsyncSession,
    draft: EventDraft,
    *,
    tenant_context: TenantContext,
) -> AgentEvent:
    await _establish_tenant_context(session, draft, tenant_context)
    engagement = await _lock_engagement(session, draft)
    last = await _last_event(session, draft)
    sequence = 1 if last is None else last.sequence + 1
    prev_event_hash = GENESIS_PREV_HASH if last is None else last.event_hash
    event = _build_event(draft, sequence, prev_event_hash)
    session.add(event)
    await session.flush()
    await session.refresh(engagement)
    return event
