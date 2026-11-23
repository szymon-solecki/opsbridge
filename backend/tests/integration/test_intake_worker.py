"""Exercise real PostgreSQL domain outcomes inside a rollback-only outer transaction."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app.intake import worker
from backend.app.security import Principal
from backend.app.api.routers.dashboard import DashboardDelivery, deliveries, delivery, events, overview
from backend.app.services.operations import attention_items, operations_summary
from backend.app.intake.paths import accepted_package_directory, quarantine_package_directory, work_claim_directory
from backend.app.models import (DeliveryEvent, DeliveryExpectation, File, Incident, IncidentStatus,
                                IncidentType, IntakeClaim, IntakeClaimStatus, Integration, OutboxEvent)


@pytest.mark.integration
def test_claim_business_replay_and_finalization(tmp_path, monkeypatch):
    if os.environ.get("OPSBRIDGE_RUN_INTEGRATION") != "1":
        pytest.skip("Explicit PostgreSQL opt-in required")
    from backend.app.config import DATABASE_URL_FROM_PROCESS, normalize_database_url
    if not DATABASE_URL_FROM_PROCESS:
        pytest.fail("Explicit isolated database URL required")
    url = make_url(normalize_database_url(DATABASE_URL_FROM_PROCESS))
    if url.database != "opsbridge_test" or url.host not in {"localhost", "127.0.0.1"} or url.query:
        pytest.fail("Local isolated opsbridge_test required")
    engine = create_engine(url, hide_parameters=True)
    integration, expectation = uuid4(), uuid4()
    try:
        with engine.connect() as conn, conn.begin() as outer:
            assert conn.scalar(text("SELECT current_database()")) == "opsbridge_test"

            @contextmanager
            def held_connection(*_):
                yield conn

            # Keep all business transactions inside this test's outer rollback.
            monkeypatch.setattr(worker, "lifecycle", held_connection)
            with Session(conn) as db, db.begin():
                db.add(Integration(id=integration, name=f"demo-{integration}", source_name="synthetic"))
                db.flush()
                db.add(DeliveryExpectation(id=expectation, integration_id=integration,
                    business_date=date(2026, 1, 1), delivery_type="DAILY", expected_pattern="*.csv",
                    deadline_at=datetime(2026, 1, 2, tzinfo=timezone.utc)))
                db.flush()
                db.add(Incident(delivery_expectation_id=expectation, incident_type=IncidentType.MISSING_FILE,
                                reason="Synthetic overdue delivery"))

            def deliver(data, source_id, *, mismatch=False, interrupt=False):
                claim = uuid4()
                work = work_claim_directory(integration, claim, root=tmp_path)
                source = work / "source"
                source.mkdir(parents=True)
                (source / "input.csv").write_bytes(data)
                (source / "manifest.json").write_text(json.dumps(dict(contract_version=1,
                    business_date="2026-01-01", delivery_type="DAILY", source_delivery_id=source_id,
                    payload=dict(file_name="input.csv", size_bytes=len(data),
                                 sha256="0"*64 if mismatch else hashlib.sha256(data).hexdigest()))))
                if interrupt:
                    with monkeypatch.context() as scoped:
                        def stop(*args):
                            raise OSError("Simulated interruption after business commit")
                        scoped.setattr(worker, "finalize", stop)
                        with pytest.raises(OSError):
                            worker.process(engine, tmp_path, integration, claim)
                    with Session(conn) as db:
                        assert db.get(IntakeClaim, claim).status == IntakeClaimStatus.COMMITTED
                worker.process(engine, tmp_path, integration, claim)
                worker.process(engine, tmp_path, integration, claim)
                with Session(conn) as db:
                    saved = db.get(IntakeClaim, claim)
                    assert saved.status == IntakeClaimStatus.FINALIZED
                    build = quarantine_package_directory if saved.error_code else accepted_package_directory
                    assert (build(integration, claim, root=tmp_path) / "input.csv").read_bytes() == data
                    return saved.file_id, saved.error_code

            assert deliver(b"bad", "mismatch", mismatch=True) == (None, "INTEGRITY_MISMATCH")
            with Session(conn) as db:
                assert db.scalar(select(Incident.status).where(Incident.delivery_expectation_id == expectation)) == IncidentStatus.RESOLVED
            failed, error = deliver(b"", "first")
            assert failed and error is None
            good = b"record_id,record_date,amount,currency,reference\n"
            received, error = deliver(good, "second", interrupt=True)
            assert received and error is None
            assert deliver(good, "alias") == (received, None)
            for _ in range(2):
                assert deliver(b"", "second") == (None, "SOURCE_DELIVERY_ID_CONFLICT")
            assert deliver(b"extra", "third") == (None, "UNEXPECTED_DISTINCT_PAYLOAD")
            with Session(conn) as db:
                assert db.get(DeliveryExpectation, expectation).current_file_id == received
                principal = Principal(uuid4(), "test-viewer", "VIEWER", "", datetime.now(timezone.utc))
                assert overview(db, principal).counts.get("RECEIVED", 0) >= 1
                rows = deliveries(integration_id=integration, status="RECEIVED", offset=0, limit=20, session=db)
                row, = map(DashboardDelivery.model_validate, rows)
                assert row.current_file.id == received
                assert row.current_file.replaces_file_id == failed
                assert delivery(row.id, db).id == row.id
                assert db.get(File, received).replaces_file_id == failed
                assert db.get(File, failed).status.value == "VALIDATION_FAILED"
                assert db.scalar(select(func.count()).select_from(File).where(File.delivery_expectation_id == expectation)) == 2
                persisted_events = list(db.scalars(select(DeliveryEvent).where(DeliveryEvent.delivery_expectation_id == expectation)))
                assert sorted(e.event_type for e in persisted_events) == ["FileReceived", "FileValidationFailed", "SourceDeliveryIdConflict"]
                assert db.scalar(select(func.count()).select_from(OutboxEvent).where(
                    OutboxEvent.event_id.in_([e.id for e in persisted_events]))) == 3
                active = db.scalars(select(Incident.incident_type).where(Incident.delivery_expectation_id == expectation,
                                                                         Incident.status != IncidentStatus.RESOLVED))
                assert list(active) == [IncidentType.SOURCE_DELIVERY_ID_CONFLICT]
                timeline = events(expectation, offset=0, limit=2, session=db)
                tail = events(expectation, offset=2, limit=2, session=db)
                assert [event["event_type"] for event in timeline + tail] == [
                    "FileValidationFailed", "FileReceived", "SourceDeliveryIdConflict",
                ]
                assert timeline[1]["replaces_file_id"] == failed
                assert tail[0]["details"]["existing_file_id"] == str(received)
            cut = datetime.now(timezone.utc)
            with Session(conn) as db, db.begin():
                for kind, due in (("MISSING", cut - timedelta(seconds=1)), ("BOUNDARY", cut)):
                    db.add(DeliveryExpectation(integration_id=integration, business_date=date(2026, 1, 1),
                                               delivery_type=kind, expected_pattern="*.csv", deadline_at=due))
            with Session(conn) as db:
                _, activity, active_by_integration, _ = operations_summary(db, cut)
                assert activity[integration]["pending"] == 1
                assert activity[integration]["overdue"] == 1
                assert activity[integration]["received"] == 1
                assert activity[integration]["on_time"] == 0
                assert activity[integration]["last_arrival"] is not None
                assert active_by_integration[integration] == 1
                items = attention_items(db, cut, 20, integration)
                assert [item["kind"] for item in items] == ["SOURCE_DELIVERY_ID_CONFLICT", "MISSING_FILE"]
                assert items[1]["delivery_type"] == "MISSING"
                queue = deliveries(integration_id=integration, status=None, offset=0, limit=20, session=db, sort="deadline")
                assert [row.deadline_at for row in queue] == sorted(row.deadline_at for row in queue)
            with Session(conn) as db, db.begin():
                db.get(Integration, integration).active = False
                db.add(Incident(delivery_expectation_id=expectation, incident_type=IncidentType.MISSING_FILE,
                                reason="Synthetic pending arrival"))
            assert deliver(good, "inactive") == (None, "INTEGRATION_INACTIVE")
            with Session(conn) as db:
                assert db.get(DeliveryExpectation, expectation).current_file_id == received
                assert not list(db.scalars(select(Incident.id).where(
                    Incident.delivery_expectation_id == expectation, Incident.incident_type == IncidentType.MISSING_FILE,
                    Incident.status != IncidentStatus.RESOLVED)))
            unknown, orphan = uuid4(), uuid4()
            source = work_claim_directory(unknown, orphan, root=tmp_path) / "source"
            source.mkdir(parents=True)
            (source / "unidentified.txt").write_bytes(b"unidentified synthetic package")
            worker.process(engine, tmp_path, unknown, orphan)
            with Session(conn) as db:
                assert db.get(IntakeClaim, orphan) is None
            assert (quarantine_package_directory(unknown, orphan, root=tmp_path) / "unidentified.txt").is_file()
            outer.rollback()
    finally:
        engine.dispose()
