"""Create the initial OpsBridge V1 operational schema.

Revision ID: a84f2c91d6b0
Revises:
Create Date: 2026-11-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a84f2c91d6b0"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    delivery_status = postgresql.ENUM(
        "EXPECTED",
        "RECEIVED",
        "VALIDATION_FAILED",
        "PROCESSING",
        "PROCESSING_FAILED",
        "COMPLETED",
        name="delivery_status",
    )
    file_status = postgresql.ENUM(
        "RECEIVED",
        "VALIDATION_FAILED",
        "PROCESSING",
        "PROCESSING_FAILED",
        "COMPLETED",
        name="file_status",
    )
    actor_type = postgresql.ENUM("SYSTEM", "OPERATOR", "SIMULATOR", name="actor_type")
    incident_type = postgresql.ENUM(
        "MISSING_FILE", "VALIDATION_FAILURE", "PROCESSING_FAILURE", name="incident_type"
    )
    incident_status = postgresql.ENUM("OPEN", "ACKNOWLEDGED", "RESOLVED", name="incident_status")

    bind = op.get_bind()
    delivery_status.create(bind, checkfirst=False)
    file_status.create(bind, checkfirst=False)
    actor_type.create(bind, checkfirst=False)
    incident_type.create(bind, checkfirst=False)
    incident_status.create(bind, checkfirst=False)

    op.create_table(
        "integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integrations")),
        sa.UniqueConstraint("name", name=op.f("uq_integrations_name")),
    )

    op.create_table(
        "delivery_expectations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("expected_pattern", sa.String(length=255), nullable=False),
        sa.Column("deadline_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("overdue_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "EXPECTED", "RECEIVED", "VALIDATION_FAILED", "PROCESSING", "PROCESSING_FAILED", "COMPLETED",
                name="delivery_status", create_type=False,
            ),
            server_default=sa.text("'EXPECTED'"),
            nullable=False,
        ),
        sa.Column("current_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "overdue_at IS NULL OR overdue_at > deadline_at",
            name=op.f("ck_delivery_expectations_overdue_after_deadline"),
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["integrations.id"],
            name=op.f("fk_delivery_expectations_integration_id_integrations"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_expectations")),
        sa.UniqueConstraint(
            "integration_id", "business_date", "expected_pattern", name=op.f("uq_delivery_expectation_identity")
        ),
    )

    op.create_table(
        "files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_expectation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("content_hash", postgresql.CHAR(length=64), nullable=False),
        sa.Column("source_delivery_id", sa.String(length=255, collation="C"), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("received_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "RECEIVED", "VALIDATION_FAILED", "PROCESSING", "PROCESSING_FAILED", "COMPLETED",
                name="file_status", create_type=False,
            ),
            server_default=sa.text("'RECEIVED'"),
            nullable=False,
        ),
        sa.Column("replaces_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempt_series", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("attempt_count_in_series", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("validation_error_code", sa.String(length=100), nullable=True),
        sa.Column("validation_error_message", sa.Text(), nullable=True),
        sa.Column("processing_error_code", sa.String(length=100), nullable=True),
        sa.Column("processing_error_message", sa.Text(), nullable=True),
        sa.Column("validated_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("processed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "replaces_file_id IS NULL OR replaces_file_id <> id",
            name=op.f("ck_files_not_self_replacement"),
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_files_sha256_hex_format")
        ),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_files_nonnegative_size")),
        sa.CheckConstraint("attempt_series > 0", name=op.f("ck_files_positive_attempt_series")),
        sa.CheckConstraint(
            "attempt_count_in_series BETWEEN 0 AND 3", name=op.f("ck_files_attempt_count_limit")
        ),
        sa.ForeignKeyConstraint(
            ["delivery_expectation_id"], ["delivery_expectations.id"],
            name=op.f("fk_files_delivery_expectation_id_delivery_expectations"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replaces_file_id", "delivery_expectation_id"],
            ["files.id", "files.delivery_expectation_id"],
            name=op.f("fk_files_replacement_same_delivery"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
        sa.UniqueConstraint(
            "delivery_expectation_id", "content_hash", name=op.f("uq_files_delivery_content_hash")
        ),
        sa.UniqueConstraint("id", "delivery_expectation_id", name=op.f("uq_files_id_delivery_expectation")),
        sa.UniqueConstraint("replaces_file_id", name=op.f("uq_files_replaces_file_id")),
    )

    op.create_table(
        "delivery_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_expectation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "actor_type",
            postgresql.ENUM("SYSTEM", "OPERATOR", "SIMULATOR", name="actor_type", create_type=False),
            server_default=sa.text("'SYSTEM'"),
            nullable=False,
        ),
        sa.Column("actor_reference", sa.String(length=255), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "event_type <> 'ManualReprocessingRequested' OR "
            "(actor_type = 'OPERATOR' AND actor_reference IS NOT NULL "
            "AND length(trim(actor_reference)) > 0)",
            name=op.f("ck_delivery_events_manual_reprocessing_actor"),
        ),
        sa.ForeignKeyConstraint(
            ["delivery_expectation_id"], ["delivery_expectations.id"],
            name=op.f("fk_delivery_events_delivery_expectation_id_delivery_expectations"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["file_id", "delivery_expectation_id"],
            ["files.id", "files.delivery_expectation_id"],
            name=op.f("fk_delivery_events_file_same_delivery"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_events")),
        sa.UniqueConstraint(
            "id", "delivery_expectation_id", name=op.f("uq_delivery_events_id_delivery_expectation")
        ),
    )

    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_expectation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "incident_type",
            postgresql.ENUM(
                "MISSING_FILE", "VALIDATION_FAILURE", "PROCESSING_FAILURE",
                name="incident_type", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM("OPEN", "ACKNOWLEDGED", "RESOLVED", name="incident_status", create_type=False),
            server_default=sa.text("'OPEN'"),
            nullable=False,
        ),
        sa.Column("opened_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("acknowledged_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolved_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(incident_type = 'MISSING_FILE' AND file_id IS NULL) OR "
            "(incident_type IN ('VALIDATION_FAILURE', 'PROCESSING_FAILURE') AND file_id IS NOT NULL)",
            name=op.f("ck_incidents_file_reference_matches_incident_type"),
        ),
        sa.CheckConstraint(
            "(status = 'OPEN' AND acknowledged_at IS NULL AND resolved_at IS NULL) OR "
            "(status = 'ACKNOWLEDGED' AND acknowledged_at IS NOT NULL AND resolved_at IS NULL) OR "
            "(status = 'RESOLVED' AND resolved_at IS NOT NULL AND "
            "(acknowledged_at IS NULL OR resolved_at >= acknowledged_at))",
            name=op.f("ck_incidents_lifecycle_timestamps_match_status"),
        ),
        sa.ForeignKeyConstraint(
            ["delivery_expectation_id"], ["delivery_expectations.id"],
            name=op.f("fk_incidents_delivery_expectation_id_delivery_expectations"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["file_id", "delivery_expectation_id"],
            ["files.id", "files.delivery_expectation_id"],
            name=op.f("fk_incidents_file_same_delivery"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("publication_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_attempt_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_attempt_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("failed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "publication_attempts >= 0", name=op.f("ck_outbox_events_nonnegative_publication_attempts")
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR failed_at IS NULL",
            name=op.f("ck_outbox_events_single_terminal_publication_state"),
        ),
        sa.CheckConstraint(
            "(published_at IS NULL AND failed_at IS NULL) OR next_attempt_at IS NULL",
            name=op.f("ck_outbox_events_terminal_event_has_no_retry_schedule"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["delivery_events.id"],
            name=op.f("fk_outbox_events_event_id_delivery_events"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
        sa.UniqueConstraint("event_id", name=op.f("uq_outbox_events_event_id")),
    )

    op.create_table(
        "inbox_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("received_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"], ["outbox_events.event_id"],
            name=op.f("fk_inbox_events_event_id_outbox_events"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_inbox_events")),
    )

    op.create_table(
        "activity_feed",
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_expectation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("occurred_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["delivery_expectation_id"], ["delivery_expectations.id"],
            name=op.f("fk_activity_feed_delivery_expectation_id_delivery_expectations"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id", "delivery_expectation_id"],
            ["delivery_events.id", "delivery_events.delivery_expectation_id"],
            name=op.f("fk_activity_feed_source_event_same_delivery"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("source_event_id", name=op.f("pk_activity_feed")),
    )

    op.create_foreign_key(
        op.f("fk_delivery_expectations_current_file_same_delivery"),
        "delivery_expectations",
        "files",
        ["current_file_id", "id"],
        ["id", "delivery_expectation_id"],
        ondelete="RESTRICT",
    )

    op.create_index(
        op.f("ix_delivery_expectations_sla_pending"),
        "delivery_expectations",
        ["deadline_at"],
        postgresql_where=sa.text("status = 'EXPECTED' AND overdue_at IS NULL"),
    )
    op.create_index(
        op.f("ix_files_delivery_received"), "files", ["delivery_expectation_id", sa.text("received_at DESC")]
    )
    op.create_index(
        op.f("uq_files_source_delivery_id"),
        "files",
        ["delivery_expectation_id", "source_delivery_id"],
        unique=True,
        postgresql_where=sa.text("source_delivery_id IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_delivery_events_delivery_time"),
        "delivery_events",
        ["delivery_expectation_id", sa.text("occurred_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        op.f("ix_delivery_events_file_time"), "delivery_events", ["file_id", sa.text("occurred_at DESC")]
    )
    op.create_index(
        op.f("ix_delivery_events_type_time"), "delivery_events", ["event_type", sa.text("occurred_at DESC")]
    )
    op.create_index(
        op.f("uq_incidents_active_missing_file"),
        "incidents",
        ["delivery_expectation_id"],
        unique=True,
        postgresql_where=sa.text("incident_type = 'MISSING_FILE' AND status IN ('OPEN', 'ACKNOWLEDGED')"),
    )
    op.create_index(
        op.f("uq_incidents_active_validation_file"),
        "incidents",
        ["file_id"],
        unique=True,
        postgresql_where=sa.text("incident_type = 'VALIDATION_FAILURE' AND status IN ('OPEN', 'ACKNOWLEDGED')"),
    )
    op.create_index(
        op.f("uq_incidents_active_processing_file"),
        "incidents",
        ["file_id"],
        unique=True,
        postgresql_where=sa.text("incident_type = 'PROCESSING_FAILURE' AND status IN ('OPEN', 'ACKNOWLEDGED')"),
    )
    op.create_index(
        op.f("ix_incidents_status_opened"), "incidents", ["status", sa.text("opened_at DESC")]
    )
    op.create_index(
        op.f("ix_incidents_delivery_opened"),
        "incidents",
        ["delivery_expectation_id", sa.text("opened_at DESC")],
    )
    op.create_index(
        op.f("ix_outbox_events_pending"),
        "outbox_events",
        ["next_attempt_at", "created_at", "id"],
        postgresql_where=sa.text("published_at IS NULL AND failed_at IS NULL"),
    )
    op.create_index(
        op.f("ix_activity_feed_chronological"),
        "activity_feed",
        [sa.text("occurred_at DESC"), sa.text("source_event_id DESC")],
    )
    op.create_index(
        op.f("ix_activity_feed_delivery_chronological"),
        "activity_feed",
        ["delivery_expectation_id", sa.text("occurred_at DESC"), sa.text("source_event_id DESC")],
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION prevent_delivery_event_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            BEGIN
                RAISE EXCEPTION
                    'delivery_events are immutable: UPDATE and DELETE are not allowed'
                    USING ERRCODE = '55000';
                RETURN OLD;
            END;
            $function$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_delivery_events_append_only
            BEFORE UPDATE OR DELETE ON delivery_events
            FOR EACH ROW
            EXECUTE FUNCTION prevent_delivery_event_mutation()
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION protect_file_replacement_link()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            DECLARE
                cycle_found boolean;
            BEGIN
                IF TG_OP = 'UPDATE'
                   AND OLD.replaces_file_id IS NOT NULL
                   AND NEW.replaces_file_id IS DISTINCT FROM OLD.replaces_file_id THEN
                    RAISE EXCEPTION
                        'files.replaces_file_id is immutable once set'
                        USING ERRCODE = '55000';
                END IF;

                IF TG_OP = 'UPDATE'
                   AND NEW.replaces_file_id IS NOT DISTINCT FROM OLD.replaces_file_id THEN
                    RETURN NEW;
                END IF;

                IF NEW.replaces_file_id IS NULL THEN
                    RETURN NEW;
                END IF;

                IF NEW.replaces_file_id = NEW.id THEN
                    RAISE EXCEPTION
                        'a file cannot replace itself'
                        USING ERRCODE = '23514';
                END IF;

                -- Serialize replacement-link checks so concurrent writes cannot create a cycle.
                PERFORM pg_advisory_xact_lock(1869639013, 1);

                WITH RECURSIVE replacement_chain(file_id) AS (
                    SELECT NEW.replaces_file_id
                    UNION
                    SELECT predecessor.replaces_file_id
                    FROM files AS predecessor
                    JOIN replacement_chain AS chain
                      ON predecessor.id = chain.file_id
                    WHERE predecessor.replaces_file_id IS NOT NULL
                )
                SELECT EXISTS (
                    SELECT 1
                    FROM replacement_chain
                    WHERE file_id = NEW.id
                )
                INTO cycle_found;

                IF cycle_found THEN
                    RAISE EXCEPTION
                        'replacement link would create a cycle'
                        USING ERRCODE = '23514';
                END IF;

                RETURN NEW;
            END;
            $function$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_files_replacement_link_protection
            BEFORE INSERT OR UPDATE ON files
            FOR EACH ROW
            EXECUTE FUNCTION protect_file_replacement_link()
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DROP TRIGGER trg_files_replacement_link_protection ON files")
    )
    op.execute(sa.text("DROP FUNCTION protect_file_replacement_link()"))
    op.execute(
        sa.text("DROP TRIGGER trg_delivery_events_append_only ON delivery_events")
    )
    op.execute(sa.text("DROP FUNCTION prevent_delivery_event_mutation()"))

    op.drop_index(op.f("ix_activity_feed_delivery_chronological"), table_name="activity_feed")
    op.drop_index(op.f("ix_activity_feed_chronological"), table_name="activity_feed")
    op.drop_index(op.f("ix_outbox_events_pending"), table_name="outbox_events")
    op.drop_index(op.f("ix_incidents_delivery_opened"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_status_opened"), table_name="incidents")
    op.drop_index(op.f("uq_incidents_active_processing_file"), table_name="incidents")
    op.drop_index(op.f("uq_incidents_active_validation_file"), table_name="incidents")
    op.drop_index(op.f("uq_incidents_active_missing_file"), table_name="incidents")
    op.drop_index(op.f("ix_delivery_events_type_time"), table_name="delivery_events")
    op.drop_index(op.f("ix_delivery_events_file_time"), table_name="delivery_events")
    op.drop_index(op.f("ix_delivery_events_delivery_time"), table_name="delivery_events")
    op.drop_index(op.f("uq_files_source_delivery_id"), table_name="files")
    op.drop_index(op.f("ix_files_delivery_received"), table_name="files")
    op.drop_index(op.f("ix_delivery_expectations_sla_pending"), table_name="delivery_expectations")

    op.drop_constraint(
        op.f("fk_delivery_expectations_current_file_same_delivery"),
        "delivery_expectations",
        type_="foreignkey",
    )

    op.drop_table("activity_feed")
    op.drop_table("inbox_events")
    op.drop_table("outbox_events")
    op.drop_table("incidents")
    op.drop_table("delivery_events")
    op.drop_table("files")
    op.drop_table("delivery_expectations")
    op.drop_table("integrations")

    postgresql.ENUM("OPEN", "ACKNOWLEDGED", "RESOLVED", name="incident_status").drop(
        op.get_bind(), checkfirst=False
    )
    postgresql.ENUM(
        "MISSING_FILE", "VALIDATION_FAILURE", "PROCESSING_FAILURE", name="incident_type"
    ).drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM("SYSTEM", "OPERATOR", "SIMULATOR", name="actor_type").drop(
        op.get_bind(), checkfirst=False
    )
    postgresql.ENUM(
        "RECEIVED", "VALIDATION_FAILED", "PROCESSING", "PROCESSING_FAILED", "COMPLETED", name="file_status"
    ).drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(
        "EXPECTED", "RECEIVED", "VALIDATION_FAILED", "PROCESSING", "PROCESSING_FAILED", "COMPLETED",
        name="delivery_status",
    ).drop(op.get_bind(), checkfirst=False)
