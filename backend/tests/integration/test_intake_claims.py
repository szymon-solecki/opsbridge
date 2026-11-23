"""PostgreSQL constraint tests for intake claims; only runs against opsbridge_test."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError, DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from backend.app.config import DATABASE_URL_FROM_PROCESS, normalize_database_url
from backend.app.models import IntakeClaim, IntakeClaimStatus, IntakeFinalLocation


@pytest.fixture(scope="module")
def intake_test_engine() -> Iterator[Engine]:
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
def isolated_connection(intake_test_engine: Engine) -> Iterator[Connection]:
    connection = intake_test_engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _create_integration(connection: Connection) -> UUID:
    integration_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO integrations (id, name, source_name)
            VALUES (:id, :name, 'synthetic-intake-claim-test')
            """
        ),
        {"id": integration_id, "name": f"intake-claim-{uuid4()}"},
    )
    return integration_id


def _create_expectation(connection: Connection, integration_id: UUID) -> UUID:
    expectation_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO delivery_expectations (
                id, integration_id, business_date, delivery_type, expected_pattern, deadline_at
            ) VALUES (
                :id, :integration_id, :business_date, :delivery_type, 'payload-*.csv', :deadline_at
            )
            """
        ),
        {
            "id": expectation_id,
            "integration_id": integration_id,
            "business_date": date(2026, 1, 1),
            "delivery_type": f"CLAIM_{uuid4().hex[:16].upper()}",
            "deadline_at": datetime(2030, 1, 1, tzinfo=timezone.utc),
        },
    )
    return expectation_id


def _create_file(connection: Connection, expectation_id: UUID) -> UUID:
    file_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO files (
                id, delivery_expectation_id, original_name, content_hash, size_bytes, received_at
            ) VALUES (
                :id, :expectation_id, 'payload.csv', :content_hash, 0, :received_at
            )
            """
        ),
        {
            "id": file_id,
            "expectation_id": expectation_id,
            "content_hash": uuid4().hex * 2,
            "received_at": datetime.now(timezone.utc),
        },
    )
    return file_id


def _create_claim_parents(connection: Connection) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    integration_id = _create_integration(connection)
    other_integration_id = _create_integration(connection)
    expectation_id = _create_expectation(connection, integration_id)
    other_expectation_id = _create_expectation(connection, other_integration_id)
    file_id = _create_file(connection, expectation_id)
    other_file_id = _create_file(connection, other_expectation_id)
    return integration_id, other_integration_id, expectation_id, other_expectation_id, file_id, other_file_id


def _insert_claim(
    connection: Connection,
    *,
    integration_id: UUID,
    delivery_expectation_id: UUID | None = None,
    file_id: UUID | None = None,
    status: str = "CLAIMED",
    final_location: str | None = None,
    content_hash: str | None = None,
    source_delivery_id: str | None = None,
    finalized_at: datetime | None = None,
) -> UUID:
    claim_id = uuid4()
    connection.execute(
        text(
            """
            INSERT INTO intake_claims (
                id, integration_id, delivery_expectation_id, file_id, status, final_location,
                content_hash, source_delivery_id, finalized_at
            ) VALUES (
                :id, :integration_id, :delivery_expectation_id, :file_id,
                CAST(:status AS intake_claim_status),
                CAST(:final_location AS intake_final_location),
                :content_hash, :source_delivery_id, :finalized_at
            )
            """
        ),
        {
            "id": claim_id,
            "integration_id": integration_id,
            "delivery_expectation_id": delivery_expectation_id,
            "file_id": file_id,
            "status": status,
            "final_location": final_location,
            "content_hash": content_hash,
            "source_delivery_id": source_delivery_id,
            "finalized_at": finalized_at,
        },
    )
    return claim_id


def _assert_rejected(connection: Connection, operation, *, constraint: str | None = None, sqlstate: str | None = None) -> None:
    savepoint = connection.begin_nested()
    try:
        operation()
    except DBAPIError as error:
        diagnostic = getattr(error.orig, "diag", None)
        actual_constraint = getattr(diagnostic, "constraint_name", None)
        actual_sqlstate = getattr(error.orig, "sqlstate", None)
        savepoint.rollback()
        if constraint is not None:
            assert actual_constraint == constraint
        if sqlstate is not None:
            assert actual_sqlstate == sqlstate
    else:
        savepoint.rollback()
        pytest.fail(f"Expected rejection (constraint={constraint!r}, sqlstate={sqlstate!r})")


@pytest.mark.integration
def test_valid_intake_claim_uses_claimed_defaults(isolated_connection: Connection) -> None:
    (
        integration_id,
        _other_integration_id,
        expectation_id,
        _other_expectation_id,
        file_id,
        _other_file_id,
    ) = _create_claim_parents(isolated_connection)
    session = Session(bind=isolated_connection, join_transaction_mode="create_savepoint")
    try:
        claim = IntakeClaim(
            integration_id=integration_id,
            delivery_expectation_id=expectation_id,
            file_id=file_id,
            content_hash="a" * 64,
            source_delivery_id="vendor-delivery-001",
        )
        session.add(claim)
        session.flush()
        assert claim.id is not None
        assert claim.status is IntakeClaimStatus.CLAIMED
        assert claim.delivery_expectation_id == expectation_id
        assert claim.file_id == file_id
        assert claim.final_location is None
        assert claim.finalized_at is None
    finally:
        session.close()


@pytest.mark.integration
def test_finalized_intake_claim_persists_final_location_and_utc_timestamp(
    isolated_connection: Connection,
) -> None:
    (
        integration_id,
        _other_integration_id,
        expectation_id,
        _other_expectation_id,
        file_id,
        _other_file_id,
    ) = _create_claim_parents(isolated_connection)
    finalized_at = datetime.now(timezone.utc)
    session = Session(bind=isolated_connection, join_transaction_mode="create_savepoint")
    try:
        claim = IntakeClaim(
            integration_id=integration_id,
            delivery_expectation_id=expectation_id,
            file_id=file_id,
            status=IntakeClaimStatus.FINALIZED,
            final_location=IntakeFinalLocation.ACCEPTED,
            finalized_at=finalized_at,
        )
        session.add(claim)
        session.flush()
        session.refresh(claim)

        assert claim.status is IntakeClaimStatus.FINALIZED
        assert claim.final_location is IntakeFinalLocation.ACCEPTED
        assert claim.finalized_at is not None
        assert claim.finalized_at.tzinfo is not None
        assert claim.finalized_at.astimezone(timezone.utc) == finalized_at
    finally:
        session.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("case", "constraint", "sqlstate"),
    [
        ("invalid_integration", "fk_intake_claims_integration_id_integrations", None),
        ("expectation_other_integration", "fk_intake_claims_expectation_same_integration", None),
        ("file_other_expectation", "fk_intake_claims_file_same_expectation", None),
        ("file_without_expectation", "ck_intake_claims_file_requires_expectation", None),
        ("invalid_hash", "ck_intake_claims_content_hash_sha256_format", None),
        ("empty_source_id", "ck_intake_claims_source_delivery_id_nonblank", None),
        ("blank_source_id", "ck_intake_claims_source_delivery_id_nonblank", None),
        ("long_source_id", None, "22001"),
        ("finalized_without_location", "ck_intake_claims_finalization_fields_match_status", None),
        ("finalized_without_timestamp", "ck_intake_claims_finalization_fields_match_status", None),
        ("nonfinalized_with_location", "ck_intake_claims_finalization_fields_match_status", None),
        ("nonfinalized_with_timestamp", "ck_intake_claims_finalization_fields_match_status", None),
    ],
)
def test_database_rejects_invalid_intake_claims(
    isolated_connection: Connection,
    case: str,
    constraint: str | None,
    sqlstate: str | None,
) -> None:
    (
        integration_id,
        other_integration_id,
        expectation_id,
        other_expectation_id,
        file_id,
        other_file_id,
    ) = _create_claim_parents(isolated_connection)
    finalized_at = datetime.now(timezone.utc)

    cases = {
        "invalid_integration": {
            "integration_id": uuid4(),
        },
        "expectation_other_integration": {
            "integration_id": integration_id,
            "delivery_expectation_id": other_expectation_id,
        },
        "file_other_expectation": {
            "integration_id": integration_id,
            "delivery_expectation_id": expectation_id,
            "file_id": other_file_id,
        },
        "file_without_expectation": {
            "integration_id": integration_id,
            "file_id": file_id,
        },
        "invalid_hash": {
            "integration_id": integration_id,
            "content_hash": "A" * 64,
        },
        "empty_source_id": {
            "integration_id": integration_id,
            "source_delivery_id": "",
        },
        "blank_source_id": {
            "integration_id": integration_id,
            "source_delivery_id": " \t\r\n",
        },
        "long_source_id": {
            "integration_id": integration_id,
            "source_delivery_id": "x" * 256,
        },
        "finalized_without_location": {
            "integration_id": integration_id,
            "status": "FINALIZED",
            "finalized_at": finalized_at,
        },
        "finalized_without_timestamp": {
            "integration_id": integration_id,
            "status": "FINALIZED",
            "final_location": "ACCEPTED",
        },
        "nonfinalized_with_location": {
            "integration_id": integration_id,
            "final_location": "ACCEPTED",
        },
        "nonfinalized_with_timestamp": {
            "integration_id": integration_id,
            "finalized_at": finalized_at,
        },
    }
    _assert_rejected(
        isolated_connection,
        lambda: _insert_claim(isolated_connection, **cases[case]),
        constraint=constraint,
        sqlstate=sqlstate,
    )
