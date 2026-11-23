"""Signal dashboard changes after PostgreSQL commits."""

from alembic import op

revision = "f43c720a19be"
down_revision = "e8b31a9cf204"
branch_labels = None
depends_on = None

TABLES = (
    "integrations", "delivery_expectations", "files", "delivery_events", "incidents",
    "activity_feed", "notification_jobs", "notification_attempts", "incident_acknowledgements",
)


def upgrade():
    op.execute("""
        CREATE FUNCTION opsbridge_signal_dashboard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_notify('opsbridge_dashboard', '');
            RETURN NULL;
        END;
        $$
    """)
    for table in TABLES:
        op.execute(f"""
            CREATE TRIGGER trg_dashboard_invalidation AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION opsbridge_signal_dashboard()
        """)


def downgrade():
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER trg_dashboard_invalidation ON {table}")
    op.execute("DROP FUNCTION opsbridge_signal_dashboard()")
