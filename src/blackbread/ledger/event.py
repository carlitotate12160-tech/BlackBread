import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from blackbread.ledger.hashing import (
    GENESIS_PREV_HASH,
    HASH_ALGORITHM,
    HASH_HEX_LENGTH,
    HASH_VERSION,
)
from blackbread.models.base import Base

__all__ = ["AgentEvent", "GENESIS_PREV_HASH", "HASH_HEX_LENGTH"]


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["engagement_id", "tenant_id"],
            ["engagements.id", "engagements.tenant_id"],
            name="fk_agent_events_engagement_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "engagement_id",
            "sequence",
            name="uq_agent_events_engagement_sequence",
        ),
        UniqueConstraint("event_hash", name="uq_agent_events_event_hash"),
        Index(
            "ix_agent_events_tenant_engagement_sequence",
            "tenant_id",
            "engagement_id",
            "sequence",
        ),
        CheckConstraint("sequence >= 1", name="ck_agent_events_sequence_positive"),
        CheckConstraint(
            "schema_version >= 1",
            name="ck_agent_events_schema_version_positive",
        ),
        CheckConstraint(
            "char_length(btrim(schema_name)) > 0",
            name="ck_agent_events_schema_name_not_blank",
        ),
        CheckConstraint(
            "char_length(btrim(producer)) > 0",
            name="ck_agent_events_producer_not_blank",
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_agent_events_payload_object",
        ),
        CheckConstraint(
            "jsonb_typeof(redaction_refs) = 'array'",
            name="ck_agent_events_redaction_refs_array",
        ),
        CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="ck_agent_events_payload_hash_hex",
        ),
        CheckConstraint(
            "prev_event_hash ~ '^[0-9a-f]{64}$'",
            name="ck_agent_events_prev_hash_hex",
        ),
        CheckConstraint(
            "event_hash ~ '^[0-9a-f]{64}$'",
            name="ck_agent_events_event_hash_hex",
        ),
        CheckConstraint(
            "hash_algorithm = 'sha256'",
            name="ck_agent_events_hash_algorithm",
        ),
        CheckConstraint("hash_version = 1", name="ck_agent_events_hash_version"),
        CheckConstraint(
            "sensitivity IN ('public', 'internal', 'confidential', 'restricted')",
            name="ck_agent_events_sensitivity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    engagement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    schema_name: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    producer: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(HASH_HEX_LENGTH), nullable=False)
    prev_event_hash: Mapped[str] = mapped_column(String(HASH_HEX_LENGTH), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(HASH_HEX_LENGTH), nullable=False)
    hash_algorithm: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=HASH_ALGORITHM,
        server_default=text("'sha256'"),
    )
    hash_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=HASH_VERSION,
        server_default=text("1"),
    )
    sensitivity: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="internal",
        server_default=text("'internal'"),
    )
    redaction_refs: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
