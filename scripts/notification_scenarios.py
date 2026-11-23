"""Verify notifications with real SMTP inside the disposable demo namespace."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import partial
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from demo_http import client
from backend.app.event_worker import verified_engine
from backend.app.models import DeliveryExpectation, Incident, IncidentStatus, NotificationJob
from backend.app.notification_worker import dispatch, send_to_mailpit
from backend.app.services.incident_notifications import resolve_incident
from backend.app.services.sla import detect_overdue


API = "http://127.0.0.1:8000"
MAILPIT = "http://127.0.0.1:8025"


def wait_for_mailpit(http):
    end = time.monotonic() + 25
    while time.monotonic() < end:
        try:
            if http.get(MAILPIT + "/api/v1/messages").is_success:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.25)
    raise RuntimeError("Disposable Mailpit API did not become ready")


def main(engine):
    http = httpx.Client(timeout=6)
    wait_for_mailpit(http)
    api = client()
    now = datetime.now(timezone.utc)
    integration = next(row for row in api.get("/integrations").json() if row["name"] == "Demo")
    deliveries = {}
    for kind in ("NOTIFY_ACK", "NOTIFY_RESOLVE"):
        response = api.post(f"/integrations/{integration['id']}/delivery-expectations", json={
            "delivery_type": kind, "business_date": "2026-01-01", "expected_pattern": "*.csv",
            "deadline_at": (now - timedelta(minutes=1)).isoformat(),
        })
        response.raise_for_status()
        deliveries[kind] = response.json()["id"]
    with Session(engine) as session, session.begin():
        detect_overdue(session, now)
        for kind, delivery_id in list(deliveries.items()):
            deliveries[kind] = session.scalar(select(Incident.id).where(Incident.delivery_expectation_id == delivery_id))
    send = partial(send_to_mailpit, host="127.0.0.1")
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(dispatch, engine, send, now=now) for _ in range(2)]
        for task in tasks:
            task.result(timeout=30)
    ack_id, resolve_id = deliveries.values()
    with Session(engine) as session:
        for incident_id in (ack_id, resolve_id):
            jobs = list(session.scalars(select(NotificationJob).where(NotificationJob.incident_id == incident_id)))
            assert sorted(job.status for job in jobs) == ["PENDING", "PENDING", "SENT", "SENT"]
    dispatch(engine, send, now=now + timedelta(seconds=120))
    endpoint = f"/dashboard/incidents/{ack_id}/acknowledge"
    assert api.post(endpoint, json={"comment": "Missing CSRF token"},
                    headers={"X-CSRF-Token": ""}).status_code == 403
    acknowledged = api.post(endpoint, json={"comment": "Investigating synthetic delivery"})
    acknowledged.raise_for_status()
    assert acknowledged.json()["operator"] == api.principal["id"]
    with Session(engine) as session, session.begin():
        incident = session.get(Incident, resolve_id, with_for_update=True)
        delivery = session.get(DeliveryExpectation, incident.delivery_expectation_id)
        resolve_incident(session, delivery, incident, datetime.now(timezone.utc), "Synthetic resolution verification.")
    dispatch(engine, send, now=now + timedelta(seconds=999))
    messages = http.get(MAILPIT + "/api/v1/messages", params={"limit": 200}).json()["messages"]
    ids = [message["MessageID"].strip("<>") for message in messages]
    with Session(engine) as session:
        for incident_id, count in ((ack_id, 3), (resolve_id, 4)):
            jobs = list(session.scalars(select(NotificationJob).where(NotificationJob.incident_id == incident_id)))
            assert len([job for job in jobs if job.status == "SENT"]) == count
            assert next(job for job in jobs if job.level == 2).status == "CANCELLED"
            for job in jobs:
                assert ids.count(f"{job.id}@opsbridge.test") == int(job.status == "SENT")
        assert session.get(Incident, ack_id).status == IncidentStatus.ACKNOWLEDGED
        assert session.get(Incident, resolve_id).status == IncidentStatus.RESOLVED
    # Leave a fresh open incident for the operator or the live browser test.
    api.post(f"/integrations/{integration['id']}/delivery-expectations", json={
        "delivery_type": "NOTIFY_BROWSER", "business_date": "2026-01-01", "expected_pattern": "*.csv",
        "deadline_at": (now - timedelta(seconds=5)).isoformat(),
    }).raise_for_status()
    with Session(engine) as session, session.begin():
        detect_overdue(session)
    dispatch(engine, send)
    print("Mailpit captured each expected message once in the concurrent run. Acknowledgement and resolution cancelled level two.", flush=True)


if __name__ == "__main__":
    target = verified_engine()
    try:
        main(target)
    finally:
        target.dispose()
