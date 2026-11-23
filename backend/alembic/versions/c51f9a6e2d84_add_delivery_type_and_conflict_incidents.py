"""Add explicit delivery types and idempotent source ID conflict incidents.

Revision ID: c51f9a6e2d84
Revises: a84f2c91d6b0
Create Date: 2026-11-16

Downgrade is intentionally guarded: delivery_type and conflict incident history
cannot be discarded safely. PostgreSQL enum labels are retained on downgrade.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c51f9a6e2d84"
down_revision: Union[str, None] = "a84f2c91d6b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DELIVERY_TYPE_BACKFILL = {
    ("Treasury Feed", "treasury-*.csv"): "TREASURY_TRANSACTIONS",
}


def _sql_literal(value: str) -> str:
    """Render a trusted migration constant as a PostgreSQL string literal."""
    return str(
        sa.literal(value).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def _delivery_type_mapping_values() -> str:
    """Render the single explicit backfill map as a PostgreSQL VALUES list."""
    rows = []
    for (integration_name, expected_pattern), delivery_type in DELIVERY_TYPE_BACKFILL.items():
        rows.append(
            "(" + ", ".join(
                _sql_literal(value)
                for value in (integration_name, expected_pattern, delivery_type)
            ) + ")"
        )
    return ",\n                   ".join(rows)


def _validate_delivery_type_mapping_sql() -> str:
    mapping_values = _delivery_type_mapping_values()
    return f"""
DO $opsbridge_backfill_validation$
DECLARE
    unmapped_expectation record;
BEGIN
    SELECT expectation.id,
           integration.name AS integration_name,
           expectation.expected_pattern
    INTO unmapped_expectation
    FROM delivery_expectations AS expectation
    JOIN integrations AS integration ON integration.id = expectation.integration_id
    LEFT JOIN (VALUES
        {mapping_values}
    ) AS mapping(integration_name, expected_pattern, delivery_type)
      ON mapping.integration_name = integration.name
     AND mapping.expected_pattern = expectation.expected_pattern
    WHERE mapping.delivery_type IS NULL
    ORDER BY expectation.id
    LIMIT 1;

    IF FOUND THEN
        RAISE EXCEPTION
            'No explicit delivery_type mapping for expectation % (integration=%, expected_pattern=%)',
            unmapped_expectation.id,
            unmapped_expectation.integration_name,
            unmapped_expectation.expected_pattern;
    END IF;
END
$opsbridge_backfill_validation$;
"""


def _backfill_delivery_types_sql() -> str:
    mapping_values = _delivery_type_mapping_values()
    return f"""
UPDATE delivery_expectations AS expectation
SET delivery_type = mapping.delivery_type
FROM integrations AS integration,
     (VALUES
    {mapping_values}
) AS mapping(integration_name, expected_pattern, delivery_type)
WHERE integration.id = expectation.integration_id
  AND mapping.integration_name = integration.name
  AND mapping.expected_pattern = expectation.expected_pattern;
"""


def _validate_backfilled_identities_sql() -> str:
    return """
DO $opsbridge_identity_validation$
DECLARE
    duplicate_identity record;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM delivery_expectations
        WHERE delivery_type IS NULL
    ) THEN
        RAISE EXCEPTION
            'Every existing delivery expectation must have an explicit delivery_type mapping';
    END IF;

    SELECT integration_id, business_date, delivery_type
    INTO duplicate_identity
    FROM delivery_expectations
    GROUP BY integration_id, business_date, delivery_type
    HAVING count(*) > 1
    ORDER BY integration_id, business_date, delivery_type
    LIMIT 1;

    IF FOUND THEN
        RAISE EXCEPTION
            'The delivery_type backfill produces duplicate identity (integration_id=%, business_date=%, delivery_type=%)',
            duplicate_identity.integration_id,
            duplicate_identity.business_date,
            duplicate_identity.delivery_type;
    END IF;
END
$opsbridge_identity_validation$;
"""


def _assert_downgrade_preserves_data_sql() -> str:
    return """
DO $opsbridge_downgrade_guard$
BEGIN
    IF EXISTS (SELECT 1 FROM delivery_expectations) THEN
        RAISE EXCEPTION
            'Cannot downgrade while delivery expectations exist; removing delivery_type would discard data';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM incidents
        WHERE incident_type::text = 'SOURCE_DELIVERY_ID_CONFLICT'
    ) THEN
        RAISE EXCEPTION
            'Cannot downgrade while source delivery ID conflict incident history exists';
    END IF;
END
$opsbridge_downgrade_guard$;
"""


def upgrade() -> None:
    # PostgreSQL does not allow a newly added enum value to be used until its
    # transaction commits. Keep this additive operation in its own block.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE incident_type "
            "ADD VALUE IF NOT EXISTS 'SOURCE_DELIVERY_ID_CONFLICT'"
        )

    op.add_column(
        "delivery_expectations",
        sa.Column("delivery_type", sa.String(length=64, collation="C"), nullable=True),
    )

    op.execute(_validate_delivery_type_mapping_sql())
    op.execute(_backfill_delivery_types_sql())
    op.execute(_validate_backfilled_identities_sql())

    op.alter_column("delivery_expectations", "delivery_type", nullable=False)
    op.create_check_constraint(
        op.f("ck_delivery_expectations_delivery_type_format"),
        "delivery_expectations",
        "delivery_type ~ '^[A-Z0-9_]{1,64}$'",
    )
    op.drop_constraint(
        op.f("uq_delivery_expectation_identity"),
        "delivery_expectations",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_delivery_expectation_delivery_type"),
        "delivery_expectations",
        ["integration_id", "business_date", "delivery_type"],
    )

    op.add_column("incidents", sa.Column("conflict_key", postgresql.UUID(as_uuid=True), nullable=True))
    op.drop_constraint(
        op.f("ck_incidents_file_reference_matches_incident_type"),
        "incidents",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_incidents_file_reference_matches_incident_type"),
        "incidents",
        "(incident_type IN ('MISSING_FILE', 'SOURCE_DELIVERY_ID_CONFLICT') AND file_id IS NULL) OR "
        "(incident_type IN ('VALIDATION_FAILURE', 'PROCESSING_FAILURE') AND file_id IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_incidents_conflict_key_matches_incident_type"),
        "incidents",
        "(incident_type = 'SOURCE_DELIVERY_ID_CONFLICT' AND conflict_key IS NOT NULL) OR "
        "(incident_type <> 'SOURCE_DELIVERY_ID_CONFLICT' AND conflict_key IS NULL)",
    )
    op.create_index(
        op.f("uq_incidents_conflict_key"),
        "incidents",
        ["conflict_key"],
        unique=True,
        postgresql_where=sa.text("conflict_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute(_assert_downgrade_preserves_data_sql())

    op.drop_index(op.f("uq_incidents_conflict_key"), table_name="incidents")
    op.drop_constraint(
        op.f("ck_incidents_conflict_key_matches_incident_type"),
        "incidents",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_incidents_file_reference_matches_incident_type"),
        "incidents",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_incidents_file_reference_matches_incident_type"),
        "incidents",
        "(incident_type = 'MISSING_FILE' AND file_id IS NULL) OR "
        "(incident_type IN ('VALIDATION_FAILURE', 'PROCESSING_FAILURE') AND file_id IS NOT NULL)",
    )
    op.drop_column("incidents", "conflict_key")

    op.drop_constraint(
        op.f("uq_delivery_expectation_delivery_type"),
        "delivery_expectations",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_delivery_expectations_delivery_type_format"),
        "delivery_expectations",
        type_="check",
    )
    op.drop_column("delivery_expectations", "delivery_type")
    op.create_unique_constraint(
        op.f("uq_delivery_expectation_identity"),
        "delivery_expectations",
        ["integration_id", "business_date", "expected_pattern"],
    )

    # PostgreSQL has no direct DROP VALUE operation for an enum. The enum label
    # remains unused; all dependent data/constraints are guarded above.
