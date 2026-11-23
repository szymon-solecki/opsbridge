from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Enum as SqlEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from backend.app.models.base import Base
from backend.app.models.enums import ActorType

if TYPE_CHECKING:
    from backend.app.models.activity import ActivityFeed
    from backend.app.models.file import File
    from backend.app.models.integration import DeliveryExpectation


class DeliveryEvent(Base):
    __tablename__ = "delivery_events"
    __table_args__ = (
        UniqueConstraint("id", "delivery_expectation_id", name="uq_delivery_events_id_delivery_expectation"),
        ForeignKeyConstraint(
            ["file_id", "delivery_expectation_id"],
            ["files.id", "files.delivery_expectation_id"],
            name="fk_delivery_events_file_same_delivery",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "event_type <> 'ManualReprocessingRequested' OR "
            "(actor_type = 'OPERATOR' AND actor_reference IS NOT NULL "
            "AND length(trim(actor_reference)) > 0)",
            name="manual_reprocessing_actor",
        ),
        Index(
            "ix_delivery_events_delivery_time",
            "delivery_expectation_id",
            text("occurred_at DESC"),
            text("id DESC"),
        ),
        Index("ix_delivery_events_file_time", "file_id", text("occurred_at DESC")),
        Index("ix_delivery_events_type_time", "event_type", text("occurred_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    delivery_expectation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("delivery_expectations.id", ondelete="RESTRICT"), nullable=False
    )
    file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    actor_type: Mapped[ActorType] = mapped_column(
        SqlEnum(ActorType, name="actor_type", values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
        default=ActorType.SYSTEM,
        server_default=text("'SYSTEM'"),
    )
    actor_reference: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[dict | None] = mapped_column(JSONB)

    delivery_expectation: Mapped[DeliveryExpectation] = relationship(back_populates="events")
    file: Mapped[File | None] = relationship(
        "File",
        primaryjoin=(
            "and_(DeliveryEvent.file_id == File.id, "
            "DeliveryEvent.delivery_expectation_id == File.delivery_expectation_id)"
        ),
        foreign_keys="DeliveryEvent.file_id",
        back_populates="events",
    )
    outbox_event: Mapped[OutboxEvent | None] = relationship(back_populates="delivery_event", uselist=False)
    activity_entry: Mapped[ActivityFeed | None] = relationship(back_populates="source_event", uselist=False)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_outbox_events_event_id"),
        CheckConstraint("publication_attempts >= 0", name="nonnegative_publication_attempts"),
        CheckConstraint("published_at IS NULL OR failed_at IS NULL", name="single_terminal_publication_state"),
        CheckConstraint(
            "(published_at IS NULL AND failed_at IS NULL) OR next_attempt_at IS NULL",
            name="terminal_event_has_no_retry_schedule",
        ),
        Index(
            "ix_outbox_events_pending",
            "next_attempt_at",
            "created_at",
            postgresql_where=text("published_at IS NULL AND failed_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("delivery_events.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    publication_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    delivery_event: Mapped[DeliveryEvent] = relationship(back_populates="outbox_event")
    inbox_event: Mapped[InboxEvent | None] = relationship(back_populates="outbox_event", uselist=False)


class InboxEvent(Base):
    __tablename__ = "inbox_events"

    event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("outbox_events.event_id", ondelete="RESTRICT"), primary_key=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB)

    outbox_event: Mapped[OutboxEvent] = relationship(back_populates="inbox_event")
