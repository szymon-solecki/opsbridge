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
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from backend.app.models.base import Base
from backend.app.models.enums import IncidentStatus, IncidentType

if TYPE_CHECKING:
    from backend.app.models.file import File
    from backend.app.models.integration import DeliveryExpectation


_ACTIVE_STATUSES = "('OPEN', 'ACKNOWLEDGED')"


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["file_id", "delivery_expectation_id"],
            ["files.id", "files.delivery_expectation_id"],
            name="fk_incidents_file_same_delivery",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(incident_type IN ('MISSING_FILE', 'SOURCE_DELIVERY_ID_CONFLICT', 'RECONCILIATION_FAILURE') AND file_id IS NULL) OR "
            "(incident_type IN ('VALIDATION_FAILURE', 'PROCESSING_FAILURE') AND file_id IS NOT NULL)",
            name="file_reference_matches_incident_type",
        ),
        ForeignKeyConstraint(["reconciliation_run_id", "delivery_expectation_id"],
                             ["reconciliation_runs.id", "reconciliation_runs.source_a_delivery_id"],
                             name="fk_incidents_reconciliation_run_anchor", ondelete="RESTRICT"),
        CheckConstraint("(incident_type = 'RECONCILIATION_FAILURE') = (reconciliation_run_id IS NOT NULL)",
                        name="reconciliation_run_matches_incident_type"),
        Index("uq_incidents_reconciliation_run", "reconciliation_run_id", unique=True,
              postgresql_where=text("reconciliation_run_id IS NOT NULL")),
        CheckConstraint(
            "(incident_type = 'SOURCE_DELIVERY_ID_CONFLICT' AND conflict_key IS NOT NULL) OR "
            "(incident_type <> 'SOURCE_DELIVERY_ID_CONFLICT' AND conflict_key IS NULL)",
            name="conflict_key_matches_incident_type",
        ),
        CheckConstraint(
            "(status = 'OPEN' AND acknowledged_at IS NULL AND resolved_at IS NULL) OR "
            "(status = 'ACKNOWLEDGED' AND acknowledged_at IS NOT NULL AND resolved_at IS NULL) OR "
            "(status = 'RESOLVED' AND resolved_at IS NOT NULL AND "
            "(acknowledged_at IS NULL OR resolved_at >= acknowledged_at))",
            name="lifecycle_timestamps_match_status",
        ),
        Index(
            "uq_incidents_active_missing_file",
            "delivery_expectation_id",
            unique=True,
            postgresql_where=text(f"incident_type = 'MISSING_FILE' AND status IN {_ACTIVE_STATUSES}"),
        ),
        Index(
            "uq_incidents_active_validation_file",
            "file_id",
            unique=True,
            postgresql_where=text(f"incident_type = 'VALIDATION_FAILURE' AND status IN {_ACTIVE_STATUSES}"),
        ),
        Index(
            "uq_incidents_active_processing_file",
            "file_id",
            unique=True,
            postgresql_where=text(f"incident_type = 'PROCESSING_FAILURE' AND status IN {_ACTIVE_STATUSES}"),
        ),
        Index(
            "uq_incidents_conflict_key",
            "conflict_key",
            unique=True,
            postgresql_where=text("conflict_key IS NOT NULL"),
        ),
        Index("ix_incidents_status_opened", "status", text("opened_at DESC")),
        Index(
            "ix_incidents_delivery_opened",
            "delivery_expectation_id",
            text("opened_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    delivery_expectation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("delivery_expectations.id", ondelete="RESTRICT"), nullable=False
    )
    file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    conflict_key: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reconciliation_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    incident_type: Mapped[IncidentType] = mapped_column(
        SqlEnum(IncidentType, name="incident_type", values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    status: Mapped[IncidentStatus] = mapped_column(
        SqlEnum(IncidentStatus, name="incident_status", values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
        default=IncidentStatus.OPEN,
        server_default=text("'OPEN'"),
    )
    opened_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    delivery_expectation: Mapped[DeliveryExpectation] = relationship(back_populates="incidents")
    file: Mapped[File | None] = relationship(
        "File",
        primaryjoin=(
            "and_(Incident.file_id == File.id, "
            "Incident.delivery_expectation_id == File.delivery_expectation_id)"
        ),
        foreign_keys="Incident.file_id",
        back_populates="incidents",
    )
