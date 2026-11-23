"""Exercise the operational worker transactions on verified disposable PostgreSQL."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import os
from uuid import uuid4

from backend.app.models.security import OperatorAccount
from backend.app.security import Principal

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from backend.app.api.routers.dashboard import ReprocessingRequest, reprocess
from backend.app.intake.paths import accepted_package_directory
from backend.app.intake.worker import lifecycle
from backend.app.models import (
    ActorType, DeliveryEvent, DeliveryExpectation, DeliveryStatus, File, FileStatus, Incident,
    IncidentStatus, IncidentType, IntakeClaim, IntakeClaimStatus, IntakeFinalLocation, Integration, OutboxEvent,
)
from backend.app.services import processing
from backend.app.services.file_intake import committed_outcome
from backend.app.intake.snapshot import Inspection
from backend.app.intake.manifest import DeliveryManifest, PayloadManifest
from backend.app.services.sla import detect_overdue


@pytest.fixture
def verified_connection():
    if os.environ.get("OPSBRIDGE_RUN_INTEGRATION") != "1":
        pytest.skip("Explicit PostgreSQL opt-in required")
    from backend.app.config import DATABASE_URL_FROM_PROCESS
    if not DATABASE_URL_FROM_PROCESS:
        pytest.fail("A process-supplied isolated PostgreSQL URL is required")
    url = make_url(DATABASE_URL_FROM_PROCESS)
    if url.database != "opsbridge_test" or url.host not in {"localhost", "127.0.0.1"} or url.query:
        pytest.fail("The operations test requires local opsbridge_test")
    engine = create_engine(url.set(drivername="postgresql+psycopg"), poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection, connection.begin() as transaction:
            assert connection.scalar(text("SELECT current_database()")) == "opsbridge_test"
            yield engine, connection
            transaction.rollback()
    finally:
        engine.dispose()


def make_delivery(connection, now):
    integration_id, delivery_id = uuid4(), uuid4()
    with Session(connection) as session, session.begin():
        session.add(Integration(id=integration_id, name=f"ops-{integration_id}", source_name="synthetic"))
        session.flush()
        session.add(DeliveryExpectation(id=delivery_id, integration_id=integration_id, business_date=date(2026, 1, 1),
                    deadline_at=now - timedelta(minutes=1), delivery_type="LEDGER", expected_pattern="*.csv"))
    return integration_id, delivery_id


def test_sla_persists_once_and_late_intake_resolves_missing_incident(verified_connection):
    _, connection = verified_connection
    now = datetime.now(timezone.utc)
    integration_id, delivery_id = make_delivery(connection, now)
    with Session(connection) as session, session.begin():
        assert detect_overdue(session, now) == 1
    with Session(connection) as session, session.begin():
        assert detect_overdue(session, now + timedelta(seconds=1)) == 0
        row = session.get(DeliveryExpectation, delivery_id)
        assert row.overdue_at == now and row.status == DeliveryStatus.EXPECTED
        incident = session.scalar(select(Incident).where(Incident.delivery_expectation_id == delivery_id))
        assert incident.status == IncidentStatus.OPEN and incident.incident_type == IncidentType.MISSING_FILE
        claim = IntakeClaim(integration_id=integration_id, status=IntakeClaimStatus.VALIDATED)
        session.add(claim)
        session.flush()
        digest = sha256(b"synthetic").hexdigest()
        manifest = DeliveryManifest(1, date(2026, 1, 1), "LEDGER", None, PayloadManifest("ledger.csv", 9, digest))
        committed_outcome(session, claim, Inspection(manifest, digest, 9), 1, None)
        assert incident.status == IncidentStatus.RESOLVED
    with Session(connection) as session:
        row = session.get(DeliveryExpectation, delivery_id)
        assert row.status == DeliveryStatus.RECEIVED and row.overdue_at == now
        audited = list(session.scalars(select(DeliveryEvent).where(DeliveryEvent.delivery_expectation_id == delivery_id)
                                      .order_by(DeliveryEvent.occurred_at)))
        assert [event.event_type for event in audited] == ["DeliveryOverdue", "FileReceived"]
        assert session.scalar(select(OutboxEvent).where(OutboxEvent.event_id == audited[0].id)).event_type == "DeliveryOverdue"


def test_processing_crash_exhaustion_manual_audit_and_success(verified_connection, monkeypatch, tmp_path):
    engine, connection = verified_connection
    clock = datetime.now(timezone.utc)
    integration_id, delivery_id = make_delivery(connection, clock)
    file_id, claim_id = uuid4(), uuid4()
    data = b"record_id,record_date,amount,currency,reference\nX,2026-01-01,9,EUR,\n"
    digest = sha256(data).hexdigest()
    with Session(connection) as session, session.begin():
        row = session.get(DeliveryExpectation, delivery_id)
        row.status = DeliveryStatus.RECEIVED
        session.add(File(id=file_id, delivery_expectation_id=delivery_id, original_name="ledger.csv",
                         content_hash=digest, size_bytes=len(data), received_at=clock))
        session.flush()
        row.current_file_id = file_id
        session.add(IntakeClaim(id=claim_id, integration_id=integration_id, delivery_expectation_id=delivery_id,
                                file_id=file_id, status=IntakeClaimStatus.FINALIZED,
                                final_location=IntakeFinalLocation.ACCEPTED, finalized_at=clock))
    with lifecycle(engine, file_id, namespace="processing:file") as lock:
        assert lock is not None
        assert not processing.process_file(engine, tmp_path, delivery_id, file_id)

    @contextmanager
    def local_transaction(*_, **__):
        yield connection

    monkeypatch.setattr(processing, "lifecycle", local_transaction)

    def interrupted(*_):
        raise RuntimeError("Simulated worker exit")

    with pytest.raises(RuntimeError, match="Simulated worker exit"):
        processing.process_file(engine, tmp_path, delivery_id, file_id, clock=lambda: clock, processor=interrupted)
    assert processing.process_file(engine, tmp_path, delivery_id, file_id, clock=lambda: clock)
    assert not processing.process_file(engine, tmp_path, delivery_id, file_id, clock=lambda: clock)
    clock += processing.RETRY_DELAY
    assert processing.process_file(engine, tmp_path, delivery_id, file_id, clock=lambda: clock)
    clock += processing.RETRY_DELAY
    assert processing.process_file(engine, tmp_path, delivery_id, file_id, clock=lambda: clock)
    clock += processing.RETRY_DELAY
    assert not processing.process_file(engine, tmp_path, delivery_id, file_id, clock=lambda: clock)
    request = ReprocessingRequest(file_id=file_id, attempt_series=1, confirmed=True)
    with Session(connection) as session, session.begin():
        account = OperatorAccount(username="test-operator", password_hash="unused", role="OPERATOR", active=True)
        session.add(account)
        session.flush()
        principal = Principal(account.id, account.username, account.role, "", clock)
    with Session(connection) as session:
        file = session.get(File, file_id)
        assert file.status == FileStatus.PROCESSING_FAILED
        assert file.attempt_count_in_series == 3
        assert file.processing_error_code == "STORAGE_UNAVAILABLE"
    with Session(connection) as session:
        assert reprocess(delivery_id, request, session, principal) == {"status": "queued"}
    with Session(connection, join_transaction_mode="create_savepoint") as session, pytest.raises(HTTPException) as conflict:
        reprocess(delivery_id, request, session, principal)
    assert conflict.value.status_code == 409

    package = accepted_package_directory(integration_id, claim_id, root=tmp_path)
    package.mkdir(parents=True)
    (package / "manifest.json").write_text("{}", encoding="utf-8")
    (package / "ledger.csv").write_bytes(data)
    assert processing.process_file(engine, tmp_path, delivery_id, file_id, clock=lambda: clock)
    assert not processing.process_file(engine, tmp_path, delivery_id, file_id, clock=lambda: clock)
    with Session(connection) as session:
        row = session.get(DeliveryExpectation, delivery_id)
        file = session.get(File, file_id)
        assert row.status == DeliveryStatus.COMPLETED and row.current_file_id == file_id
        assert file.status == FileStatus.COMPLETED and (file.attempt_series, file.attempt_count_in_series) == (2, 1)
        incident = session.scalar(select(Incident).where(Incident.file_id == file_id))
        assert incident.status == IncidentStatus.RESOLVED
        events = list(session.scalars(select(DeliveryEvent).where(DeliveryEvent.file_id == file_id)))
        assert len(events) == 9
        assert sorted(event.details["error_code"] for event in events if event.event_type == "FileProcessingFailed") == [
            "STORAGE_UNAVAILABLE", "STORAGE_UNAVAILABLE", "WORKER_INTERRUPTED",
        ]
        manual, = [event for event in events if event.event_type == "ManualReprocessingRequested"]
        assert manual.actor_type == ActorType.OPERATOR and manual.actor_reference == str(principal.id)
        assert manual.details["attempt_series"] == 2
        assert len(list(session.scalars(select(OutboxEvent).where(
            OutboxEvent.event_id.in_([event.id for event in events]))))) == 9
