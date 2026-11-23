"""Exercise transactional notification and acknowledgement state on isolated PostgreSQL."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import notification_worker as worker
from backend.app.event_worker import verified_engine
from backend.app.models import (
    DeliveryExpectation, Incident, IncidentAcknowledgement, IncidentStatus, IncidentType,
    Integration, NotificationAttempt, NotificationJob,
)
from backend.app.services.incident_notifications import acknowledge_incident, open_incident, resolve_incident


@pytest.fixture
def isolated(monkeypatch):
    if os.getenv("OPSBRIDGE_RUN_INTEGRATION") != "1":
        pytest.skip("Explicit integration opt-in required")
    from backend.app.config import DATABASE_URL_FROM_PROCESS

    if not DATABASE_URL_FROM_PROCESS:
        pytest.fail("Explicit local opsbridge_test connection required")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL_FROM_PROCESS)
    monkeypatch.setenv("OPSBRIDGE_EXPECTED_DATABASE", "opsbridge_test")
    engine = verified_engine()
    try:
        with engine.connect() as connection, connection.begin() as outer:
            @contextmanager
            def hold(*_args, **_kwargs):
                yield connection

            monkeypatch.setattr(worker, "lifecycle", hold)
            yield connection
            outer.rollback()
    finally:
        engine.dispose()


def seed(session, now):
    integration = Integration(name="Notification test " + str(uuid4()), source_name="Test")
    session.add(integration)
    session.flush()
    delivery = DeliveryExpectation(integration_id=integration.id, business_date=date(2026, 1, 1),
                                   delivery_type="TEST_NOTICE", expected_pattern="*.csv",
                                   deadline_at=now - timedelta(seconds=1))
    session.add(delivery)
    session.flush()
    return delivery


def test_escalation_timing_ack_and_resolution_history(isolated):
    now = datetime.now(timezone.utc)
    with Session(isolated) as session, session.begin():
        delivery = seed(session, now)
        incident = open_incident(session, delivery, IncidentType.MISSING_FILE, now, reason="Synthetic overdue delivery")
        incident_id, delivery_id = incident.id, delivery.id
    sent = []
    assert worker.dispatch(isolated, sent.append, now=now + timedelta(seconds=119)) == 2
    assert all(envelope.event == "OPENED" for envelope in sent)
    assert worker.dispatch(isolated, sent.append, now=now + timedelta(seconds=120)) == 1
    assert sent[-1].level == 1
    assert worker.dispatch(isolated, sent.append, now=now + timedelta(seconds=120)) == 0
    with Session(isolated) as session, session.begin():
        assert acknowledge_incident(session, incident_id, now + timedelta(seconds=150),
                                    operator="local-demo-operator", comment="Reviewing")
        assert acknowledge_incident(session, incident_id, now + timedelta(seconds=152),
                                    operator="local-demo-operator", comment=None) is None
    with Session(isolated) as session, session.begin():
        incident = session.get(Incident, incident_id, with_for_update=True)
        delivery = session.get(DeliveryExpectation, delivery_id)
        assert resolve_incident(session, delivery, incident, now + timedelta(seconds=160), "Synthetic arrival")
        assert not resolve_incident(session, delivery, incident, now + timedelta(seconds=161), "Duplicate")
    assert worker.dispatch(isolated, sent.append, now=now + timedelta(seconds=301)) == 1
    assert sent[-1].event == "RESOLVED" and sent[-1].incident_id == incident_id
    with Session(isolated) as session:
        audit = session.get(IncidentAcknowledgement, incident_id)
        assert (audit.operator, audit.comment) == ("local-demo-operator", "Reviewing")
        assert session.get(Incident, incident_id).status == IncidentStatus.RESOLVED
        jobs = list(session.scalars(select(NotificationJob).where(NotificationJob.incident_id == incident_id)))
        assert len(jobs) == 5
        assert next(job for job in jobs if job.level == 2).status == "CANCELLED"


def test_restart_and_retry_exhaustion_keep_attempt_history(isolated, monkeypatch):
    monkeypatch.setenv("OPSBRIDGE_NOTIFICATION_POLICIES",
                       '[{"opened":[{"owner":"Demo","email":"demo@opsbridge.test"}]}]')
    now = datetime.now(timezone.utc)
    with Session(isolated) as session, session.begin():
        incident = open_incident(session, seed(session, now), IncidentType.MISSING_FILE, now, reason="Synthetic")
        incident_id = incident.id

    def crash(_):
        raise RuntimeError("Synthetic interruption")

    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        worker.dispatch(isolated, crash, now=now)
    assert worker.dispatch(isolated, crash, now=now) == 0  # Recover STARTED, then wait.

    def unavailable(_):
        raise ConnectionRefusedError

    assert worker.dispatch(isolated, unavailable, now=now + timedelta(seconds=4)) == 0
    assert worker.dispatch(isolated, unavailable, now=now + timedelta(seconds=5)) == 1
    assert worker.dispatch(isolated, unavailable, now=now + timedelta(seconds=24)) == 0
    assert worker.dispatch(isolated, unavailable, now=now + timedelta(seconds=25)) == 1
    assert worker.dispatch(isolated, unavailable, now=now + timedelta(seconds=300)) == 0
    with Session(isolated) as session:
        job = session.scalar(select(NotificationJob).where(NotificationJob.incident_id == incident_id))
        assert job.status == "FAILED" and job.attempt_count == 3
        attempts = session.scalars(select(NotificationAttempt).where(NotificationAttempt.job_id == job.id)
                                   .order_by(NotificationAttempt.number))
        assert [row.status for row in attempts] == ["UNKNOWN", "FAILED", "FAILED"]


def test_notification_insert_rolls_back_with_incident(isolated):
    now = datetime.now(timezone.utc)
    with Session(isolated, join_transaction_mode="create_savepoint") as session:
        with pytest.raises(RuntimeError):
            with session.begin():
                incident = open_incident(session, seed(session, now), IncidentType.MISSING_FILE, now, reason="Synthetic")
                incident_id = incident.id
                raise RuntimeError("Synthetic rollback")
    with Session(isolated) as session:
        assert session.get(Incident, incident_id) is None
        assert session.scalar(select(NotificationJob.id).where(NotificationJob.incident_id == incident_id)) is None
