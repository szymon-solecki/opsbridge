"""Add individual accounts, sessions, security audit and notification policy storage."""

from alembic import op

revision = "ca78b650af13"
down_revision = "b678d1243fa0"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE operator_accounts (
        id UUID NOT NULL,
        username VARCHAR(64) NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(10) NOT NULL,
        active BOOLEAN NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        CONSTRAINT pk_operator_accounts PRIMARY KEY (id),
        CONSTRAINT ck_operator_accounts_valid_role CHECK (role IN ('VIEWER','OPERATOR','ADMIN')),
        CONSTRAINT ck_operator_accounts_valid_username CHECK (username ~ '^[a-z0-9][a-z0-9_.-]{2,63}$'),
        CONSTRAINT uq_operator_accounts_username UNIQUE (username)
        )
    """)
    op.execute("""
        CREATE TABLE operator_sessions (
        digest VARCHAR(64) NOT NULL,
        operator_id UUID NOT NULL,
        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        CONSTRAINT pk_operator_sessions PRIMARY KEY (digest),
        CONSTRAINT fk_operator_sessions_operator_id_operator_accounts FOREIGN KEY(operator_id) REFERENCES operator_accounts (id) ON DELETE RESTRICT
        )
    """)
    op.execute("""CREATE INDEX ix_operator_sessions_account ON operator_sessions (operator_id)""")
    op.execute("""
        CREATE TABLE security_audit_events (
        id UUID NOT NULL,
        operator_id UUID,
        action VARCHAR(40) NOT NULL,
        target_id UUID,
        occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        CONSTRAINT pk_security_audit_events PRIMARY KEY (id),
        CONSTRAINT fk_security_audit_events_operator_id_operator_accounts FOREIGN KEY(operator_id) REFERENCES operator_accounts (id) ON DELETE RESTRICT
        )
    """)
    op.execute("""CREATE INDEX ix_security_audit_operator_action_time ON security_audit_events (operator_id, action, occurred_at)""")
    op.execute("""
        CREATE TABLE notification_policy_documents (
        id INTEGER NOT NULL,
        rules JSONB NOT NULL,
        CONSTRAINT pk_notification_policy_documents PRIMARY KEY (id),
        CONSTRAINT ck_notification_policy_documents_singleton CHECK (id = 1)
        )
    """)

    op.execute("ALTER TABLE reconciliation_definitions DROP CONSTRAINT uq_reconciliation_source_pair")
    op.execute("ALTER TABLE reconciliation_definitions ADD CONSTRAINT uq_reconciliation_named_source_pair "
               "UNIQUE (name, source_a_delivery_id, source_b_delivery_id)")
    op.execute("""
        CREATE FUNCTION opsbridge_security_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'security audit records are immutable';
        END;
        $$
    """)
    op.execute("CREATE TRIGGER trg_security_audit_immutable BEFORE UPDATE OR DELETE ON security_audit_events "
               "FOR EACH ROW EXECUTE FUNCTION opsbridge_security_audit_immutable()")
    op.execute("CREATE TRIGGER trg_security_audit_no_truncate BEFORE TRUNCATE ON security_audit_events "
               "FOR EACH STATEMENT EXECUTE FUNCTION opsbridge_security_audit_immutable()")


def downgrade():
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM security_audit_events)
                OR EXISTS (SELECT 1 FROM operator_accounts)
                OR EXISTS (SELECT 1 FROM notification_policy_documents)
                OR EXISTS (SELECT 1 FROM reconciliation_definitions
                           GROUP BY source_a_delivery_id, source_b_delivery_id HAVING count(*) > 1) THEN
                RAISE EXCEPTION 'security records or reconciliation policy history prevent downgrade';
            END IF;
        END;
        $$
    """)
    op.execute("ALTER TABLE reconciliation_definitions DROP CONSTRAINT uq_reconciliation_named_source_pair")
    op.execute("ALTER TABLE reconciliation_definitions ADD CONSTRAINT uq_reconciliation_source_pair "
               "UNIQUE (source_a_delivery_id, source_b_delivery_id)")
    op.drop_table("notification_policy_documents")
    op.drop_table("security_audit_events")
    op.drop_table("operator_sessions")
    op.drop_table("operator_accounts")
    op.execute("DROP FUNCTION opsbridge_security_audit_immutable()")
