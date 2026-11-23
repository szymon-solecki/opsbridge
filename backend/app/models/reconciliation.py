"""Versioned reconciliation definitions and durable execution results."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.models.base import Base


class ReconciliationDefinition(Base):
    __tablename__ = "reconciliation_definitions"
    __table_args__ = (
        UniqueConstraint("name", "source_a_delivery_id", "source_b_delivery_id", name="uq_reconciliation_named_source_pair"),
        UniqueConstraint("id", "source_a_delivery_id", "source_b_delivery_id", name="uq_reconciliation_definition_sources"),
        CheckConstraint("source_a_delivery_id <> source_b_delivery_id", name="distinct_sources"),
        CheckConstraint("match_on IN ('record_id','reference')", name="supported_key"),
        CheckConstraint("tolerance >= 0 AND (materiality IS NULL OR materiality > 0)", name="positive_thresholds"),
        CheckConstraint("exception_limit IS NULL OR exception_limit > 0", name="positive_exception_limit"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120))
    source_a_delivery_id: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("delivery_expectations.id", ondelete="RESTRICT"))
    source_b_delivery_id: Mapped[UUID] = mapped_column(PGUUID, ForeignKey("delivery_expectations.id", ondelete="RESTRICT"))
    match_on: Mapped[str] = mapped_column(String(12))
    tolerance: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    materiality: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    exception_limit: Mapped[int | None] = mapped_column(Integer)
    incident_on_missing: Mapped[bool] = mapped_column(Boolean)
    incident_on_failure: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        UniqueConstraint("id", "source_a_delivery_id", name="uq_reconciliation_run_anchor"),
        ForeignKeyConstraint(["definition_id", "source_a_delivery_id", "source_b_delivery_id"],
                             ["reconciliation_definitions.id", "reconciliation_definitions.source_a_delivery_id",
                              "reconciliation_definitions.source_b_delivery_id"],
                             name="fk_reconciliation_run_definition_sources", ondelete="RESTRICT"),
        ForeignKeyConstraint(["file_a_id", "source_a_delivery_id"], ["files.id", "files.delivery_expectation_id"],
                             name="fk_reconciliation_run_file_a", ondelete="RESTRICT"),
        ForeignKeyConstraint(["file_b_id", "source_b_delivery_id"], ["files.id", "files.delivery_expectation_id"],
                             name="fk_reconciliation_run_file_b", ondelete="RESTRICT"),
        CheckConstraint("status IN ('WAITING','RUNNING','RETRY','COMPLETED','FAILED')", name="status"),
        CheckConstraint("attempts BETWEEN 0 AND 3", name="attempt_limit"),
        CheckConstraint("(file_a_id IS NULL) = (file_b_id IS NULL) AND (status = 'WAITING') = (file_a_id IS NULL)", name="pins"),
        CheckConstraint("(status IN ('COMPLETED','FAILED')) = (finished_at IS NOT NULL)", name="finished"),
        CheckConstraint("(status = 'COMPLETED') = (report IS NOT NULL) AND "
                        "(status = 'COMPLETED') = (snapshot IS NOT NULL)", name="completed_evidence"),
        Index("uq_reconciliation_active_run", "definition_id", unique=True,
              postgresql_where=text("status IN ('WAITING','RUNNING','RETRY')")),
        Index("ix_reconciliation_due", "next_attempt_at", "id",
              postgresql_where=text("status IN ('WAITING','RUNNING','RETRY')")),
        Index("ix_reconciliation_history", "definition_id", text("created_at DESC"), text("id DESC")),
    )

    id: Mapped[UUID] = mapped_column(PGUUID, primary_key=True, default=uuid4)
    definition_id: Mapped[UUID] = mapped_column(PGUUID)
    source_a_delivery_id: Mapped[UUID] = mapped_column(PGUUID)
    source_b_delivery_id: Mapped[UUID] = mapped_column(PGUUID)
    file_a_id: Mapped[UUID | None] = mapped_column(PGUUID)
    file_b_id: Mapped[UUID | None] = mapped_column(PGUUID)
    parent_id: Mapped[UUID | None] = mapped_column(PGUUID, ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(12))
    attempts: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    error_code: Mapped[str | None] = mapped_column(String(40))
    missing_reported: Mapped[bool] = mapped_column(Boolean)
    snapshot: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    report: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
