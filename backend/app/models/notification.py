"""Durable incident notification requests and attempt history."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class NotificationJob(Base):
    __tablename__ = "notification_jobs"
    __table_args__ = (
        UniqueConstraint("incident_id", "event", "level", "recipient", name="uq_notification_job_identity"),
        CheckConstraint("status IN ('PENDING','SENDING','SENT','FAILED','CANCELLED')", name="valid_status"),
        CheckConstraint(
            "(event IN ('OPENED','RESOLVED') AND level = 0) OR (event = 'ESCALATED' AND level > 0)",
            name="valid_event_level",
        ),
        CheckConstraint("attempt_count BETWEEN 0 AND 3", name="attempt_limit"),
        Index("ix_notification_jobs_due", "status", "next_attempt_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id", ondelete="RESTRICT"))
    event: Mapped[str] = mapped_column(String(10))
    level: Mapped[int]
    severity: Mapped[str] = mapped_column(String(10))
    owner: Mapped[str] = mapped_column(String(100))
    recipient: Mapped[str] = mapped_column(String(254))
    status: Mapped[str] = mapped_column(String(10))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int]
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(40))


class NotificationAttempt(Base):
    __tablename__ = "notification_attempts"
    __table_args__ = (
        CheckConstraint("status IN ('STARTED','SENT','FAILED','UNKNOWN')", name="valid_status"),
        CheckConstraint("number BETWEEN 1 AND 3", name="attempt_limit"),
    )

    job_id: Mapped[UUID] = mapped_column(ForeignKey("notification_jobs.id", ondelete="RESTRICT"), primary_key=True)
    number: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(10))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(40))


class IncidentAcknowledgement(Base):
    __tablename__ = "incident_acknowledgements"

    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id", ondelete="RESTRICT"), primary_key=True)
    operator: Mapped[str] = mapped_column(String(100))
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
