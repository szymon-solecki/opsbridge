from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Enum as SqlEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.models.base import Base
from backend.app.models.enums import IntakeClaimStatus, IntakeFinalLocation


class IntakeClaim(Base):
    __tablename__ = "intake_claims"
    __table_args__ = (
        ForeignKeyConstraint(
            ["delivery_expectation_id", "integration_id"],
            ["delivery_expectations.id", "delivery_expectations.integration_id"],
            name="fk_intake_claims_expectation_same_integration",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["file_id", "delivery_expectation_id"],
            ["files.id", "files.delivery_expectation_id"],
            name="fk_intake_claims_file_same_expectation",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "file_id IS NULL OR delivery_expectation_id IS NOT NULL",
            name="file_requires_expectation",
        ),
        CheckConstraint(
            "content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'",
            name="content_hash_sha256_format",
        ),
        CheckConstraint(
            "source_delivery_id IS NULL OR "
            "(length(source_delivery_id) <= 255 AND source_delivery_id ~ '[^[:space:]]')",
            name="source_delivery_id_nonblank",
        ),
        CheckConstraint(
            "(status = 'FINALIZED' AND final_location IS NOT NULL AND finalized_at IS NOT NULL) OR "
            "(status <> 'FINALIZED' AND final_location IS NULL AND finalized_at IS NULL)",
            name="finalization_fields_match_status",
        ),
        Index(
            "ix_intake_claims_status_created_at",
            "status",
            text("created_at DESC"),
        ),
        Index(
            "ix_intake_claims_integration_created_at",
            "integration_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    integration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("integrations.id", name="fk_intake_claims_integration_id_integrations", ondelete="RESTRICT"),
        nullable=False,
    )
    delivery_expectation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[IntakeClaimStatus] = mapped_column(
        SqlEnum(
            IntakeClaimStatus,
            name="intake_claim_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=IntakeClaimStatus.CLAIMED,
        server_default=text("'CLAIMED'"),
    )
    final_location: Mapped[IntakeFinalLocation | None] = mapped_column(
        SqlEnum(
            IntakeFinalLocation,
            name="intake_final_location",
            values_callable=lambda enum: [item.value for item in enum],
        )
    )
    content_hash: Mapped[str | None] = mapped_column(String(64))
    source_delivery_id: Mapped[str | None] = mapped_column(String(255))
    finalized_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
