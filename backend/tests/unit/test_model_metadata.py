from pathlib import Path
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum as SqlEnum,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    inspect,
)
from sqlalchemy.dialects.postgresql import BIGINT, CHAR, JSONB, TIMESTAMP, UUID as PGUUID, dialect
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable, UniqueConstraint

from backend.app.models import (
    ActivityFeed,
    ActorType,
    Base,
    DeliveryEvent,
    DeliveryExpectation,
    DeliveryStatus,
    File,
    FileStatus,
    InboxEvent,
    Incident,
    IncidentStatus,
    IncidentType,
    Integration,
    IntakeClaim,
    IntakeClaimStatus,
    IntakeFinalLocation,
    OutboxEvent,
)


ADDITIONAL_TABLES = {"notification_jobs", "notification_attempts", "incident_acknowledgements",
                     "reconciliation_definitions", "reconciliation_runs",
                     "operator_accounts", "operator_sessions", "security_audit_events", "notification_policy_documents"}

EXPECTED_COLUMNS = {
    "integrations": {
        "id": (PGUUID, False, True),
        "name": (str, False, False),
        "source_name": (str, False, False),
        "active": (Boolean, False, False),
        "created_at": (TIMESTAMP, False, False),
        "updated_at": (TIMESTAMP, False, False),
    },
    "delivery_expectations": {
        "id": (PGUUID, False, True),
        "integration_id": (PGUUID, False, False),
        "business_date": (Date, False, False),
        "delivery_type": (str, False, False),
        "expected_pattern": (str, False, False),
        "deadline_at": (TIMESTAMP, False, False),
        "overdue_at": (TIMESTAMP, True, False),
        "status": (SqlEnum, False, False),
        "current_file_id": (PGUUID, True, False),
        "created_at": (TIMESTAMP, False, False),
        "updated_at": (TIMESTAMP, False, False),
    },
    "files": {
        "id": (PGUUID, False, True),
        "delivery_expectation_id": (PGUUID, False, False),
        "original_name": (str, False, False),
        "content_hash": (CHAR, False, False),
        "source_delivery_id": (str, True, False),
        "size_bytes": (BIGINT, False, False),
        "received_at": (TIMESTAMP, False, False),
        "status": (SqlEnum, False, False),
        "replaces_file_id": (PGUUID, True, False),
        "attempt_series": (Integer, False, False),
        "attempt_count_in_series": (Integer, False, False),
        "validation_error_code": (str, True, False),
        "validation_error_message": (str, True, False),
        "processing_error_code": (str, True, False),
        "processing_error_message": (str, True, False),
        "validated_at": (TIMESTAMP, True, False),
        "processed_at": (TIMESTAMP, True, False),
        "created_at": (TIMESTAMP, False, False),
    },
    "delivery_events": {
        "id": (PGUUID, False, True),
        "delivery_expectation_id": (PGUUID, False, False),
        "file_id": (PGUUID, True, False),
        "event_type": (str, False, False),
        "occurred_at": (TIMESTAMP, False, False),
        "actor_type": (SqlEnum, False, False),
        "actor_reference": (str, True, False),
        "details": (JSONB, True, False),
    },
    "incidents": {
        "id": (PGUUID, False, True),
        "delivery_expectation_id": (PGUUID, False, False),
        "file_id": (PGUUID, True, False),
        "conflict_key": (PGUUID, True, False),
        "reconciliation_run_id": (PGUUID, True, False),
        "incident_type": (SqlEnum, False, False),
        "status": (SqlEnum, False, False),
        "opened_at": (TIMESTAMP, False, False),
        "acknowledged_at": (TIMESTAMP, True, False),
        "resolved_at": (TIMESTAMP, True, False),
        "reason": (str, False, False),
        "resolution_reason": (str, True, False),
        "created_at": (TIMESTAMP, False, False),
        "updated_at": (TIMESTAMP, False, False),
    },
    "outbox_events": {
        "id": (PGUUID, False, True),
        "event_id": (PGUUID, False, False),
        "event_type": (str, False, False),
        "payload": (JSONB, False, False),
        "created_at": (TIMESTAMP, False, False),
        "published_at": (TIMESTAMP, True, False),
        "publication_attempts": (Integer, False, False),
        "last_attempt_at": (TIMESTAMP, True, False),
        "next_attempt_at": (TIMESTAMP, True, False),
        "failed_at": (TIMESTAMP, True, False),
        "last_error": (str, True, False),
    },
    "inbox_events": {
        "event_id": (PGUUID, False, True),
        "event_type": (str, False, False),
        "received_at": (TIMESTAMP, False, False),
        "processed_at": (TIMESTAMP, False, False),
        "outcome": (str, False, False),
        "details": (JSONB, True, False),
    },
    "activity_feed": {
        "source_event_id": (PGUUID, False, True),
        "delivery_expectation_id": (PGUUID, False, False),
        "event_type": (str, False, False),
        "summary": (str, False, False),
        "payload": (JSONB, True, False),
        "occurred_at": (TIMESTAMP, False, False),
        "created_at": (TIMESTAMP, False, False),
    },
    "intake_claims": {
        "id": (PGUUID, False, True),
        "integration_id": (PGUUID, False, False),
        "delivery_expectation_id": (PGUUID, True, False),
        "file_id": (PGUUID, True, False),
        "status": (SqlEnum, False, False),
        "final_location": (SqlEnum, True, False),
        "content_hash": (str, True, False),
        "source_delivery_id": (str, True, False),
        "finalized_at": (TIMESTAMP, True, False),
        "error_code": (str, True, False),
        "error_message": (str, True, False),
        "created_at": (TIMESTAMP, False, False),
        "updated_at": (TIMESTAMP, False, False),
    },
}

EXPECTED_STRING_LENGTHS = {
    ("integrations", "name"): 120,
    ("integrations", "source_name"): 120,
    ("delivery_expectations", "delivery_type"): 64,
    ("delivery_expectations", "expected_pattern"): 255,
    ("files", "original_name"): 255,
    ("files", "source_delivery_id"): 255,
    ("files", "validation_error_code"): 100,
    ("files", "validation_error_message"): None,
    ("files", "processing_error_code"): 100,
    ("files", "processing_error_message"): None,
    ("delivery_events", "event_type"): 100,
    ("delivery_events", "actor_reference"): 255,
    ("incidents", "reason"): None,
    ("incidents", "resolution_reason"): None,
    ("outbox_events", "event_type"): 100,
    ("outbox_events", "last_error"): None,
    ("inbox_events", "event_type"): 100,
    ("inbox_events", "outcome"): 30,
    ("activity_feed", "event_type"): 100,
    ("activity_feed", "summary"): 500,
    ("intake_claims", "content_hash"): 64,
    ("intake_claims", "source_delivery_id"): 255,
    ("intake_claims", "error_code"): 100,
    ("intake_claims", "error_message"): None,
}

EXPECTED_INDEX_NAMES = {
    "integrations": set(),
    "delivery_expectations": {"ix_delivery_expectations_sla_pending"},
    "files": {"ix_files_delivery_received", "uq_files_source_delivery_id"},
    "delivery_events": {
        "ix_delivery_events_delivery_time", "ix_delivery_events_file_time", "ix_delivery_events_type_time"
    },
    "incidents": {
        "uq_incidents_active_missing_file", "uq_incidents_active_validation_file",
        "uq_incidents_active_processing_file", "ix_incidents_status_opened", "ix_incidents_delivery_opened",
        "uq_incidents_conflict_key", "uq_incidents_reconciliation_run",
    },
    "outbox_events": {"ix_outbox_events_pending"},
    "inbox_events": set(),
    "activity_feed": {"ix_activity_feed_chronological", "ix_activity_feed_delivery_chronological"},
    "intake_claims": {"ix_intake_claims_status_created_at", "ix_intake_claims_integration_created_at"},
}

EXPECTED_SERVER_DEFAULT_KEYS = {
    ("integrations", "active"), ("integrations", "created_at"), ("integrations", "updated_at"),
    ("delivery_expectations", "status"), ("delivery_expectations", "created_at"),
    ("delivery_expectations", "updated_at"), ("files", "status"), ("files", "attempt_series"),
    ("files", "attempt_count_in_series"), ("files", "created_at"),
    ("delivery_events", "occurred_at"), ("delivery_events", "actor_type"),
    ("incidents", "status"), ("incidents", "opened_at"), ("incidents", "created_at"),
    ("incidents", "updated_at"), ("outbox_events", "created_at"),
    ("outbox_events", "publication_attempts"), ("inbox_events", "received_at"),
    ("activity_feed", "created_at"),
    ("intake_claims", "status"), ("intake_claims", "created_at"),
    ("intake_claims", "updated_at"),
}

EXPECTED_PYTHON_DEFAULT_KEYS = {
    ("notification_jobs", "id"),
    ("integrations", "id"), ("integrations", "active"),
    ("delivery_expectations", "id"), ("delivery_expectations", "status"),
    ("files", "id"), ("files", "status"), ("files", "attempt_series"),
    ("files", "attempt_count_in_series"), ("delivery_events", "id"),
    ("delivery_events", "actor_type"), ("incidents", "id"), ("incidents", "status"),
    ("outbox_events", "id"), ("outbox_events", "publication_attempts"),
    ("intake_claims", "id"), ("intake_claims", "status"),
}

EXPECTED_CHECK_SUFFIXES = {
    "integrations": set(),
    "delivery_expectations": {"overdue_after_deadline", "delivery_type_format"},
    "files": {
        "not_self_replacement", "sha256_hex_format", "nonnegative_size",
        "positive_attempt_series", "attempt_count_limit",
    },
    "delivery_events": {"manual_reprocessing_actor"},
    "incidents": {
        "file_reference_matches_incident_type", "lifecycle_timestamps_match_status",
        "conflict_key_matches_incident_type", "reconciliation_run_matches_incident_type",
    },
    "outbox_events": {
        "nonnegative_publication_attempts", "single_terminal_publication_state",
        "terminal_event_has_no_retry_schedule",
    },
    "inbox_events": set(),
    "activity_feed": set(),
    "intake_claims": {
        "file_requires_expectation", "content_hash_sha256_format",
        "source_delivery_id_nonblank", "finalization_fields_match_status",
    },
}


EXPECTED_FOREIGN_KEYS = {
    "integrations": set(),
    "delivery_expectations": {
        (("integration_id",), ("integrations", "id"), "RESTRICT"),
        (("current_file_id", "id"), ("files", "id", "delivery_expectation_id"), "RESTRICT"),
    },
    "files": {
        (("delivery_expectation_id",), ("delivery_expectations", "id"), "RESTRICT"),
        (("replaces_file_id", "delivery_expectation_id"), ("files", "id", "delivery_expectation_id"), "RESTRICT"),
    },
    "delivery_events": {
        (("delivery_expectation_id",), ("delivery_expectations", "id"), "RESTRICT"),
        (("file_id", "delivery_expectation_id"), ("files", "id", "delivery_expectation_id"), "RESTRICT"),
    },
    "incidents": {
        (("reconciliation_run_id", "delivery_expectation_id"),
         ("reconciliation_runs", "id", "source_a_delivery_id"), "RESTRICT"),
        (("delivery_expectation_id",), ("delivery_expectations", "id"), "RESTRICT"),
        (("file_id", "delivery_expectation_id"), ("files", "id", "delivery_expectation_id"), "RESTRICT"),
    },
    "outbox_events": {
        (("event_id",), ("delivery_events", "id"), "RESTRICT"),
    },
    "inbox_events": {
        (("event_id",), ("outbox_events", "event_id"), "RESTRICT"),
    },
    "activity_feed": {
        (("delivery_expectation_id",), ("delivery_expectations", "id"), "RESTRICT"),
        (("source_event_id", "delivery_expectation_id"),
         ("delivery_events", "id", "delivery_expectation_id"), "RESTRICT"),
    },
    "intake_claims": {
        (("integration_id",), ("integrations", "id"), "RESTRICT"),
        (("delivery_expectation_id", "integration_id"),
         ("delivery_expectations", "id", "integration_id"), "RESTRICT"),
        (("file_id", "delivery_expectation_id"),
         ("files", "id", "delivery_expectation_id"), "RESTRICT"),
    },
}


def _normalized(value: str) -> str:
    return " ".join(value.lower().split())


def _foreign_key_signature(constraint: ForeignKeyConstraint) -> tuple:
    elements = list(constraint.elements)
    return (
        tuple(constraint.column_keys),
        (elements[0].column.table.name, *(element.column.name for element in elements)),
        constraint.ondelete,
    )


def _all_constraints(table, constraint_type):
    return [item for item in table.constraints if isinstance(item, constraint_type)]


def _check_text(table, suffix: str) -> str:
    check = next(
        item
        for item in _all_constraints(table, CheckConstraint)
        if item.name.endswith(suffix)
    )
    return _normalized(str(check.sqltext))


def _index_sql(index: Index) -> str:
    return str(CreateIndex(index).compile(dialect=dialect()))


def test_tables_and_all_approved_columns_are_registered() -> None:
    assert set(Base.metadata.tables) == set(EXPECTED_COLUMNS) | ADDITIONAL_TABLES
    for table_name, expected_columns in EXPECTED_COLUMNS.items():
        table = Base.metadata.tables[table_name]
        assert set(table.columns.keys()) == set(expected_columns)


def test_postgresql_types_nullability_and_primary_keys_match_schema() -> None:
    for table_name, expected_columns in EXPECTED_COLUMNS.items():
        table = Base.metadata.tables[table_name]
        for column_name, (expected_type, nullable, primary_key) in expected_columns.items():
            column = table.columns[column_name]
            if expected_type is str:
                assert isinstance(column.type, String)
                assert column.type.length == EXPECTED_STRING_LENGTHS[(table_name, column_name)]
            else:
                assert isinstance(column.type, expected_type), (table_name, column_name, column.type)
            assert column.nullable is nullable, (table_name, column_name)
            assert column.primary_key is primary_key, (table_name, column_name)
            if expected_type is TIMESTAMP:
                assert column.type.timezone is True, (table_name, column_name)
            if expected_type is PGUUID:
                assert column.type.as_uuid is True, (table_name, column_name)

    for table_name in EXPECTED_COLUMNS:
        table = Base.metadata.tables[table_name]
        assert [column.name for column in table.primary_key.columns] == [
            name for name, (_, _, is_primary_key) in EXPECTED_COLUMNS[table_name].items() if is_primary_key
        ]

    assert Base.metadata.tables["files"].c.content_hash.type.length == 64
    assert Base.metadata.tables["files"].c.source_delivery_id.type.collation == "C"
    assert Base.metadata.tables["delivery_expectations"].c.delivery_type.type.collation == "C"
    assert Base.metadata.tables["delivery_expectations"].c.deadline_at.type.timezone is True
    assert Base.metadata.tables["activity_feed"].c.payload.type.__class__ is JSONB


def test_python_and_server_defaults_match_the_schema() -> None:
    uuid_default_tables = {
        "integrations", "delivery_expectations", "files", "delivery_events", "incidents",
        "outbox_events", "intake_claims",
    }
    for table_name in uuid_default_tables:
        id_default = Base.metadata.tables[table_name].c.id.default.arg
        assert callable(id_default) and id_default.__name__ == uuid4.__name__
        assert Base.metadata.tables[table_name].c.id.server_default is None

    server_defaults = {
        ("integrations", "active"): "true",
        ("integrations", "created_at"): "now()",
        ("integrations", "updated_at"): "now()",
        ("delivery_expectations", "status"): "'EXPECTED'",
        ("delivery_expectations", "created_at"): "now()",
        ("delivery_expectations", "updated_at"): "now()",
        ("files", "status"): "'RECEIVED'",
        ("files", "attempt_series"): "1",
        ("files", "attempt_count_in_series"): "0",
        ("files", "created_at"): "now()",
        ("delivery_events", "occurred_at"): "now()",
        ("delivery_events", "actor_type"): "'SYSTEM'",
        ("incidents", "status"): "'OPEN'",
        ("incidents", "opened_at"): "now()",
        ("incidents", "created_at"): "now()",
        ("incidents", "updated_at"): "now()",
        ("outbox_events", "created_at"): "now()",
        ("outbox_events", "publication_attempts"): "0",
        ("inbox_events", "received_at"): "now()",
        ("activity_feed", "created_at"): "now()",
        ("intake_claims", "status"): "'CLAIMED'",
        ("intake_claims", "created_at"): "now()",
        ("intake_claims", "updated_at"): "now()",
    }
    for (table_name, column_name), expected in server_defaults.items():
        actual = str(Base.metadata.tables[table_name].c[column_name].server_default.arg).lower()
        assert actual == expected.lower()

    python_defaults = {
        ("integrations", "active"): True,
        ("delivery_expectations", "status"): DeliveryStatus.EXPECTED,
        ("files", "status"): FileStatus.RECEIVED,
        ("files", "attempt_series"): 1,
        ("files", "attempt_count_in_series"): 0,
        ("delivery_events", "actor_type"): ActorType.SYSTEM,
        ("incidents", "status"): IncidentStatus.OPEN,
        ("outbox_events", "publication_attempts"): 0,
        ("intake_claims", "status"): IntakeClaimStatus.CLAIMED,
    }
    for (table_name, column_name), expected in python_defaults.items():
        assert Base.metadata.tables[table_name].c[column_name].default.arg == expected

    for table_name in ("integrations", "delivery_expectations", "incidents", "intake_claims"):
        assert Base.metadata.tables[table_name].c.updated_at.onupdate is not None

    actual_server_default_keys = {
        (table_name, column.name)
        for table_name, table in Base.metadata.tables.items()
        for column in table.columns
        if column.server_default is not None
    }
    assert actual_server_default_keys == EXPECTED_SERVER_DEFAULT_KEYS | {
        ("reconciliation_definitions", "created_at"), ("reconciliation_runs", "created_at"),
        ("operator_accounts", "created_at"), ("security_audit_events", "occurred_at"),
    }

    actual_python_default_keys = {
        (table_name, column.name)
        for table_name, table in Base.metadata.tables.items()
        for column in table.columns
        if column.default is not None
    }
    assert actual_python_default_keys == EXPECTED_PYTHON_DEFAULT_KEYS | {
        ("reconciliation_definitions", "id"), ("reconciliation_runs", "id"),
        ("operator_accounts", "id"), ("security_audit_events", "id"),
    }

    assert Base.metadata.tables["inbox_events"].c.event_id.default is None
    assert Base.metadata.tables["activity_feed"].c.source_event_id.default is None


def test_all_enum_values_match_the_approved_schema() -> None:
    assert [item.value for item in DeliveryStatus] == [
        "EXPECTED", "RECEIVED", "VALIDATION_FAILED", "PROCESSING", "PROCESSING_FAILED", "COMPLETED"
    ]
    assert [item.value for item in FileStatus] == [
        "RECEIVED", "VALIDATION_FAILED", "PROCESSING", "PROCESSING_FAILED", "COMPLETED"
    ]
    assert [item.value for item in IncidentType] == [
        "MISSING_FILE", "VALIDATION_FAILURE", "PROCESSING_FAILURE", "SOURCE_DELIVERY_ID_CONFLICT",
        "RECONCILIATION_FAILURE"
    ]
    assert [item.value for item in IncidentStatus] == ["OPEN", "ACKNOWLEDGED", "RESOLVED"]
    assert [item.value for item in ActorType] == ["SYSTEM", "OPERATOR", "SIMULATOR"]
    assert [item.value for item in IntakeClaimStatus] == [
        "CLAIMED", "SNAPSHOTTED", "VALIDATED", "COMMITTED", "FINALIZED"
    ]
    assert [item.value for item in IntakeFinalLocation] == ["ACCEPTED", "QUARANTINE"]

    enum_columns = {
        ("delivery_expectations", "status"): "delivery_status",
        ("files", "status"): "file_status",
        ("incidents", "incident_type"): "incident_type",
        ("incidents", "status"): "incident_status",
        ("delivery_events", "actor_type"): "actor_type",
        ("intake_claims", "status"): "intake_claim_status",
        ("intake_claims", "final_location"): "intake_final_location",
    }
    for (table_name, column_name), enum_name in enum_columns.items():
        column_type = Base.metadata.tables[table_name].c[column_name].type
        assert isinstance(column_type, SqlEnum)
        assert column_type.name == enum_name
        assert column_type.enums == [item.value for item in column_type.enum_class]


def test_all_foreign_keys_match_local_and_referenced_column_order_and_delete_action() -> None:
    for table_name, expected in EXPECTED_FOREIGN_KEYS.items():
        actual = {
            _foreign_key_signature(item)
            for item in _all_constraints(Base.metadata.tables[table_name], ForeignKeyConstraint)
        }
        assert actual == expected, table_name


def test_unique_constraints_and_partial_unique_indexes_match_schema() -> None:
    expected_constraints = {
        "integrations": {("name",)},
        "delivery_expectations": {
            ("id", "integration_id"),
            ("integration_id", "business_date", "delivery_type"),
        },
        "files": {
            ("delivery_expectation_id", "content_hash"),
            ("id", "delivery_expectation_id"),
            ("replaces_file_id",),
        },
        "delivery_events": {("id", "delivery_expectation_id")},
        "incidents": set(),
        "outbox_events": {("event_id",)},
        "inbox_events": set(),
        "activity_feed": set(),
        "intake_claims": set(),
    }
    for table_name, expected in expected_constraints.items():
        actual = {
            tuple(item.columns.keys())
            for item in _all_constraints(Base.metadata.tables[table_name], UniqueConstraint)
        }
        assert actual == expected, table_name

    partial_unique_indexes = {
        "uq_files_source_delivery_id": (
            "files", ("delivery_expectation_id", "source_delivery_id"), "source_delivery_id is not null"
        ),
        "uq_incidents_active_missing_file": (
            "incidents", ("delivery_expectation_id",),
            "incident_type = 'missing_file' and status in ('open', 'acknowledged')",
        ),
        "uq_incidents_active_validation_file": (
            "incidents", ("file_id",),
            "incident_type = 'validation_failure' and status in ('open', 'acknowledged')",
        ),
        "uq_incidents_active_processing_file": (
            "incidents", ("file_id",),
            "incident_type = 'processing_failure' and status in ('open', 'acknowledged')",
        ),
        "uq_incidents_conflict_key": (
            "incidents", ("conflict_key",), "conflict_key is not null"
        ),
    }
    for index_name, (table_name, columns, predicate) in partial_unique_indexes.items():
        index = next(item for item in Base.metadata.tables[table_name].indexes if item.name == index_name)
        assert index.unique is True
        assert tuple(column.name for column in index.columns) == columns
        assert _normalized(str(index.dialect_options["postgresql"]["where"])) == predicate


def test_all_index_names_and_nonunique_predicates_match_schema() -> None:
    for table_name, expected_names in EXPECTED_INDEX_NAMES.items():
        indexes = Base.metadata.tables[table_name].indexes
        assert {item.name for item in indexes} == expected_names, table_name

    sla_index = next(
        item for item in Base.metadata.tables["delivery_expectations"].indexes
        if item.name == "ix_delivery_expectations_sla_pending"
    )
    assert tuple(column.name for column in sla_index.columns) == ("deadline_at",)
    assert _normalized(str(sla_index.dialect_options["postgresql"]["where"])) == (
        "status = 'expected' and overdue_at is null"
    )


def test_check_constraints_cover_hash_attempts_incidents_sla_and_audit() -> None:
    for table_name, expected_suffixes in EXPECTED_CHECK_SUFFIXES.items():
        actual_suffixes = {
            item.name.split("ck_" + table_name + "_", 1)[-1]
            for item in _all_constraints(Base.metadata.tables[table_name], CheckConstraint)
        }
        assert actual_suffixes == expected_suffixes, table_name

    assert _normalized(_check_text(File.__table__, "sha256_hex_format")) == (
        "content_hash ~ '^[0-9a-f]{64}$'"
    )
    assert _normalized(_check_text(DeliveryExpectation.__table__, "delivery_type_format")) == (
        "delivery_type ~ '^[a-z0-9_]{1,64}$'"
    )
    assert "size_bytes >= 0" in _check_text(File.__table__, "nonnegative_size")
    assert "attempt_count_in_series between 0 and 3" in _check_text(File.__table__, "attempt_count_limit")
    assert "attempt_series > 0" in _check_text(File.__table__, "positive_attempt_series")
    assert "replaces_file_id <> id" in _check_text(File.__table__, "not_self_replacement")
    assert "overdue_at > deadline_at" in _check_text(
        DeliveryExpectation.__table__, "overdue_after_deadline"
    )
    assert _check_text(IntakeClaim.__table__, "file_requires_expectation") == (
        "file_id is null or delivery_expectation_id is not null"
    )
    assert _check_text(IntakeClaim.__table__, "content_hash_sha256_format") == (
        "content_hash is null or content_hash ~ '^[0-9a-f]{64}$'"
    )
    source_id_rule = _check_text(IntakeClaim.__table__, "source_delivery_id_nonblank")
    assert "source_delivery_id is null or" in source_id_rule
    assert "length(source_delivery_id) <= 255" in source_id_rule
    assert "source_delivery_id ~ '[^[:space:]]'" in source_id_rule
    finalization_rule = _check_text(IntakeClaim.__table__, "finalization_fields_match_status")
    assert all(term in finalization_rule for term in (
        "status = 'finalized'", "final_location is not null", "finalized_at is not null",
        "status <> 'finalized'", "final_location is null", "finalized_at is null",
    ))
    incident_lifecycle = _check_text(Incident.__table__, "lifecycle_timestamps_match_status")
    assert all(term in incident_lifecycle for term in (
        "status = 'open'", "acknowledged_at is null", "resolved_at is null",
        "status = 'acknowledged'", "acknowledged_at is not null",
        "status = 'resolved'", "resolved_at >= acknowledged_at",
    ))
    incident_file_rule = _check_text(Incident.__table__, "file_reference_matches_incident_type")
    assert incident_file_rule == (
        "(incident_type in ('missing_file', 'source_delivery_id_conflict', 'reconciliation_failure') and file_id is null) or "
        "(incident_type in ('validation_failure', 'processing_failure') and file_id is not null)"
    )
    conflict_key_rule = _check_text(Incident.__table__, "conflict_key_matches_incident_type")
    assert conflict_key_rule == (
        "(incident_type = 'source_delivery_id_conflict' and conflict_key is not null) or "
        "(incident_type <> 'source_delivery_id_conflict' and conflict_key is null)"
    )
    manual_audit = _check_text(DeliveryEvent.__table__, "manual_reprocessing_actor")
    assert all(term in manual_audit for term in (
        "manualreprocessingrequested", "actor_type = 'operator'", "actor_reference is not null",
        "length(trim(actor_reference)) > 0",
    ))


def test_outbox_terminal_checks_retry_columns_and_pending_predicate() -> None:
    outbox = OutboxEvent.__table__
    assert {"publication_attempts", "last_attempt_at", "next_attempt_at", "failed_at"} <= set(outbox.columns.keys())
    assert "publication_attempts >= 0" in _check_text(outbox, "nonnegative_publication_attempts")
    assert "published_at is null or failed_at is null" in _check_text(
        outbox, "single_terminal_publication_state"
    )
    assert "next_attempt_at is null" in _check_text(outbox, "terminal_event_has_no_retry_schedule")
    pending_index = next(item for item in outbox.indexes if item.name == "ix_outbox_events_pending")
    assert _normalized(str(pending_index.dialect_options["postgresql"]["where"])) == (
        "published_at is null and failed_at is null"
    )
    assert "next_attempt_at" in _index_sql(pending_index)
    assert "published_at is null and failed_at is null" in _index_sql(pending_index).lower()


def test_inbox_idempotency_and_activity_feed_relationship_and_indexes() -> None:
    inbox = InboxEvent.__table__
    assert [column.name for column in inbox.primary_key.columns] == ["event_id"]
    assert _foreign_key_signature(next(
        item for item in _all_constraints(inbox, ForeignKeyConstraint)
    )) == (("event_id",), ("outbox_events", "event_id"), "RESTRICT")

    activity = ActivityFeed.__table__
    assert [column.name for column in activity.primary_key.columns] == ["source_event_id"]
    assert _foreign_key_signature(next(
        item for item in _all_constraints(activity, ForeignKeyConstraint)
        if tuple(item.column_keys) == ("source_event_id", "delivery_expectation_id")
    )) == (
        ("source_event_id", "delivery_expectation_id"),
        ("delivery_events", "id", "delivery_expectation_id"),
        "RESTRICT",
    )
    indexes = {item.name: item for item in activity.indexes}
    assert set(indexes) == {"ix_activity_feed_chronological", "ix_activity_feed_delivery_chronological"}
    for index in indexes.values():
        assert "desc" in _index_sql(index).lower()

    configure_mappers()
    activity_relationship = inspect(ActivityFeed).relationships["source_event"]
    assert activity_relationship.mapper.class_ is DeliveryEvent
    relationship_pairs = {(local.name, remote.name) for local, remote in activity_relationship.local_remote_pairs}
    assert {("source_event_id", "id"), ("delivery_expectation_id", "delivery_expectation_id")} <= relationship_pairs


def test_chronological_indexes_have_explicit_descending_order() -> None:
    expected = {
        "files": {"ix_files_delivery_received"},
        "delivery_events": {
            "ix_delivery_events_delivery_time", "ix_delivery_events_file_time", "ix_delivery_events_type_time"
        },
        "incidents": {"ix_incidents_status_opened", "ix_incidents_delivery_opened"},
        "activity_feed": {"ix_activity_feed_chronological", "ix_activity_feed_delivery_chronological"},
        "intake_claims": {
            "ix_intake_claims_status_created_at", "ix_intake_claims_integration_created_at"
        },
    }
    for table_name, index_names in expected.items():
        indexes = {item.name: item for item in Base.metadata.tables[table_name].indexes}
        assert index_names <= set(indexes)
        for index_name in index_names:
            assert "desc" in _index_sql(indexes[index_name]).lower(), (table_name, index_name)


def test_orm_relationships_cover_approved_entity_links() -> None:
    configure_mappers()
    relationships = {
        Integration: {"delivery_expectations"},
        DeliveryExpectation: {"integration", "files", "current_file", "events", "incidents"},
        File: {"delivery_expectation", "replaces_file", "events", "incidents"},
        DeliveryEvent: {"delivery_expectation", "file", "outbox_event", "activity_entry"},
        Incident: {"delivery_expectation", "file"},
        OutboxEvent: {"delivery_event", "inbox_event"},
        InboxEvent: {"outbox_event"},
        ActivityFeed: {"source_event", "delivery_expectation"},
    }
    for model, expected_names in relationships.items():
        assert expected_names <= set(inspect(model).relationships.keys())
    current_file = inspect(DeliveryExpectation).relationships["current_file"]
    assert current_file.post_update is True
    assert [column.name for column in current_file._user_defined_foreign_keys] == ["current_file_id"]


def test_alembic_imports_all_registered_model_metadata() -> None:
    models_package = __import__("backend.app.models", fromlist=["__all__"])
    assert set(models_package.__all__) >= {
        "Integration", "DeliveryExpectation", "File", "DeliveryEvent", "Incident",
        "OutboxEvent", "InboxEvent", "ActivityFeed",
        "IntakeClaim", "IntakeClaimStatus", "IntakeFinalLocation",
    }
    assert set(Base.metadata.tables) == set(EXPECTED_COLUMNS) | ADDITIONAL_TABLES

    alembic_env = Path(__file__).resolve().parents[2] / "alembic" / "env.py"
    source = alembic_env.read_text(encoding="utf-8")
    assert "from backend.app.models import Base" in source
    assert "target_metadata = Base.metadata" in source


def test_all_tables_indexes_and_circular_fk_compile_for_postgresql() -> None:
    pg_dialect = dialect()
    for table in Base.metadata.sorted_tables:
        str(CreateTable(table).compile(dialect=pg_dialect))
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=pg_dialect))

    current_file_fk = next(
        item
        for item in DeliveryExpectation.__table__.constraints
        if isinstance(item, ForeignKeyConstraint)
        and item.name == "fk_delivery_expectations_current_file_same_delivery"
    )
    assert current_file_fk.use_alter is True
    assert list(current_file_fk.column_keys) == ["current_file_id", "id"]
    assert "ALTER TABLE delivery_expectations" in str(
        AddConstraint(current_file_fk).compile(dialect=pg_dialect)
    )
