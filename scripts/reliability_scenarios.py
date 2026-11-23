"""Process-death and transport regression checks for the disposable demo."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep


def seed(integration, mode):
    from demo_http import client

    api = client()
    if mode == "integration":
        response = api.post("/integrations", json={"name": "Reliability fixtures", "source_name": "Synthetic fault lab"})
        response.raise_for_status()
        print(response.json()["id"])
        return
    now = datetime.now(timezone.utc)
    response = api.post(f"/integrations/{integration}/delivery-expectations", json={
        "business_date": "2026-01-01", "delivery_type": mode, "expected_pattern": "data.csv",
        "deadline_at": (now + timedelta(hours=1) if mode in {"FAULT_PROCESSING", "FAULT_REPROCESS"}
                        else now - timedelta(minutes=1)).isoformat(),
    })
    response.raise_for_status()
    print(response.json()["id"])


def upload(home, delivery_type):
    directory = Path(home)
    data = b"record_id,record_date,amount,currency,reference\n1,2026-01-01,0.01,USD,fault-test\n"
    with TemporaryDirectory() as folder:
        (Path(folder) / "data.csv").write_bytes(data)
        (Path(folder) / "manifest.json").write_text(json.dumps({
            "contract_version": 1, "business_date": "2026-01-01", "delivery_type": delivery_type,
            "source_delivery_id": delivery_type, "payload": {"file_name": "data.csv", "size_bytes": len(data),
                                                                 "sha256": sha256(data).hexdigest()},
        }), encoding="utf-8")
        package = delivery_type.lower()
        stage = directory / "staging" / package
        batch = [f"mkdir {stage}", f"put data.csv {stage}/data.csv", f"put manifest.json {stage}/manifest.json",
                 f"rename {stage} {directory}/incoming/{package}"]
        subprocess.run(["sftp", "-D", "/usr/lib/openssh/sftp-server -u 0007", "-b", "-", "localhost"],
                       cwd=folder, input="\n".join(batch) + "\n", text=True, check=True)


def await_result(check, timeout=30):
    due = monotonic() + timeout
    while monotonic() < due:
        if value := check():
            return value
        sleep(0.25)
    raise AssertionError("Recovery did not converge within the test deadline")


def processing(key):
    from uuid import UUID
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from backend.app.event_worker import verified_engine
    from backend.app.intake.paths import SFTP_DATA_ROOT
    from backend.app.models import DeliveryEvent, DeliveryExpectation, File, FileStatus
    from backend.app.services.processing import process_file

    engine = verified_engine()
    key = UUID(key)
    try:
        with Session(engine) as session:
            file_id = session.get(DeliveryExpectation, key).current_file_id
        crash = """
import os, sys
from uuid import UUID
from backend.app.event_worker import verified_engine
from backend.app.intake.paths import SFTP_DATA_ROOT
from backend.app.services.processing import process_file
process_file(verified_engine(), SFTP_DATA_ROOT, UUID(sys.argv[1]), UUID(sys.argv[2]), processor=lambda *_: os._exit(73))
"""
        start = monotonic()
        assert subprocess.run([sys.executable, "-c", crash, str(key), str(file_id)], timeout=15).returncode == 73
        with Session(engine) as session:
            assert session.get(File, file_id).status == FileStatus.PROCESSING

        def recover():
            process_file(engine, SFTP_DATA_ROOT, key, file_id)
            with Session(engine) as session:
                return session.get(File, file_id).status == FileStatus.COMPLETED

        await_result(recover)
        with Session(engine) as session:
            events = list(session.scalars(select(DeliveryEvent.event_type)
                                         .where(DeliveryEvent.delivery_expectation_id == key)))
            assert events.count("FileReceived") == events.count("FileProcessingCompleted") == 1
            assert events.count("FileProcessingStarted") == 2 and events.count("FileProcessingFailed") == 1
            assert session.get(File, file_id).attempt_count_in_series == 2
        print(json.dumps({"processing_crash_to_completion_s": round(monotonic() - start, 3)}))
    finally:
        engine.dispose()


def notification(key):
    from uuid import UUID
    import httpx
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from backend.app.event_worker import verified_engine
    from backend.app.models import Incident, NotificationAttempt, NotificationJob
    from backend.app.notification_worker import dispatch, send_to_mailpit
    from backend.app.services.sla import detect_overdue

    engine = verified_engine()
    try:
        with Session(engine) as session, session.begin():
            detect_overdue(session)
            incident = session.scalar(select(Incident.id).where(Incident.delivery_expectation_id == UUID(key)))
        crash = """
import os, sys
from uuid import UUID
from backend.app.event_worker import verified_engine
from backend.app.notification_worker import dispatch, send_to_mailpit
def deliver(envelope):
    send_to_mailpit(envelope, "127.0.0.1")
    if envelope.incident_id == UUID(sys.argv[1]):
        os._exit(74)
dispatch(verified_engine(), deliver)
"""
        assert incident is not None
        start = monotonic()
        assert subprocess.run([sys.executable, "-c", crash, str(incident)], timeout=20).returncode == 74
        with Session(engine) as session:
            job = session.scalar(select(NotificationJob.id)
                                 .where(NotificationJob.incident_id == incident, NotificationJob.status == "SENDING"))
        assert job is not None

        def recover():
            dispatch(engine, lambda envelope: send_to_mailpit(envelope, "127.0.0.1"))
            with Session(engine) as session:
                return session.get(NotificationJob, job).status == "SENT"

        await_result(recover)
        with Session(engine) as session:
            attempts = list(session.scalars(select(NotificationAttempt.status).where(NotificationAttempt.job_id == job)
                                            .order_by(NotificationAttempt.number)))
            assert attempts == ["UNKNOWN", "SENT"]
            assert len(list(session.scalars(select(NotificationJob.id).where(
                NotificationJob.incident_id == incident, NotificationJob.event == "OPENED")))) == 2
        response = httpx.get("http://127.0.0.1:8025/api/v1/messages", params={"limit": 200}, timeout=5)
        response.raise_for_status()
        count = sum(message["MessageID"].strip("<>") == f"{job}@opsbridge.test"
                    for message in response.json()["messages"])
        assert count == 2
        print(json.dumps({"notification_crash_to_sent_s": round(monotonic() - start, 3), "smtp_copies": count}))
    finally:
        engine.dispose()


def reprocessing(key, *, complete):
    from uuid import UUID
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from backend.app.event_worker import verified_engine
    from backend.app.intake.paths import SFTP_DATA_ROOT
    from backend.app.models import DeliveryEvent, DeliveryExpectation, File, FileStatus, Incident
    from backend.app.services.processing import MAX_ATTEMPTS, RETRY_DELAY, Result, process_file

    engine = verified_engine()
    key = UUID(key)
    try:
        with Session(engine) as session:
            file_id = session.get(DeliveryExpectation, key).current_file_id
        if not complete:
            # Exercise the real attempt transactions with a transient storage fault.
            for attempt in range(MAX_ATTEMPTS):
                if attempt:
                    sleep(RETRY_DELAY.total_seconds())
                assert process_file(engine, SFTP_DATA_ROOT, key, file_id,
                                    processor=lambda *_: Result(error="STORAGE_UNAVAILABLE"))
            return
        assert process_file(engine, SFTP_DATA_ROOT, key, file_id)
        with Session(engine) as session:
            file = session.get(File, file_id)
            assert (file.status, file.attempt_series, file.attempt_count_in_series) == (FileStatus.COMPLETED, 2, 1)
            events = list(session.scalars(select(DeliveryEvent).where(DeliveryEvent.delivery_expectation_id == key)))
            assert sum(event.event_type == "FileProcessingFailed" for event in events) == MAX_ATTEMPTS
            requests = [event for event in events if event.event_type == "ManualReprocessingRequested"]
            assert len(requests) == 1 and requests[0].actor_type.value == "OPERATOR" and requests[0].actor_reference
            incident = session.scalar(select(Incident).where(Incident.file_id == file_id,
                                                             Incident.incident_type == "PROCESSING_FAILURE"))
            assert incident is not None and incident.status.value == "RESOLVED"
        print("Authorized browser reprocessing completed one new series and preserved the original attempts.")
    finally:
        engine.dispose()


def db_outage(pg, api, docker):
    """Reject TCP only in this freshly created container, using local-socket control."""
    from subprocess import CalledProcessError

    def psql(sql, *, tcp=False):
        args = ["-h", "127.0.0.1"] if tcp else []
        return docker("exec", "--user", "postgres", pg, "psql", "-U", "postgres", "-d", "opsbridge_test",
                      *args, "-Atq", "-v", "ON_ERROR_STOP=1", "-c", sql)

    def ready(expected):
        try:
            docker("exec", api, "python", "-c", "import httpx; "
                   f"assert httpx.get('http://127.0.0.1:8000/ready', timeout=5).status_code == {expected}")
            return True
        except CalledProcessError:
            return False

    identity = psql("SELECT current_database()")
    if identity != "opsbridge_test":
        raise AssertionError("Fault injection needs the verified disposable database")
    aggregate = """SELECT (SELECT count(*) FROM files), (SELECT count(*) FROM delivery_events),
                         (SELECT count(*) FROM outbox_events)"""
    baseline = psql(aggregate)
    assert ready(200)
    install = """set -eu
backup="$PGDATA/pg_hba.reliability.bak"
[ ! -e "$backup" ]
cp "$PGDATA/pg_hba.conf" "$backup"
{ printf 'host all all 127.0.0.1/32 reject\\n'; cat "$backup"; } > "$PGDATA/pg_hba.conf"
"""
    docker("exec", "--user", "postgres", pg, "sh", "-ec", install)
    start = monotonic()
    try:
        psql("SELECT pg_reload_conf()")
        def rejection():
            try:
                psql("SELECT 1", tcp=True)
            except CalledProcessError:
                return True
            return False
        await_result(rejection, 10)
        psql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
             "WHERE datname=current_database() AND pid <> pg_backend_pid() AND client_addr IS NOT NULL")
        await_result(lambda: ready(503), 15)
        unavailable = monotonic() - start
    finally:
        docker("exec", "--user", "postgres", pg, "sh", "-ec",
               'mv "$PGDATA/pg_hba.reliability.bak" "$PGDATA/pg_hba.conf"')
        psql("SELECT pg_reload_conf()")
    resumed = monotonic()
    await_result(lambda: ready(200), 15)
    assert psql(aggregate) == baseline
    return {"postgres_detect_unavailable_s": round(unavailable, 3),
            "postgres_restore_to_ready_s": round(monotonic() - resumed, 3)}


if __name__ == "__main__":
    mode, key, *extra = sys.argv[1:]
    if mode == "seed":
        seed(key, extra[0])
    elif mode == "upload":
        upload(key, extra[0])
    elif mode == "processing":
        processing(key)
    elif mode == "notification":
        notification(key)
    elif mode in {"prepare-reprocessing", "verify-reprocessing"}:
        reprocessing(key, complete=mode == "verify-reprocessing")
    else:
        raise SystemExit("Unknown reliability mode")
