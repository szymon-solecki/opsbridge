"""PostgreSQL-backed service tests; HTTP routing is covered by unit tests."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, create_engine, event as sqlalchemy_event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError, DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from backend.app.config import DATABASE_URL_FROM_PROCESS, normalize_database_url
from backend.app.models.enums import DeliveryStatus
from backend.app.schemas.delivery_expectation import DeliveryExpectationCreate
from backend.app.schemas.integration import IntegrationCreate
from backend.app.services.delivery_expectations import (
    create_delivery_expectation,
    list_delivery_expectations,
)
from backend.app.services.errors import (
    DuplicateDeliveryExpectationError,
    DuplicateIntegrationNameError,
    IntegrationNotFoundError,
)
from backend.app.services.integrations import create_integration, list_integrations


@pytest.fixture(scope="module")
def api_test_engine() -> Iterator[Engine]:
    if os.environ.get("OPSBRIDGE_RUN_INTEGRATION") != "1":
        pytest.skip("Set OPSBRIDGE_RUN_INTEGRATION=1 to run database integration tests")

    if not DATABASE_URL_FROM_PROCESS:
        pytest.fail("Set DATABASE_URL explicitly in the process environment for integration tests")

    try:
        parsed_url = make_url(normalize_database_url(DATABASE_URL_FROM_PROCESS))
    except (ArgumentError, ValueError):
        pytest.fail("Integration test DATABASE_URL must use a valid PostgreSQL URL")

    if parsed_url.database != "opsbridge_test":
        pytest.fail("Integration tests require DATABASE_URL to target opsbridge_test")

    engine = create_engine(parsed_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def isolated_connection(api_test_engine: Engine) -> Iterator[Connection]:
    connection = api_test_engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def session_factory(isolated_connection: Connection) -> Callable[[], Session]:
    def create_test_session() -> Session:
        return Session(
            bind=isolated_connection,
            join_transaction_mode="create_savepoint",
        )

    return create_test_session


def _create_integration(session_factory: Callable[[], Session], name: str | None = None):
    with session_factory() as session:
        return create_integration(
            session,
            IntegrationCreate(
                name=name or f"service-test-{uuid4()}",
                source_name="synthetic-service-test",
            ),
        )


def _expectation_data(expected_pattern: str, delivery_type: str) -> DeliveryExpectationCreate:
    return DeliveryExpectationCreate(
        business_date=date(2025, 1, 2),
        delivery_type=delivery_type,
        expected_pattern=expected_pattern,
        deadline_at=datetime(2030, 4, 5, 10, 30, tzinfo=timezone.utc),
    )


def _insert_expectation(
    connection: Connection,
    integration_id: UUID,
    *,
    delivery_type: str,
    expected_pattern: str,
    business_date: date = date(2026, 11, 16),
) -> UUID:
    expectation_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO delivery_expectations (
                id, integration_id, business_date, delivery_type, expected_pattern, deadline_at
            ) VALUES (
                :id, :integration_id, :business_date, :delivery_type, :expected_pattern, :deadline_at
            )
            """
        ),
        {
            "id": expectation_id,
            "integration_id": integration_id,
            "business_date": business_date,
            "delivery_type": delivery_type,
            "expected_pattern": expected_pattern,
            "deadline_at": datetime(2030, 1, 1, tzinfo=timezone.utc),
        },
    )
    return expectation_id


def _insert_incident(
    connection: Connection,
    expectation_id: UUID,
    *,
    incident_type: str,
    file_id: UUID | None = None,
    conflict_key: UUID | None = None,
    status: str = "OPEN",
    resolved_at: datetime | None = None,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO incidents (
                id, delivery_expectation_id, file_id, conflict_key, incident_type,
                status, reason, resolved_at
            ) VALUES (
                :id, :delivery_expectation_id, :file_id, :conflict_key,
                CAST(:incident_type AS incident_type), CAST(:status AS incident_status),
                'Synthetic integration test incident', :resolved_at
            )
            """
        ),
        {
            "id": uuid4(),
            "delivery_expectation_id": expectation_id,
            "file_id": file_id,
            "conflict_key": conflict_key,
            "incident_type": incident_type,
            "status": status,
            "resolved_at": resolved_at,
        },
    )


def _insert_file(connection: Connection, expectation_id: UUID) -> UUID:
    file_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO files (
                id, delivery_expectation_id, original_name, content_hash,
                size_bytes, received_at
            ) VALUES (
                :id, :delivery_expectation_id, :original_name, :content_hash,
                1, :received_at
            )
            """
        ),
        {
            "id": file_id,
            "delivery_expectation_id": expectation_id,
            "original_name": f"{file_id}.csv",
            "content_hash": uuid4().hex + uuid4().hex[:32],
            "received_at": datetime.now(timezone.utc),
        },
    )
    return file_id


def _assert_constraint_violation(
    connection: Connection,
    operation: Callable[[], object],
    expected_constraint: str,
) -> None:
    savepoint = connection.begin_nested()
    try:
        operation()
    except DBAPIError as error:
        diagnostic = getattr(error.orig, "diag", None)
        actual_constraint = getattr(diagnostic, "constraint_name", None)
        savepoint.rollback()
        assert actual_constraint == expected_constraint, (
            f"Expected constraint {expected_constraint!r}, got {actual_constraint!r}"
        )
    else:
        savepoint.rollback()
        pytest.fail(f"Expected PostgreSQL constraint {expected_constraint!r} to reject the statement")


@pytest.mark.integration
def test_create_and_list_integrations_with_stable_pagination(
    isolated_connection: Connection,
    session_factory: Callable[[], Session],
) -> None:
    first = _create_integration(session_factory, "  Treasury  ")
    second = _create_integration(session_factory, "Another Integration")
    assert first.name == "Treasury"
    assert first.source_name == "synthetic-service-test"

    with session_factory() as session:
        items = list_integrations(session, limit=100, offset=0)
    assert first.id in {item.id for item in items}
    assert second.id in {item.id for item in items}
    assert items == sorted(items, key=lambda item: (item.created_at, item.id), reverse=True)

    with session_factory() as session:
        first_page = list_integrations(session, limit=1, offset=0)
    with session_factory() as session:
        second_page = list_integrations(session, limit=1, offset=1)
    assert len(first_page) == 1
    assert len(second_page) == 1
    assert first_page[0].id != second_page[0].id

    event_count = isolated_connection.execute(
        text(
            """
            SELECT count(*)
            FROM delivery_events AS event
            JOIN delivery_expectations AS expectation
              ON expectation.id = event.delivery_expectation_id
            WHERE expectation.integration_id = :integration_id
            """
        ),
        {"integration_id": first.id},
    ).scalar_one()
    assert event_count == 0


@pytest.mark.integration
def test_duplicate_integration_name_is_translated_by_the_service(
    session_factory: Callable[[], Session],
) -> None:
    name = "duplicate-service-test"
    _create_integration(session_factory, name)

    with session_factory() as session:
        with pytest.raises(DuplicateIntegrationNameError):
            create_integration(
                session,
                IntegrationCreate(name=name, source_name="another-source"),
            )


@pytest.mark.integration
def test_create_expectation_persists_event_and_outbox_and_supports_filters(
    isolated_connection: Connection,
    session_factory: Callable[[], Session],
) -> None:
    integration = _create_integration(session_factory)
    with session_factory() as session:
        first = create_delivery_expectation(
            session,
            integration.id,
            _expectation_data("daily-*.csv", "DAILY_TRANSACTIONS"),
        )

    assert first.status == DeliveryStatus.EXPECTED
    assert first.overdue_at is None
    assert first.current_file_id is None

    event_row = isolated_connection.execute(
        text(
            """
            SELECT id, event_type, actor_type, actor_reference, details
            FROM delivery_events
            WHERE delivery_expectation_id = :delivery_expectation_id
            """
        ),
        {"delivery_expectation_id": first.id},
    ).mappings().one()
    assert event_row["event_type"] == "DeliveryExpectationCreated"
    assert event_row["actor_type"] == "SYSTEM"
    assert event_row["actor_reference"] == "opsbridge-api"
    assert event_row["details"]["expected_pattern"] == "daily-*.csv"
    assert event_row["details"]["delivery_type"] == "DAILY_TRANSACTIONS"
    assert event_row["details"]["status"] == "EXPECTED"

    outbox_row = isolated_connection.execute(
        text("SELECT event_type, payload FROM outbox_events WHERE event_id = :event_id"),
        {"event_id": event_row["id"]},
    ).mappings().one()
    assert outbox_row["event_type"] == "DeliveryExpectationCreated"
    assert outbox_row["payload"] == event_row["details"]

    with session_factory() as session:
        create_delivery_expectation(
            session,
            integration.id,
            _expectation_data("monthly-*.csv", "MONTHLY_TRANSACTIONS"),
        )
    with session_factory() as session:
        filtered = list_delivery_expectations(
            session,
            limit=1,
            offset=0,
            integration_id=integration.id,
            status=DeliveryStatus.EXPECTED,
        )
    assert len(filtered) == 1
    assert filtered[0].integration_id == integration.id
    assert filtered[0].status == DeliveryStatus.EXPECTED

    with session_factory() as session:
        all_for_integration = list_delivery_expectations(
            session,
            limit=50,
            offset=0,
            integration_id=integration.id,
        )
    assert len(all_for_integration) == 2
    assert all_for_integration == sorted(
        all_for_integration,
        key=lambda item: (item.created_at, item.id),
        reverse=True,
    )


@pytest.mark.integration
def test_nonexistent_integration_is_rejected_by_the_service(
    session_factory: Callable[[], Session],
) -> None:
    with session_factory() as session:
        with pytest.raises(IntegrationNotFoundError):
            create_delivery_expectation(
                session,
                UUID(int=0),
                _expectation_data("missing-integration.csv", "MISSING_INTEGRATION"),
            )


@pytest.mark.integration
def test_duplicate_delivery_expectation_identity_is_translated_by_the_service(
    session_factory: Callable[[], Session],
) -> None:
    integration = _create_integration(session_factory)
    data = _expectation_data("duplicate-expectation.csv", "DUPLICATE_EXPECTATION")
    with session_factory() as session:
        create_delivery_expectation(session, integration.id, data)

    with session_factory() as session:
        with pytest.raises(DuplicateDeliveryExpectationError):
            create_delivery_expectation(session, integration.id, data)


@pytest.mark.integration
def test_expectation_event_and_outbox_roll_back_together_on_outbox_failure(
    isolated_connection: Connection,
    session_factory: Callable[[], Session],
) -> None:
    integration = _create_integration(session_factory)
    failure_observed = False

    def fail_outbox_insert(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        nonlocal failure_observed
        if statement.lstrip().lower().startswith("insert into outbox_events"):
            failure_observed = True
            raise RuntimeError("Injected test failure before outbox insert")

    sqlalchemy_event.listen(isolated_connection, "before_cursor_execute", fail_outbox_insert)
    try:
        with session_factory() as session:
            with pytest.raises(RuntimeError, match="Injected test failure"):
                create_delivery_expectation(
                    session,
                    integration.id,
                    _expectation_data("rollback-expectation.csv", "ROLLBACK_EXPECTATION"),
                )
    finally:
        sqlalchemy_event.remove(isolated_connection, "before_cursor_execute", fail_outbox_insert)

    assert failure_observed
    assert isolated_connection.execute(
        text("SELECT count(*) FROM delivery_expectations WHERE integration_id = :id"),
        {"id": integration.id},
    ).scalar_one() == 0
    assert isolated_connection.execute(
        text(
            """
            SELECT count(*)
            FROM delivery_events AS event
            JOIN delivery_expectations AS expectation
              ON expectation.id = event.delivery_expectation_id
            WHERE expectation.integration_id = :integration_id
            """
        ),
        {"integration_id": integration.id},
    ).scalar_one() == 0
    assert isolated_connection.execute(
        text(
            """
            SELECT count(*)
            FROM outbox_events AS outbox
            JOIN delivery_events AS event ON event.id = outbox.event_id
            JOIN delivery_expectations AS expectation
              ON expectation.id = event.delivery_expectation_id
            WHERE expectation.integration_id = :integration_id
            """
        ),
        {"integration_id": integration.id},
    ).scalar_one() == 0


@pytest.mark.integration
def test_delivery_type_is_the_unique_identity_and_pattern_can_be_reused(
    isolated_connection: Connection,
    session_factory: Callable[[], Session],
) -> None:
    integration = _create_integration(session_factory)
    shared_pattern = "treasury-*.csv"
    _insert_expectation(
        isolated_connection,
        integration.id,
        delivery_type="TREASURY_TRANSACTIONS",
        expected_pattern=shared_pattern,
    )
    _insert_expectation(
        isolated_connection,
        integration.id,
        delivery_type="TREASURY_BALANCES",
        expected_pattern=shared_pattern,
    )

    _assert_constraint_violation(
        isolated_connection,
        lambda: _insert_expectation(
            isolated_connection,
            integration.id,
            delivery_type="TREASURY_TRANSACTIONS",
            expected_pattern="another-pattern.csv",
        ),
        "uq_delivery_expectation_delivery_type",
    )
    _assert_constraint_violation(
        isolated_connection,
        lambda: _insert_expectation(
            isolated_connection,
            integration.id,
            delivery_type="treasury_lowercase",
            expected_pattern="lowercase.csv",
        ),
        "ck_delivery_expectations_delivery_type_format",
    )


@pytest.mark.integration
def test_incident_file_rules_and_conflict_key_uniqueness(
    isolated_connection: Connection,
    session_factory: Callable[[], Session],
) -> None:
    integration = _create_integration(session_factory)

    def new_expectation(delivery_type: str) -> UUID:
        return _insert_expectation(
            isolated_connection,
            integration.id,
            delivery_type=delivery_type,
            expected_pattern=f"{delivery_type.lower()}-*.csv",
        )

    missing_expectation = new_expectation("MISSING_VALID")
    _insert_incident(isolated_connection, missing_expectation, incident_type="MISSING_FILE")

    valid_conflict_expectation = new_expectation("CONFLICT_VALID")
    conflict_key = uuid4()
    _insert_incident(
        isolated_connection,
        valid_conflict_expectation,
        incident_type="SOURCE_DELIVERY_ID_CONFLICT",
        conflict_key=conflict_key,
        status="RESOLVED",
        resolved_at=datetime.now(timezone.utc),
    )

    valid_validation_expectation = new_expectation("VALIDATION_VALID")
    valid_validation_file = _insert_file(isolated_connection, valid_validation_expectation)
    _insert_incident(
        isolated_connection,
        valid_validation_expectation,
        incident_type="VALIDATION_FAILURE",
        file_id=valid_validation_file,
    )

    valid_processing_expectation = new_expectation("PROCESSING_VALID")
    valid_processing_file = _insert_file(isolated_connection, valid_processing_expectation)
    _insert_incident(
        isolated_connection,
        valid_processing_expectation,
        incident_type="PROCESSING_FAILURE",
        file_id=valid_processing_file,
    )

    invalid_cases = [
        # Every invalid row gets its own delivery expectation (and file when
        # required), so an active-incident partial unique index cannot mask the
        # CHECK constraint being tested.
        ("CONFLICT_MISSING_KEY", "SOURCE_DELIVERY_ID_CONFLICT", False, None,
         "ck_incidents_conflict_key_matches_incident_type"),
        ("MISSING_HAS_FILE", "MISSING_FILE", True, None,
         "ck_incidents_file_reference_matches_incident_type"),
        ("MISSING_HAS_KEY", "MISSING_FILE", False, uuid4(),
         "ck_incidents_conflict_key_matches_incident_type"),
        ("VALIDATION_HAS_KEY", "VALIDATION_FAILURE", True, uuid4(),
         "ck_incidents_conflict_key_matches_incident_type"),
        ("PROCESSING_HAS_KEY", "PROCESSING_FAILURE", True, uuid4(),
         "ck_incidents_conflict_key_matches_incident_type"),
        ("CONFLICT_HAS_FILE", "SOURCE_DELIVERY_ID_CONFLICT", True, uuid4(),
         "ck_incidents_file_reference_matches_incident_type"),
        ("VALIDATION_MISSING_FILE", "VALIDATION_FAILURE", False, None,
         "ck_incidents_file_reference_matches_incident_type"),
        ("PROCESSING_MISSING_FILE", "PROCESSING_FAILURE", False, None,
         "ck_incidents_file_reference_matches_incident_type"),
    ]

    for delivery_type, incident_type, needs_file, incident_conflict_key, constraint_name in invalid_cases:
        expectation_id = new_expectation(delivery_type)
        file_id = _insert_file(isolated_connection, expectation_id) if needs_file else None
        _assert_constraint_violation(
            isolated_connection,
            lambda expectation_id=expectation_id, incident_type=incident_type,
            file_id=file_id, incident_conflict_key=incident_conflict_key: _insert_incident(
                isolated_connection,
                expectation_id,
                incident_type=incident_type,
                file_id=file_id,
                conflict_key=incident_conflict_key,
            ),
            constraint_name,
        )

    _assert_constraint_violation(
        isolated_connection,
        lambda: _insert_incident(
            isolated_connection,
            new_expectation("CONFLICT_DUPLICATE_KEY"),
            incident_type="SOURCE_DELIVERY_ID_CONFLICT",
            conflict_key=conflict_key,
            status="RESOLVED",
            resolved_at=datetime.now(timezone.utc),
        ),
        "uq_incidents_conflict_key",
    )
