"""Exercise worker persistence and immutable history on the disposable database."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.app.config import DATABASE_URL_FROM_PROCESS
from backend.app.api.routers.reconciliation import detail
from backend.app.event_worker import verified_engine
from backend.app.models import (
    DeliveryEvent, DeliveryExpectation, DeliveryStatus, File, FileStatus, Incident, IntakeClaim,
    Integration, ReconciliationDefinition, ReconciliationRun,
)
from backend.app.services import reconciliation as service
from backend.app.services.processing import SnapshotReadError

pytestmark = pytest.mark.integration


@pytest.fixture
def isolated(monkeypatch):
    if os.getenv("OPSBRIDGE_RUN_INTEGRATION") != "1":
        pytest.skip("Explicit opt-in required")
    if not DATABASE_URL_FROM_PROCESS:
        pytest.fail("Supply the verified isolated test connection")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL_FROM_PROCESS)
    monkeypatch.setenv("OPSBRIDGE_EXPECTED_DATABASE", "opsbridge_test")
    engine = verified_engine()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            @contextmanager
            def hold(*args, **kwargs):
                yield connection
            monkeypatch.setattr(service, "lifecycle", hold)
            yield engine, connection
            if transaction.is_active:
                transaction.rollback()
    finally:
        engine.dispose()


def sources(connection, now, *, missing=False):
    with Session(connection, expire_on_commit=False) as session, session.begin():
        deliveries = []
        for side in range(2):
            integration = Integration(name=str(uuid4()), source_name="Synthetic")
            session.add(integration)
            session.flush()
            complete = not missing or side == 0
            delivery = DeliveryExpectation(integration_id=integration.id, business_date=now.date(),
                                           deadline_at=now - timedelta(minutes=5), delivery_type="POSITION",
                                           expected_pattern="*.csv",
                                           status=DeliveryStatus.COMPLETED if complete else DeliveryStatus.EXPECTED)
            session.add(delivery)
            session.flush()
            if complete:
                file = File(delivery_expectation_id=delivery.id, original_name="positions.csv", size_bytes=10,
                            content_hash="a" * 64, received_at=now, status=FileStatus.COMPLETED)
                session.add(file)
                session.flush()
                delivery.current_file_id = file.id
                session.add(IntakeClaim(integration_id=integration.id, file_id=file.id, delivery_expectation_id=delivery.id,
                                        status="FINALIZED", finalized_at=now, final_location="ACCEPTED"))
            deliveries.append(delivery)
        definition = ReconciliationDefinition(name="Synthetic comparison", source_a_delivery_id=deliveries[0].id,
                    source_b_delivery_id=deliveries[1].id, match_on="reference", tolerance=Decimal("0"),
                    exception_limit=1, incident_on_missing=True, incident_on_failure=True)
        session.add(definition)
        session.flush()
        return service.enqueue(session, definition, deliveries[0], now).id


def test_waits_for_missing_source_and_emits_one_incident(isolated):
    engine, connection = isolated
    now = datetime.now(timezone.utc)
    run_id = sources(connection, now, missing=True)
    for seconds in (0, 10):
        assert service.execute_run(engine, None, run_id, clock=lambda: now + timedelta(seconds=seconds)) is False
    with Session(connection) as session:
        run = session.get(ReconciliationRun, run_id)
        assert run.status == "WAITING" and run.attempts == 0 and run.file_a_id is None and run.missing_reported
        assert session.scalar(select(Incident.id).where(Incident.reconciliation_run_id == run_id))
        events = session.scalars(select(DeliveryEvent.event_type).where(
            DeliveryEvent.delivery_expectation_id == run.source_a_delivery_id)).all()
        assert events.count("ReconciliationSourceMissing") == 1


def test_retries_are_bounded_and_terminal_history_is_immutable(isolated):
    engine, connection = isolated
    now = datetime.now(timezone.utc)
    run_id = sources(connection, now)
    def unavailable(*_):
        raise SnapshotReadError("STORAGE_UNAVAILABLE")
    for seconds in (0, 10, 20):
        assert service.execute_run(engine, None, run_id, clock=lambda: now + timedelta(seconds=seconds), reader=unavailable)
    assert not service.execute_run(engine, None, run_id, clock=lambda: now + timedelta(minutes=1), reader=unavailable)
    with Session(connection) as session:
        run = session.get(ReconciliationRun, run_id)
        assert (run.status, run.attempts, run.report) == ("FAILED", 3, None)
        assert run.file_a_id and run.file_b_id and run.finished_at
        for sql in ("UPDATE reconciliation_runs SET attempts = 0 WHERE id = :key",
                    "DELETE FROM reconciliation_runs WHERE id = :key"):
            with pytest.raises(DBAPIError, match="reconciliation history is immutable"), session.begin_nested():
                session.execute(text(sql), {"key": run_id})


def test_reconciliation_result_pages_keep_original_citation_indices(isolated):
    engine, connection = isolated
    now = datetime.now(timezone.utc)
    run_id = sources(connection, now)
    with Session(connection) as session:
        assert detail(run_id, limit=1, offset=0, session=session)["items"] == []

    def reader(_root, delivery, _file, _claim):
        keys = ("a", "b", "c") if delivery.id == source_a else ("b",)
        return [(key, now.date(), Decimal("0.001"), "USD", key) for key in keys]

    with Session(connection) as session:
        source_a = session.get(ReconciliationRun, run_id).source_a_delivery_id
    assert service.execute_run(engine, None, run_id, clock=lambda: now, reader=reader)
    with Session(connection) as session:
        start = detail(run_id, limit=1, offset=0, category="MISSING_B", session=session)
        last = detail(run_id, limit=1, offset=1, category="MISSING_B", session=session)
        assert start["has_more"] and not last["has_more"]
        assert start["items"][0] == {"index": 1, "category": "MISSING_B", "currency": "USD",
                                     "difference": "0.001000", "count_a": 1, "count_b": 0}
        assert last["items"][0]["index"] == 3
        assert detail(run_id, limit=1, offset=3, session=session)["items"] == []
