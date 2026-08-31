import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from blackbread.ledger import EventDraft, EventEnvelope, EventPayload, append_event, to_draft
from blackbread.ledger.catalog import (
    EngagementAttested,
    EngagementMode,
    EngagementScope,
    EngagementStopped,
    default_registry,
)
from blackbread.ledger.event import AgentEvent
from blackbread.ledger.hashing import (
    GENESIS_PREV_HASH,
    HASH_ALGORITHM,
    HASH_VERSION,
    compute_payload_hash,
)
from blackbread.models.core import Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context

FIXED_TIME = datetime(2026, 8, 30, 12, tzinfo=UTC)
AttestationFactory = Callable[..., EngagementAttested]
EventFactory = Callable[..., AgentEvent]
AppendPayload = Callable[[AsyncSession, Engagement, EventPayload], Awaitable[AgentEvent]]
AppendDraft = Callable[
    [AsyncSession, Engagement, str, int, dict[str, object]], Awaitable[AgentEvent]
]


@dataclass(frozen=True)
class GraphEvents:
    attestation: AttestationFactory
    append: AppendPayload
    draft: AppendDraft
    stopped: EngagementStopped


@pytest.fixture
def attestation_factory() -> AttestationFactory:
    def create(**scope_values: tuple[str, ...]) -> EngagementAttested:
        return EngagementAttested(
            manifest_hash="a" * 64,
            manifest_signature_ref="vault://manifest-signatures/one",
            attested_by="designated-user",
            mode=EngagementMode(
                knowledge="blind",
                execution="covert",
                tier="recon_only",
                pacing="short",
            ),
            scope=EngagementScope(**(scope_values or {"root_domains": ("example.com",)})),
            valid_from=FIXED_TIME,
            expires_at=FIXED_TIME + timedelta(days=7),
        )

    return create


@pytest.fixture
def event_factory() -> EventFactory:
    def create(payload: EventPayload, *, sequence: int = 1) -> AgentEvent:
        data = payload.to_ledger_payload()
        return AgentEvent(
            id=uuid.UUID(int=sequence),
            tenant_id="tenant-a",
            engagement_id=uuid.UUID(int=100),
            sequence=sequence,
            schema_name=payload.SCHEMA_NAME,
            schema_version=payload.SCHEMA_VERSION,
            producer="conductor",
            correlation_id=None,
            causation_id=None,
            occurred_at=FIXED_TIME,
            recorded_at=FIXED_TIME,
            payload=data,
            payload_hash=compute_payload_hash(data),
            prev_event_hash=GENESIS_PREV_HASH,
            event_hash=f"{sequence:064x}",
            hash_algorithm=HASH_ALGORITHM,
            hash_version=HASH_VERSION,
            sensitivity="internal",
            redaction_refs=[],
        )

    return create


@pytest.fixture
def append_payload() -> AppendPayload:
    async def append(
        session: AsyncSession,
        engagement: Engagement,
        payload: EventPayload,
    ) -> AgentEvent:
        await bind_tenant_context(session, TenantContext(engagement.tenant_id))
        event = await append_event(
            session,
            to_draft(
                payload,
                EventEnvelope(
                    tenant_id=engagement.tenant_id,
                    engagement_id=engagement.id,
                    producer="conductor",
                    occurred_at=FIXED_TIME,
                ),
                registry=default_registry(),
            ),
            tenant_context=TenantContext(engagement.tenant_id),
        )
        await session.commit()
        return event

    return append


@pytest.fixture
def append_draft() -> AppendDraft:
    async def append(
        session: AsyncSession,
        engagement: Engagement,
        schema_name: str,
        schema_version: int,
        payload: dict[str, object],
    ) -> AgentEvent:
        await bind_tenant_context(session, TenantContext(engagement.tenant_id))
        event = await append_event(
            session,
            EventDraft(
                tenant_id=engagement.tenant_id,
                engagement_id=engagement.id,
                schema_name=schema_name,
                schema_version=schema_version,
                producer="conductor",
                payload=payload,
                occurred_at=FIXED_TIME,
            ),
            tenant_context=TenantContext(engagement.tenant_id),
        )
        await session.commit()
        return event

    return append


@pytest.fixture
def stopped_event() -> EngagementStopped:
    return EngagementStopped(
        reason="operator_stop",
        stopped_by="operator-one",
        disposition="graceful_stop",
    )


@pytest.fixture
def graph_events(
    attestation_factory: AttestationFactory,
    append_payload: AppendPayload,
    append_draft: AppendDraft,
    stopped_event: EngagementStopped,
) -> GraphEvents:
    return GraphEvents(attestation_factory, append_payload, append_draft, stopped_event)
