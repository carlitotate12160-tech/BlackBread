import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from blackbread.models.base import Base

EMPTY_LEDGER_HEAD = "0" * 64


class PlatformMetadata(Base):
    __tablename__ = "platform_metadata"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_clients_id_tenant_id"),
        CheckConstraint("char_length(btrim(name)) > 0", name="ck_clients_name_not_blank"),
        CheckConstraint(
            "char_length(btrim(tenant_id)) > 0",
            name="ck_clients_tenant_not_blank",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Engagement(Base):
    __tablename__ = "engagements"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_engagements_id_tenant_id"),
        ForeignKeyConstraint(
            ["client_id", "tenant_id"],
            ["clients.id", "clients.tenant_id"],
            name="fk_engagements_client_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "char_length(btrim(tenant_id)) > 0",
            name="ck_engagements_tenant_not_blank",
        ),
        CheckConstraint(
            "char_length(btrim(status)) > 0",
            name="ck_engagements_status_not_blank",
        ),
        CheckConstraint(
            "ledger_lock_token = 0",
            name="ck_engagements_ledger_lock_token",
        ),
        CheckConstraint(
            "ledger_event_count >= 0",
            name="ck_engagements_ledger_event_count",
        ),
        CheckConstraint(
            "ledger_head_hash ~ '^[0-9a-f]{64}$'",
            name="ck_engagements_ledger_head_hash",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="created",
        server_default=text("'created'"),
    )
    ledger_lock_token: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="Immutable sentinel used only to authorize engagement row locks.",
    )
    ledger_event_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    ledger_head_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=EMPTY_LEDGER_HEAD,
        server_default=text(f"'{EMPTY_LEDGER_HEAD}'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
