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
    text,
)
from sqlalchemy.dialects.postgresql import BIGINT, CHAR, TIMESTAMP, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from backend.app.models.base import Base
from backend.app.models.enums import FileStatus

if TYPE_CHECKING:
    from backend.app.models.event import DeliveryEvent
    from backend.app.models.incident import Incident
    from backend.app.models.integration import DeliveryExpectation


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("delivery_expectation_id", "content_hash", name="uq_files_delivery_content_hash"),
        UniqueConstraint("id", "delivery_expectation_id", name="uq_files_id_delivery_expectation"),
        UniqueConstraint("replaces_file_id", name="uq_files_replaces_file_id"),
        ForeignKeyConstraint(
            ["replaces_file_id", "delivery_expectation_id"],
            ["files.id", "files.delivery_expectation_id"],
            name="fk_files_replacement_same_delivery",
            ondelete="RESTRICT",
        ),
        CheckConstraint("replaces_file_id IS NULL OR replaces_file_id <> id", name="not_self_replacement"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="sha256_hex_format"),
        CheckConstraint("size_bytes >= 0", name="nonnegative_size"),
        CheckConstraint("attempt_series > 0", name="positive_attempt_series"),
        CheckConstraint("attempt_count_in_series BETWEEN 0 AND 3", name="attempt_count_limit"),
        Index(
            "ix_files_delivery_received",
            "delivery_expectation_id",
            text("received_at DESC"),
        ),
        Index(
            "uq_files_source_delivery_id",
            "delivery_expectation_id",
            "source_delivery_id",
            unique=True,
            postgresql_where=text("source_delivery_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    delivery_expectation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("delivery_expectations.id", ondelete="RESTRICT"), nullable=False
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    source_delivery_id: Mapped[str | None] = mapped_column(String(255, collation="C"))
    size_bytes: Mapped[int] = mapped_column(BIGINT, nullable=False)
    received_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    status: Mapped[FileStatus] = mapped_column(
        SqlEnum(FileStatus, name="file_status", values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
        default=FileStatus.RECEIVED,
        server_default=text("'RECEIVED'"),
    )
    replaces_file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    attempt_series: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    attempt_count_in_series: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    validation_error_code: Mapped[str | None] = mapped_column(String(100))
    validation_error_message: Mapped[str | None] = mapped_column(Text)
    processing_error_code: Mapped[str | None] = mapped_column(String(100))
    processing_error_message: Mapped[str | None] = mapped_column(Text)
    validated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    delivery_expectation: Mapped[DeliveryExpectation] = relationship(
        back_populates="files", foreign_keys=[delivery_expectation_id]
    )
    replaces_file: Mapped[File | None] = relationship(
        "File",
        primaryjoin=(
            "and_(File.replaces_file_id == remote(File.id), "
            "File.delivery_expectation_id == remote(File.delivery_expectation_id))"
        ),
        remote_side=lambda: [File.id, File.delivery_expectation_id],
        foreign_keys=lambda: [File.replaces_file_id],
        uselist=False,
        viewonly=True,
    )
    events: Mapped[list[DeliveryEvent]] = relationship(
        back_populates="file", foreign_keys="DeliveryEvent.file_id", passive_deletes=True
    )
    incidents: Mapped[list[Incident]] = relationship(
        back_populates="file", foreign_keys="Incident.file_id", passive_deletes=True
    )
