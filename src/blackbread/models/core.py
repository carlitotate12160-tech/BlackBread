import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from blackbread.models.base import Base


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        CheckConstraint("char_length(btrim(name)) > 0", name="ck_clients_name_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"),
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
