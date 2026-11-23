from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from backend.app.models.base import Base

if TYPE_CHECKING:
    from backend.app.models.event import DeliveryEvent
    from backend.app.models.integration import DeliveryExpectation


class ActivityFeed(Base):
    __tablename__ = "activity_feed"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_event_id", "delivery_expectation_id"],
            ["delivery_events.id", "delivery_events.delivery_expectation_id"],
            name="fk_activity_feed_source_event_same_delivery",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_activity_feed_chronological",
            text("occurred_at DESC"),
            text("source_event_id DESC"),
        ),
        Index(
            "ix_activity_feed_delivery_chronological",
            "delivery_expectation_id",
            text("occurred_at DESC"),
            text("source_event_id DESC"),
        ),
    )

    source_event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    delivery_expectation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("delivery_expectations.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    source_event: Mapped[DeliveryEvent] = relationship(back_populates="activity_entry")
    delivery_expectation: Mapped[DeliveryExpectation] = relationship(viewonly=True)
