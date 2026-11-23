from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timezone
from collections.abc import Iterator, Mapping
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError, DBAPIError
from sqlalchemy.pool import NullPool

from backend.app.config import DATABASE_URL_FROM_PROCESS, normalize_database_url


@pytest.fixture(scope="module")
def integration_engine() -> Iterator[Engine]:
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
def isolated_connection(integration_engine: Engine) -> Iterator[Connection]:
    connection = integration_engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _create_delivery(connection: Connection) -> UUID:
    unique_id = uuid4()
    integration_id = uuid4()
    delivery_expectation_id = uuid4()

    connection.execute(
        text(
            """
            INSERT INTO integrations (id, name, source_name)
            VALUES (:id, :name, :source_name)
            """
        ),
        {
            "id": integration_id,
            "name": f"trigger-test-{unique_id}",
            "source_name": "integration-test",
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO delivery_expectations (
                id, integration_id, business_date, delivery_type, expected_pattern, deadline_at
            )
            VALUES (:id, :integration_id, :business_date, :delivery_type, :expected_pattern, :deadline_at)
            """
        ),
        {
            "id": delivery_expectation_id,
            "integration_id": integration_id,
            "business_date": date.today(),
            "delivery_type": f"TRIGGER_{unique_id.hex[:20].upper()}",
            "expected_pattern": f"trigger-test-{unique_id}.csv",
            "deadline_at": datetime.now(timezone.utc),
        },
    )
    return delivery_expectation_id


def _create_file(connection: Connection, delivery_expectation_id: UUID) -> UUID:
    file_id = uuid4()
    content_hash = hashlib.sha256(uuid4().bytes).hexdigest()
    connection.execute(
        text(
            """
            INSERT INTO files (
                id, delivery_expectation_id, original_name, content_hash,
                size_bytes, received_at
            )
            VALUES (
                :id, :delivery_expectation_id, :original_name, :content_hash,
                :size_bytes, :received_at
            )
            """
        ),
        {
            "id": file_id,
            "delivery_expectation_id": delivery_expectation_id,
            "original_name": f"{file_id}.csv",
            "content_hash": content_hash,
            "size_bytes": 1,
            "received_at": datetime.now(timezone.utc),
        },
    )
    return file_id


def _expect_database_rejection(
    connection: Connection, statement: str, parameters: Mapping[str, object]
) -> None:
    with pytest.raises(DBAPIError):
        with connection.begin_nested():
            connection.execute(text(statement), parameters)


@pytest.mark.integration
def test_delivery_event_insert_is_allowed_but_update_and_delete_are_rejected(
    isolated_connection: Connection,
) -> None:
    delivery_expectation_id = _create_delivery(isolated_connection)
    event_id = uuid4()

    isolated_connection.execute(
        text(
            """
            INSERT INTO delivery_events (id, delivery_expectation_id, event_type)
            VALUES (:id, :delivery_expectation_id, :event_type)
            """
        ),
        {
            "id": event_id,
            "delivery_expectation_id": delivery_expectation_id,
            "event_type": "TriggerProtectionTest",
        },
    )
    assert isolated_connection.execute(
        text("SELECT event_type FROM delivery_events WHERE id = :id"), {"id": event_id}
    ).scalar_one() == "TriggerProtectionTest"

    _expect_database_rejection(
        isolated_connection,
        "UPDATE delivery_events SET event_type = :event_type WHERE id = :id",
        {"id": event_id, "event_type": "ChangedEventType"},
    )
    _expect_database_rejection(
        isolated_connection,
        "DELETE FROM delivery_events WHERE id = :id",
        {"id": event_id},
    )

    assert isolated_connection.execute(
        text("SELECT event_type FROM delivery_events WHERE id = :id"), {"id": event_id}
    ).scalar_one() == "TriggerProtectionTest"


@pytest.mark.integration
def test_valid_file_replacement_insert_is_allowed(isolated_connection: Connection) -> None:
    delivery_expectation_id = _create_delivery(isolated_connection)
    predecessor_id = _create_file(isolated_connection, delivery_expectation_id)
    replacement_id = uuid4()
    replacement_hash = hashlib.sha256(uuid4().bytes).hexdigest()

    isolated_connection.execute(
        text("UPDATE files SET status = 'VALIDATION_FAILED' WHERE id = :id"),
        {"id": predecessor_id},
    )

    isolated_connection.execute(
        text(
            """
            INSERT INTO files (
                id, delivery_expectation_id, original_name, content_hash,
                size_bytes, received_at, replaces_file_id
            )
            VALUES (
                :id, :delivery_expectation_id, :original_name, :content_hash,
                :size_bytes, :received_at, :replaces_file_id
            )
            """
        ),
        {
            "id": replacement_id,
            "delivery_expectation_id": delivery_expectation_id,
            "original_name": f"{replacement_id}.csv",
            "content_hash": replacement_hash,
            "size_bytes": 2,
            "received_at": datetime.now(timezone.utc),
            "replaces_file_id": predecessor_id,
        },
    )

    assert isolated_connection.execute(
        text("SELECT replaces_file_id FROM files WHERE id = :id"), {"id": replacement_id}
    ).scalar_one() == predecessor_id


@pytest.mark.integration
def test_file_cannot_replace_itself(isolated_connection: Connection) -> None:
    delivery_expectation_id = _create_delivery(isolated_connection)
    file_id = uuid4()
    content_hash = hashlib.sha256(uuid4().bytes).hexdigest()

    with pytest.raises(DBAPIError) as exc_info:
        with isolated_connection.begin_nested():
            isolated_connection.execute(
                text(
                    """
                    INSERT INTO files (
                        id, delivery_expectation_id, original_name, content_hash,
                        size_bytes, received_at, replaces_file_id
                    )
                    VALUES (
                        :id, :delivery_expectation_id, :original_name, :content_hash,
                        :size_bytes, :received_at, :replaces_file_id
                    )
                    """
                ),
                {
                    "id": file_id,
                    "delivery_expectation_id": delivery_expectation_id,
                    "original_name": f"{file_id}.csv",
                    "content_hash": content_hash,
                    "size_bytes": 1,
                    "received_at": datetime.now(timezone.utc),
                    "replaces_file_id": file_id,
                },
            )

    assert "a file cannot replace itself" in str(exc_info.value.orig)


@pytest.mark.integration
def test_replacement_cycle_is_rejected(isolated_connection: Connection) -> None:
    delivery_expectation_id = _create_delivery(isolated_connection)
    first_file_id = _create_file(isolated_connection, delivery_expectation_id)
    second_file_id = _create_file(isolated_connection, delivery_expectation_id)

    isolated_connection.execute(
        text("UPDATE files SET replaces_file_id = :predecessor_id WHERE id = :file_id"),
        {"file_id": first_file_id, "predecessor_id": second_file_id},
    )
    _expect_database_rejection(
        isolated_connection,
        "UPDATE files SET replaces_file_id = :predecessor_id WHERE id = :file_id",
        {"file_id": second_file_id, "predecessor_id": first_file_id},
    )


@pytest.mark.integration
def test_existing_replacement_link_cannot_be_changed(isolated_connection: Connection) -> None:
    delivery_expectation_id = _create_delivery(isolated_connection)
    predecessor_id = _create_file(isolated_connection, delivery_expectation_id)
    replacement_id = _create_file(isolated_connection, delivery_expectation_id)
    alternate_predecessor_id = _create_file(isolated_connection, delivery_expectation_id)

    isolated_connection.execute(
        text("UPDATE files SET replaces_file_id = :predecessor_id WHERE id = :file_id"),
        {"file_id": replacement_id, "predecessor_id": predecessor_id},
    )
    _expect_database_rejection(
        isolated_connection,
        "UPDATE files SET replaces_file_id = :predecessor_id WHERE id = :file_id",
        {"file_id": replacement_id, "predecessor_id": alternate_predecessor_id},
    )


@pytest.mark.integration
def test_existing_replacement_link_cannot_be_cleared(isolated_connection: Connection) -> None:
    delivery_expectation_id = _create_delivery(isolated_connection)
    predecessor_id = _create_file(isolated_connection, delivery_expectation_id)
    replacement_id = _create_file(isolated_connection, delivery_expectation_id)

    isolated_connection.execute(
        text("UPDATE files SET replaces_file_id = :predecessor_id WHERE id = :file_id"),
        {"file_id": replacement_id, "predecessor_id": predecessor_id},
    )
    _expect_database_rejection(
        isolated_connection,
        "UPDATE files SET replaces_file_id = NULL WHERE id = :file_id",
        {"file_id": replacement_id},
    )
