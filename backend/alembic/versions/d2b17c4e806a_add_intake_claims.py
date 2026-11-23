"""Add the durable SFTP intake claim ledger.

Revision ID: d2b17c4e806a
Revises: c51f9a6e2d84
Create Date: 2026-11-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d2b17c4e806a"
down_revision: Union[str, None] = "c51f9a6e2d84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


intake_claim_status = postgresql.ENUM(
    "CLAIMED",
    "SNAPSHOTTED",
    "VALIDATED",
    "COMMITTED",
    "FINALIZED",
    name="intake_claim_status",
)
intake_final_location = postgresql.ENUM(
    "ACCEPTED",
    "QUARANTINE",
    name="intake_final_location",
)


def upgrade() -> None:
    bind = op.get_bind()
    intake_claim_status.create(bind, checkfirst=False)
    intake_final_location.create(bind, checkfirst=False)

    op.create_unique_constraint(
        "uq_delivery_expectations_id_integration",
        "delivery_expectations",
        ["id", "integration_id"],
    )

    op.create_table(
        "intake_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_expectation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "CLAIMED", "SNAPSHOTTED", "VALIDATED", "COMMITTED", "FINALIZED",
                name="intake_claim_status", create_type=False,
            ),
            server_default=sa.text("'CLAIMED'"),
            nullable=False,
        ),
        sa.Column(
            "final_location",
            postgresql.ENUM(
                "ACCEPTED", "QUARANTINE", name="intake_final_location", create_type=False
            ),
            nullable=True,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("source_delivery_id", sa.String(length=255), nullable=True),
        sa.Column("finalized_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "file_id IS NULL OR delivery_expectation_id IS NOT NULL",
            name=op.f("ck_intake_claims_file_requires_expectation"),
        ),
        sa.CheckConstraint(
            "content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_intake_claims_content_hash_sha256_format"),
        ),
        sa.CheckConstraint(
            "source_delivery_id IS NULL OR "
            "(length(source_delivery_id) <= 255 AND source_delivery_id ~ '[^[:space:]]')",
            name=op.f("ck_intake_claims_source_delivery_id_nonblank"),
        ),
        sa.CheckConstraint(
            "(status = 'FINALIZED' AND final_location IS NOT NULL AND finalized_at IS NOT NULL) OR "
            "(status <> 'FINALIZED' AND final_location IS NULL AND finalized_at IS NULL)",
            name=op.f("ck_intake_claims_finalization_fields_match_status"),
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
            name="fk_intake_claims_integration_id_integrations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_expectation_id", "integration_id"],
            ["delivery_expectations.id", "delivery_expectations.integration_id"],
            name="fk_intake_claims_expectation_same_integration",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["file_id", "delivery_expectation_id"],
            ["files.id", "files.delivery_expectation_id"],
            name="fk_intake_claims_file_same_expectation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intake_claims")),
    )
    op.create_index(
        "ix_intake_claims_status_created_at",
        "intake_claims",
        ["status", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_intake_claims_integration_created_at",
        "intake_claims",
        ["integration_id", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_intake_claims_integration_created_at", table_name="intake_claims")
    op.drop_index("ix_intake_claims_status_created_at", table_name="intake_claims")
    op.drop_table("intake_claims")
    op.drop_constraint(
        "uq_delivery_expectations_id_integration",
        "delivery_expectations",
        type_="unique",
    )
    intake_final_location.drop(op.get_bind(), checkfirst=False)
    intake_claim_status.drop(op.get_bind(), checkfirst=False)
