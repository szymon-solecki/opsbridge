"""Dispatch durable incident emails to the isolated local Mailpit sink."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import logging
import os
import signal
import smtplib
from threading import Event
from time import monotonic
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.event_worker import verified_engine
from backend.app.intake.worker import lifecycle
from backend.app.models import Incident, IncidentStatus, NotificationAttempt, NotificationJob
from backend.app.services.notification_policy import synthetic_address
from backend.app.telemetry import READY, outcome, report, start_worker, timed
MAX_ATTEMPTS = 3
BACKOFF = (5, 20)


@dataclass(frozen=True)
class Envelope:
    job_id: UUID
    incident_id: UUID
    recipient: str
    event: str
    severity: str
    level: int


def send_to_mailpit(envelope: Envelope, host: str):
    if host not in ("mailpit", "127.0.0.1"):
        raise ValueError("Only the local Mailpit sink is supported")
    address = synthetic_address(envelope.recipient)
    message = EmailMessage()
    message["From"] = "notifications@opsbridge.test"
    message["To"] = address
    message["Subject"] = f"OpsBridge [{envelope.severity}] {envelope.event}" + (
        f" L{envelope.level}" if envelope.level else ""
    )
    message["Message-ID"] = f"<{envelope.job_id}@opsbridge.test>"
    message.set_content(f"Incident {envelope.incident_id}\nEvent: {envelope.event}\n"
                        "Use the local Operations Center to review this incident.\n")
    smtp = smtplib.SMTP(host, 1025, timeout=5)
    try:
        smtp.send_message(message, to_addrs=[address])
    finally:
        smtp.close()


def _error_code(exc):
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = [detail[0] for detail in exc.recipients.values()]
        return ("SMTP_RECIPIENT_REJECTED", True) if codes and all(500 <= code < 600 for code in codes) else (
            "SMTP_RECIPIENT_TEMPORARY", False
        )
    if isinstance(exc, smtplib.SMTPResponseException):
        return "SMTP_RESPONSE_ERROR", 500 <= exc.smtp_code < 600
    if isinstance(exc, ValueError):
        return "INVALID_LOCAL_ENVELOPE", True
    return "SMTP_UNAVAILABLE", False


def _update_outcome(job, attempt, incident, now, code, permanent):
    attempt.finished_at = now
    attempt.error_code = code
    job.last_error = code
    if code is None:
        job.status = "SENT"
    elif job.event == "ESCALATED" and incident.status != IncidentStatus.OPEN:
        job.status = "CANCELLED"
    elif permanent or job.attempt_count >= MAX_ATTEMPTS:
        job.status = "FAILED"
    else:
        job.status = "PENDING"
        job.next_attempt_at = now + timedelta(seconds=BACKOFF[job.attempt_count - 1])
        return
    job.finished_at = now


def _claim(session, job_id, now):
    # Use the lifecycle service's lock order and release the database row locks
    # before making the network call. An acknowledgement may cancel queued work
    # while an already-started SMTP attempt finishes.
    incident_id = session.scalar(select(NotificationJob.incident_id).where(NotificationJob.id == job_id))
    if incident_id is None:
        return None
    incident = session.get(Incident, incident_id, with_for_update=True)
    job = session.get(NotificationJob, job_id, with_for_update=True)
    if job.status not in ("PENDING", "SENDING") or job.next_attempt_at > now:
        return None
    if job.status == "SENDING":
        attempt = session.get(NotificationAttempt, (job_id, job.attempt_count))
        attempt.status = "UNKNOWN"
        _update_outcome(job, attempt, incident, now, "OUTCOME_UNKNOWN", False)
        return None
    if job.event == "ESCALATED":
        if incident.status != IncidentStatus.OPEN:
            job.status, job.finished_at = "CANCELLED", now
            return None
        earlier = select(NotificationJob.id).where(
            NotificationJob.incident_id == incident_id, NotificationJob.event == "ESCALATED",
            NotificationJob.level < job.level, NotificationJob.status.in_(("PENDING", "SENDING")),
        ).exists()
        if session.scalar(select(earlier)):
            return None
    job.status = "SENDING"
    job.attempt_count += 1
    session.add(NotificationAttempt(job_id=job.id, number=job.attempt_count, status="STARTED", started_at=now))
    return Envelope(job.id, incident_id, job.recipient, job.event, job.severity, job.level)


@timed("notification_dispatch")
def dispatch(engine, sender, *, now=None, limit=100):
    clock = (lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))
    with Session(engine) as session:
        # Exclude blocked levels while scanning so a large batch cannot crowd
        # out earlier attempts, other incidents, or resolution messages.
        earlier = NotificationJob.__table__.alias("earlier")
        blocked = select(earlier.c.id).where(
            earlier.c.incident_id == NotificationJob.incident_id, earlier.c.event == "ESCALATED",
            earlier.c.level < NotificationJob.level, earlier.c.status.in_(("PENDING", "SENDING")),
        ).exists()
        job_ids = list(session.scalars(select(NotificationJob.id).where(
            NotificationJob.status.in_(("PENDING", "SENDING")), NotificationJob.next_attempt_at <= clock(),
            (NotificationJob.event != "ESCALATED") | (NotificationJob.status == "SENDING") | ~blocked,
        ).order_by(NotificationJob.next_attempt_at, NotificationJob.id).limit(limit)))
    processed = 0
    for job_id in job_ids:
        with lifecycle(engine, job_id, namespace="notifications:job") as connection:
            if connection is None:
                continue
            with Session(connection) as session:
                with session.begin():
                    envelope = _claim(session, job_id, clock())
                if envelope is None:
                    continue
                try:
                    sender(envelope)
                except (smtplib.SMTPException, OSError, ValueError) as exc:
                    code, permanent = _error_code(exc)
                else:
                    code, permanent = None, False
                with session.begin():
                    incident = session.get(Incident, envelope.incident_id, with_for_update=True)
                    job = session.get(NotificationJob, job_id, with_for_update=True)
                    attempt = session.get(NotificationAttempt, (job_id, job.attempt_count))
                    attempt.status = "FAILED" if code else "SENT"
                    _update_outcome(job, attempt, incident, clock(), code, permanent)
                outcome("notification_dispatch", "failed" if code else "sent")
                report(code or "NOTIFICATION_SENT", level=logging.WARNING if code else logging.INFO,
                       job_id=job_id, incident_id=envelope.incident_id)
                processed += 1
    return processed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    start_worker("notification-worker")
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    host = os.environ.get("OPSBRIDGE_MAILPIT_HOST", "mailpit")
    if host not in ("mailpit", "127.0.0.1"):
        raise SystemExit("Only the local Mailpit sink is supported")
    engine = None
    try:
        engine = verified_engine()
        last_probe = float("-inf")
        mail_ready = False
        while not stop.is_set():
            dispatch(engine, lambda envelope: send_to_mailpit(envelope, host))
            if not args.once and monotonic() - last_probe >= 5:
                try:
                    with smtplib.SMTP(host, 1025, timeout=3) as smtp:
                        mail_ready = smtp.noop()[0] == 250
                except (smtplib.SMTPException, OSError):
                    mail_ready = False
                last_probe = monotonic()
            READY.labels("notification-worker").set(int(mail_ready))
            if args.once:
                return 0
            stop.wait(1)
    except Exception:
        report("NOTIFICATION_WORKER_STOPPED", level=logging.ERROR)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
