"""Dependency probes and durable operational metrics."""

import os

import pika
from prometheus_client import Gauge, REGISTRY, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.database import get_engine
from backend.app.messaging import Broker
from backend.app.models import DeliveryEvent, Incident, IntakeClaim, NotificationAttempt, NotificationJob, OutboxEvent
from backend.app.telemetry import report

EVENTS = (
    "FileReceived", "FileValidationFailed", "SourceDeliveryIdConflict", "FileProcessingStarted",
    "FileProcessingCompleted", "FileProcessingFailed", "DeliveryOverdue",
)
DB_ERRORS = (SQLAlchemyError, ValueError, RuntimeError, OSError)
BROKER_UP = Gauge("opsbridge_broker_up", "Broker authentication probe result", ["dependency"])


def dependencies():
    states = {"database": "unavailable", "schema": "unavailable", "broker": "not_configured"}
    try:
        with get_engine().connect() as connection:
            connection.scalar(text("SELECT 1"))
            states["database"] = "ready"
            compatible = connection.scalar(text(
                "SELECT to_regclass('notification_attempts') IS NOT NULL "
                "AND to_regclass('reconciliation_runs') IS NOT NULL "
                "AND to_regclass('operator_sessions') IS NOT NULL "
                "AND to_regprocedure('opsbridge_signal_dashboard()') IS NOT NULL"
            ))
            states["schema"] = "ready" if compatible else "unavailable"
    except DB_ERRORS:
        pass
    url = os.getenv("RABBITMQ_URL")
    if url:
        states["broker"] = "unavailable"
        try:
            broker = Broker(url)
            connection = pika.BlockingConnection(broker.parameters)
            connection.close()
            states["broker"] = "ready"
        except (pika.exceptions.AMQPError, ValueError, TypeError, OSError, TimeoutError):
            pass
        BROKER_UP.labels("rabbitmq").set(int(states["broker"] == "ready"))
    return states


def metrics_snapshot():
    """Read fixed-cardinality aggregates in one bounded read transaction."""
    with get_engine().begin() as connection:
        connection.exec_driver_sql("SET LOCAL statement_timeout = '1s'")
        kind = DeliveryEvent.event_type
        events = dict(connection.execute(
            select(kind, func.count()).where(kind.in_(EVENTS)).group_by(kind)
        ).all())
        retries = connection.scalar(select(func.count()).select_from(DeliveryEvent).where(
            kind == "FileProcessingStarted", DeliveryEvent.details["attempt_count_in_series"].astext.in_(("2", "3")),
        ))
        locations = dict(connection.execute(select(IntakeClaim.final_location, func.count())
                         .where(IntakeClaim.final_location.is_not(None)).group_by(IntakeClaim.final_location)).all())
        incidents = connection.execute(select(Incident.incident_type, func.count(), func.count(Incident.resolved_at))
                                       .group_by(Incident.incident_type)).all()
        due = or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= func.now())
        state = case((OutboxEvent.failed_at.is_not(None), "failed"), (due, "due"), else_="scheduled")
        outbox = dict(connection.execute(select(state, func.count()).where(OutboxEvent.published_at.is_(None))
                                         .group_by(state)).all())
        notifications = dict(connection.execute(select(NotificationAttempt.status, func.count())
                                                .group_by(NotificationAttempt.status)).all())
        jobs = dict(connection.execute(select(NotificationJob.status, func.count())
                                       .group_by(NotificationJob.status)).all())
    return events, retries, locations, incidents, outbox, notifications, jobs


class DatabaseMetrics:
    def collect(self):
        try:
            events, retries, locations, incidents, outbox, notifications, jobs = metrics_snapshot()
        except DB_ERRORS:
            yield GaugeMetricFamily("opsbridge_database_up", "Database metrics query succeeded", value=0)
            report("DATABASE_METRICS_UNAVAILABLE")
            return
        yield GaugeMetricFamily("opsbridge_database_up", "Database metrics query succeeded", value=1)
        counts = CounterMetricFamily("opsbridge_delivery_events", "Persisted operational events by kind", labels=["event"])
        for kind in EVENTS:
            counts.add_metric([kind], events.get(kind, 0))
        yield counts
        yield CounterMetricFamily("opsbridge_processing_retries", "Persisted automatic retry starts", value=retries)
        claims = CounterMetricFamily("opsbridge_intake_finalized", "Finalized intake claims", labels=["location"])
        for location in ("ACCEPTED", "QUARANTINE"):
            claims.add_metric([location], locations.get(location, 0))
        yield claims
        opened = CounterMetricFamily("opsbridge_incidents_opened", "Persisted incident creations", labels=["type"])
        resolved = CounterMetricFamily("opsbridge_incidents_resolved", "Persisted incident resolutions", labels=["type"])
        for kind, created, closed in incidents:
            opened.add_metric([kind.value], created)
            resolved.add_metric([kind.value], closed)
        yield opened
        yield resolved
        backlog = GaugeMetricFamily("opsbridge_outbox_backlog", "Unpublished outbox rows by eligibility", labels=["state"])
        for state in ("due", "scheduled", "failed"):
            backlog.add_metric([state], outbox.get(state, 0))
        yield backlog
        attempts = CounterMetricFamily("opsbridge_notification_attempts", "Persisted notification attempts by terminal outcome",
                                       labels=["outcome"])
        for state in ("SENT", "FAILED", "UNKNOWN"):
            attempts.add_metric([state], notifications.get(state, 0))
        yield attempts
        yield CounterMetricFamily("opsbridge_notification_attempts_started", "Total attempts recorded",
                                  value=sum(notifications.values()))
        pending = GaugeMetricFamily("opsbridge_notification_jobs", "Notification jobs by status", labels=["state"])
        for state in ("PENDING", "SENDING", "SENT", "FAILED", "CANCELLED"):
            pending.add_metric([state], jobs.get(state, 0))
        yield pending


def api_metrics():
    return generate_latest(REGISTRY) + generate_latest(DatabaseMetrics())
