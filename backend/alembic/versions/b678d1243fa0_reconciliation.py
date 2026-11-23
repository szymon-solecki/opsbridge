"""Add immutable reconciliation definitions and execution history."""

from alembic import op

revision = "b678d1243fa0"
down_revision = "f43c720a19be"
branch_labels = None
depends_on = None

INCIDENT_FILE = "ck_incidents_file_reference_matches_incident_type"
OLD_FILE_CHECK = (
    "(incident_type IN ('MISSING_FILE', 'SOURCE_DELIVERY_ID_CONFLICT') AND file_id IS NULL) OR "
    "(incident_type IN ('VALIDATION_FAILURE', 'PROCESSING_FAILURE') AND file_id IS NOT NULL)"
)


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE incident_type ADD VALUE IF NOT EXISTS 'RECONCILIATION_FAILURE'")
    op.execute("""
        CREATE TABLE reconciliation_definitions (
        id UUID NOT NULL,
        name VARCHAR(120) NOT NULL,
        source_a_delivery_id UUID NOT NULL,
        source_b_delivery_id UUID NOT NULL,
        match_on VARCHAR(12) NOT NULL,
        tolerance NUMERIC(24, 6) NOT NULL,
        materiality NUMERIC(24, 6),
        exception_limit INTEGER,
        incident_on_missing BOOLEAN NOT NULL,
        incident_on_failure BOOLEAN NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        CONSTRAINT pk_reconciliation_definitions PRIMARY KEY (id),
        CONSTRAINT uq_reconciliation_source_pair UNIQUE (source_a_delivery_id, source_b_delivery_id),
        CONSTRAINT uq_reconciliation_definition_sources UNIQUE (id, source_a_delivery_id, source_b_delivery_id),
        CONSTRAINT ck_reconciliation_definitions_distinct_sources CHECK (source_a_delivery_id <> source_b_delivery_id),
        CONSTRAINT ck_reconciliation_definitions_supported_key CHECK (match_on IN ('record_id','reference')),
        CONSTRAINT ck_reconciliation_definitions_positive_thresholds CHECK (tolerance >= 0 AND (materiality IS NULL OR materiality > 0)),
        CONSTRAINT ck_reconciliation_definitions_positive_exception_limit CHECK (exception_limit IS NULL OR exception_limit > 0),
        CONSTRAINT fk_reconciliation_definitions_source_a_delivery_id_deli_683a FOREIGN KEY(source_a_delivery_id) REFERENCES delivery_expectations (id) ON DELETE RESTRICT,
        CONSTRAINT fk_reconciliation_definitions_source_b_delivery_id_deli_d32b FOREIGN KEY(source_b_delivery_id) REFERENCES delivery_expectations (id) ON DELETE RESTRICT
        )
    """)
    op.execute("""
        CREATE TABLE reconciliation_runs (
        id UUID NOT NULL,
        definition_id UUID NOT NULL,
        source_a_delivery_id UUID NOT NULL,
        source_b_delivery_id UUID NOT NULL,
        file_a_id UUID,
        file_b_id UUID,
        parent_id UUID,
        status VARCHAR(12) NOT NULL,
        attempts INTEGER NOT NULL,
        next_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL,
        finished_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        error_code VARCHAR(40),
        missing_reported BOOLEAN NOT NULL,
        snapshot JSONB,
        report JSONB,
        CONSTRAINT pk_reconciliation_runs PRIMARY KEY (id),
        CONSTRAINT uq_reconciliation_run_anchor UNIQUE (id, source_a_delivery_id),
        CONSTRAINT fk_reconciliation_run_definition_sources FOREIGN KEY(definition_id, source_a_delivery_id, source_b_delivery_id) REFERENCES reconciliation_definitions (id, source_a_delivery_id, source_b_delivery_id) ON DELETE RESTRICT,
        CONSTRAINT fk_reconciliation_run_file_a FOREIGN KEY(file_a_id, source_a_delivery_id) REFERENCES files (id, delivery_expectation_id) ON DELETE RESTRICT,
        CONSTRAINT fk_reconciliation_run_file_b FOREIGN KEY(file_b_id, source_b_delivery_id) REFERENCES files (id, delivery_expectation_id) ON DELETE RESTRICT,
        CONSTRAINT ck_reconciliation_runs_status CHECK (status IN ('WAITING','RUNNING','RETRY','COMPLETED','FAILED')),
        CONSTRAINT ck_reconciliation_runs_attempt_limit CHECK (attempts BETWEEN 0 AND 3),
        CONSTRAINT ck_reconciliation_runs_pins CHECK ((file_a_id IS NULL) = (file_b_id IS NULL) AND (status = 'WAITING') = (file_a_id IS NULL)),
        CONSTRAINT ck_reconciliation_runs_finished CHECK ((status IN ('COMPLETED','FAILED')) = (finished_at IS NOT NULL)),
        CONSTRAINT ck_reconciliation_runs_completed_evidence CHECK ((status = 'COMPLETED') = (report IS NOT NULL) AND (status = 'COMPLETED') = (snapshot IS NOT NULL)),
        CONSTRAINT fk_reconciliation_runs_parent_id_reconciliation_runs FOREIGN KEY(parent_id) REFERENCES reconciliation_runs (id) ON DELETE RESTRICT
        )
    """)
    op.execute("""CREATE INDEX ix_reconciliation_due ON reconciliation_runs (next_attempt_at, id) WHERE status IN ('WAITING','RUNNING','RETRY')""")
    op.execute("""CREATE INDEX ix_reconciliation_history ON reconciliation_runs (definition_id, created_at DESC, id DESC)""")
    op.execute("""CREATE UNIQUE INDEX uq_reconciliation_active_run ON reconciliation_runs (definition_id) WHERE status IN ('WAITING','RUNNING','RETRY')""")

    op.execute("ALTER TABLE incidents ADD COLUMN reconciliation_run_id UUID")
    op.execute("""
        ALTER TABLE incidents ADD CONSTRAINT fk_incidents_reconciliation_run_anchor
        FOREIGN KEY (reconciliation_run_id, delivery_expectation_id)
        REFERENCES reconciliation_runs (id, source_a_delivery_id) ON DELETE RESTRICT
    """)
    op.execute("""
        ALTER TABLE incidents ADD CONSTRAINT ck_incidents_reconciliation_run_matches_incident_type
        CHECK ((incident_type = 'RECONCILIATION_FAILURE') = (reconciliation_run_id IS NOT NULL))
    """)
    op.execute("CREATE UNIQUE INDEX uq_incidents_reconciliation_run ON incidents (reconciliation_run_id) "
               "WHERE reconciliation_run_id IS NOT NULL")
    op.drop_constraint(op.f(INCIDENT_FILE), "incidents", type_="check")
    new_file_check = OLD_FILE_CHECK.replace("'SOURCE_DELIVERY_ID_CONFLICT'",
                                            "'SOURCE_DELIVERY_ID_CONFLICT', 'RECONCILIATION_FAILURE'")
    op.create_check_constraint(op.f(INCIDENT_FILE), "incidents", new_file_check)
    op.execute("""
        CREATE FUNCTION opsbridge_guard_reconciliation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP IN ('TRUNCATE', 'DELETE') OR TG_TABLE_NAME = 'reconciliation_definitions' THEN
                RAISE EXCEPTION 'reconciliation history is immutable';
            END IF;
            IF OLD.status IN ('COMPLETED', 'FAILED') OR
               ROW(OLD.id, OLD.definition_id, OLD.parent_id, OLD.source_a_delivery_id,
                   OLD.source_b_delivery_id, OLD.created_at) IS DISTINCT FROM
               ROW(NEW.id, NEW.definition_id, NEW.parent_id, NEW.source_a_delivery_id,
                   NEW.source_b_delivery_id, NEW.created_at) OR
               (OLD.file_a_id IS NOT NULL AND ROW(OLD.file_a_id, OLD.file_b_id) IS DISTINCT FROM
                                               ROW(NEW.file_a_id, NEW.file_b_id)) THEN
                RAISE EXCEPTION 'reconciliation history is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    for table in ("reconciliation_definitions", "reconciliation_runs"):
        op.execute(f"CREATE TRIGGER trg_reconciliation_immutable BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION opsbridge_guard_reconciliation()")
        op.execute(f"CREATE TRIGGER trg_reconciliation_no_truncate BEFORE TRUNCATE ON {table} "
                   "FOR EACH STATEMENT EXECUTE FUNCTION opsbridge_guard_reconciliation()")
    op.execute("""
        CREATE TRIGGER trg_dashboard_reconciliation AFTER INSERT OR UPDATE OF status, attempts, missing_reported
        ON reconciliation_runs FOR EACH ROW EXECUTE FUNCTION opsbridge_signal_dashboard()
    """)


def downgrade():
    # Keep the additive enum label. Refuse to discard recorded run history.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM reconciliation_definitions) THEN
                RAISE EXCEPTION 'reconciliation definitions and history prevent downgrade';
            END IF;
        END;
        $$
    """)
    op.drop_constraint(op.f(INCIDENT_FILE), "incidents", type_="check")
    op.create_check_constraint(op.f(INCIDENT_FILE), "incidents", OLD_FILE_CHECK)
    op.drop_index("uq_incidents_reconciliation_run", table_name="incidents")
    op.drop_constraint(op.f("ck_incidents_reconciliation_run_matches_incident_type"), "incidents", type_="check")
    op.drop_constraint("fk_incidents_reconciliation_run_anchor", "incidents", type_="foreignkey")
    op.drop_column("incidents", "reconciliation_run_id")
    op.drop_table("reconciliation_runs")
    op.drop_table("reconciliation_definitions")
    op.execute("DROP FUNCTION opsbridge_guard_reconciliation()")
