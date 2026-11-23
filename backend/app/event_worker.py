"""Run the outbox publisher, activity consumer, or projection rebuild."""

import argparse
from datetime import datetime, timedelta, timezone
import logging
import os
import signal
from threading import Event
from time import monotonic

import pika
from sqlalchemy import create_engine, or_, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from backend.app.messaging import Broker, Publication, QUEUE
from backend.app.models import OutboxEvent
from backend.app.services.activity import UnknownPublication, apply_publication, rebuild_activity
from backend.app.telemetry import READY, outcome, report, start_worker, timed


TRANSPORT_ERRORS = (pika.exceptions.AMQPError, OSError, TimeoutError)
CONSUMER_ATTEMPTS = 3
RETRY_SECONDS = 2


@timed("outbox_publish")
def publish_one(engine, broker, *, after_confirm=None, clock=None):
    """Hold one row lock until the broker confirms and PostgreSQL commits."""
    clock = clock or (lambda: datetime.now(timezone.utc))
    with Session(engine) as session, session.begin():
        now = clock()
        row = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.published_at.is_(None), OutboxEvent.failed_at.is_(None),
                or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now),
            ).order_by(OutboxEvent.created_at, OutboxEvent.id).limit(1).with_for_update(skip_locked=True)
        )
        if row is None:
            return False
        event_id = row.event_id
        context = row.payload if isinstance(row.payload, dict) else {}
        fields = {key: context.get(key) for key in ("request_id", "integration_id", "delivery_expectation_id", "file_id")}
        row.publication_attempts += 1
        row.last_attempt_at = now
        if not row.event_type.strip():
            row.failed_at = now
            row.next_attempt_at = None
            row.last_error = "INVALID_EVENT_TYPE"
            result = "failed"
        else:
            try:
                broker.publish(Publication(row.event_id, row.event_type))
            except TRANSPORT_ERRORS as exc:
                row.next_attempt_at = clock() + timedelta(seconds=min(60, 2 ** min(row.publication_attempts, 6)))
                row.last_error = type(exc).__name__
                broker.close()
                result = "retry"
            else:
                if after_confirm is not None:
                    after_confirm()
                row.published_at = clock()
                row.next_attempt_at = row.last_error = None
                result = "published"
    outcome("outbox_publish", result)
    report({"failed": "INVALID_EVENT_TYPE", "retry": "OUTBOX_RETRY", "published": "OUTBOX_PUBLISHED"}[result],
           level=logging.INFO if result == "published" else logging.WARNING, event_id=event_id, **fields)
    return True


@timed("activity_consume")
def handle_message(engine, channel, method, properties, body, *, wait, after_commit=None):
    """Acknowledge only after commit. Broker delivery counts survive restarts."""
    publication = None
    try:
        publication = Publication.decode(body, properties)
        with Session(engine) as session, session.begin():
            projected = apply_publication(session, publication.event_id, publication.event_type)
    except (ValueError, RecursionError, UnknownPublication):
        channel.basic_reject(method.delivery_tag, requeue=False)
        outcome("activity_consume", "dead_letter")
        report("PUBLICATION_REJECTED", level=logging.WARNING,
               event_id=publication.event_id if publication else None)
        return
    except SQLAlchemyError:
        count = (properties.headers or {}).get("x-delivery-count", 0)
        valid_count = isinstance(count, int) and not isinstance(count, bool)
        retry = valid_count and 0 <= count < CONSUMER_ATTEMPTS - 1
        if retry:
            wait(RETRY_SECONDS)
        channel.basic_reject(method.delivery_tag, requeue=retry)
        outcome("activity_consume", "retry" if retry else "dead_letter")
        report("PROJECTION_RETRY" if retry else "PROJECTION_REJECTED", level=logging.WARNING,
               event_id=publication.event_id if publication else None)
        return
    if after_commit is not None:
        after_commit()
    channel.basic_ack(method.delivery_tag)
    outcome("activity_consume", "projected" if projected else "duplicate")
    report("PUBLICATION_PROJECTED" if projected else "PUBLICATION_DUPLICATE", event_id=publication.event_id)


def consume_one(engine, broker, *, after_commit=None):
    channel = broker.open()
    method, properties, body = channel.basic_get(QUEUE, auto_ack=False)
    if method is None:
        return False
    handle_message(engine, channel, method, properties, body, wait=broker.connection.sleep, after_commit=after_commit)
    return True


def verified_engine(*, reuse_connection=False):
    url = make_url(os.environ["DATABASE_URL"])
    if (os.getenv("OPSBRIDGE_EXPECTED_DATABASE") != "opsbridge_test"
            or url.database != "opsbridge_test" or url.host not in {"localhost", "127.0.0.1", "postgres"}
            or url.query or url.drivername not in {"postgresql", "postgresql+psycopg"}):
        raise ValueError("Event workers require an isolated local opsbridge_test target")
    # The publisher and consumer are single-threaded. Return their connection
    # after each transaction; verify it again at checkout after an outage.
    pool = {"pool_size": 1, "max_overflow": 0, "pool_pre_ping": True} if reuse_connection else {"poolclass": NullPool}
    engine = create_engine(url.set(drivername="postgresql+psycopg"), hide_parameters=True, **pool)
    try:
        with engine.connect() as connection:
            if connection.scalar(text("SELECT current_database()")) != "opsbridge_test":
                raise ValueError("Unexpected database")
    except Exception:
        engine.dispose()
        raise
    return engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("publish", "consume", "rebuild"))
    parser.add_argument("--once", action="store_true", help="Process one row or message")
    args = parser.parse_args()
    worker = {"publish": "outbox-publisher", "consume": "activity-consumer", "rebuild": "activity-rebuild"}[args.mode]
    start_worker(worker)
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    engine = broker = None
    try:
        engine = verified_engine(reuse_connection=args.mode in {"publish", "consume"})
        if args.mode == "rebuild":
            with Session(engine) as session, session.begin():
                rebuild_activity(session)
            report("ACTIVITY_REBUILT")
            return 0
        broker = Broker(os.environ["RABBITMQ_URL"])
        if broker.parameters.host not in {"localhost", "127.0.0.1", "rabbitmq"}:
            raise ValueError("Event workers require a local broker")
        step = publish_one if args.mode == "publish" else consume_one
        last_probe = float("-inf")
        while not stop.is_set():
            try:
                did_work = step(engine, broker)
                if not args.once and monotonic() - last_probe >= 5:
                    broker.open()
                    with engine.connect() as connection:
                        connection.scalar(text("SELECT 1"))
                    last_probe = monotonic()
                READY.labels(worker).set(int(broker.connection is not None and broker.connection.is_open))
                if args.once:
                    return 0
                if not did_work and not broker.service(0.5):
                    stop.wait(0.5)
            except TRANSPORT_ERRORS + (SQLAlchemyError,):
                READY.labels(worker).set(0)
                report("EVENT_LOOP_RETRY", level=logging.WARNING)
                broker.close()
                if args.once:
                    return 1
                stop.wait(2)
    except Exception:
        report("EVENT_WORKER_STOPPED", level=logging.ERROR)
        return 1
    finally:
        if broker is not None:
            broker.close()
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
