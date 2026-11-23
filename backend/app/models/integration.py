from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum as SqlEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    and_,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PGUUID
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship, validates
from sqlalchemy.sql import func

from backend.app.models.base import Base
from backend.app.models.enums import DeliveryStatus

if TYPE_CHECKING:
    from backend.app.models.event import DeliveryEvent
    from backend.app.models.file import File
    from backend.app.models.incident import Incident


class Integration(Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("name", name="uq_integrations_name"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    delivery_expectations: Mapped[list[DeliveryExpectation]] = relationship(
        back_populates="integration", passive_deletes=True
    )


class DeliveryExpectation(Base):
    __tablename__ = "delivery_expectations"
    __table_args__ = (
        UniqueConstraint("id", "integration_id", name="uq_delivery_expectations_id_integration"),
        UniqueConstraint(
            "integration_id", "business_date", "delivery_type", name="uq_delivery_expectation_delivery_type"
        ),
        CheckConstraint(
            "delivery_type ~ '^[A-Z0-9_]{1,64}$'", name="delivery_type_format"
        ),
        CheckConstraint(
            "overdue_at IS NULL OR overdue_at > deadline_at", name="overdue_after_deadline"
        ),
        ForeignKeyConstraint(
            ["current_file_id", "id"],
            ["files.id", "files.delivery_expectation_id"],
            name="fk_delivery_expectations_current_file_same_delivery",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        Index(
            "ix_delivery_expectations_sla_pending",
            "deadline_at",
            postgresql_where=text("status = 'EXPECTED' AND overdue_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    integration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("integrations.id", ondelete="RESTRICT"), nullable=False
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    delivery_type: Mapped[str] = mapped_column(String(64, collation="C"), nullable=False)
    expected_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    overdue_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[DeliveryStatus] = mapped_column(
        SqlEnum(DeliveryStatus, name="delivery_status", values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
        default=DeliveryStatus.EXPECTED,
        server_default=text("'EXPECTED'"),
    )
    current_file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    integration: Mapped[Integration] = relationship(back_populates="delivery_expectations")
    files: Mapped[list[File]] = relationship(
        back_populates="delivery_expectation",
        foreign_keys="File.delivery_expectation_id",
        passive_deletes=True,
    )
    current_file: Mapped[File | None] = relationship(
        "File",
        primaryjoin=(
            "and_(DeliveryExpectation.current_file_id == File.id, "
            "DeliveryExpectation.id == File.delivery_expectation_id)"
        ),
        foreign_keys="DeliveryExpectation.current_file_id",
        post_update=True,
    )
    events: Mapped[list[DeliveryEvent]] = relationship(
        back_populates="delivery_expectation", passive_deletes=True
    )
    incidents: Mapped[list[Incident]] = relationship(
        back_populates="delivery_expectation", passive_deletes=True
    )

    @validates("delivery_type")
    def validate_delivery_type(self, key: str, value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[A-Z0-9_]{1,64}", value, flags=re.ASCII) is None:
            raise ValueError("delivery_type must contain 1 to 64 uppercase ASCII letters, digits, or underscores")
        return value
