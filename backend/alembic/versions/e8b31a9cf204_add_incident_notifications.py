"""Add incident acknowledgement and notification audit tables."""

from alembic import op
import sqlalchemy as sa

revision = "e8b31a9cf204"
down_revision = "d2b17c4e806a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("incident_id", sa.Uuid(), sa.ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event", sa.String(10), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("owner", sa.String(100), nullable=False),
        sa.Column("recipient", sa.String(254), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(40)),
        sa.UniqueConstraint("incident_id", "event", "level", "recipient", name="uq_notification_job_identity"),
        sa.CheckConstraint("status IN ('PENDING','SENDING','SENT','FAILED','CANCELLED')", name="valid_status"),
        sa.CheckConstraint("(event IN ('OPENED','RESOLVED') AND level = 0) OR (event = 'ESCALATED' AND level > 0)",
                           name="valid_event_level"),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND 3", name="attempt_limit"),
    )
    op.create_index("ix_notification_jobs_due", "notification_jobs", ["status", "next_attempt_at", "id"])
    op.create_table(
        "notification_attempts",
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("notification_jobs.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(40)),
        sa.CheckConstraint("status IN ('STARTED','SENT','FAILED','UNKNOWN')", name="valid_status"),
        sa.CheckConstraint("number BETWEEN 1 AND 3", name="attempt_limit"),
    )
    op.create_table(
        "incident_acknowledgements",
        sa.Column("incident_id", sa.Uuid(), sa.ForeignKey("incidents.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("operator", sa.String(100), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comment", sa.Text()),
    )


def downgrade():
    op.drop_table("incident_acknowledgements")
    op.drop_table("notification_attempts")
    op.drop_table("notification_jobs")
