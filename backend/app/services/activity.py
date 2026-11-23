"""Project authoritative delivery events without trusting message content."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.app.models import ActivityFeed, DeliveryEvent, DeliveryExpectation, File, InboxEvent, OutboxEvent


SUMMARIES = {
    "DeliveryExpectationCreated": "Delivery expectation created",
    "DeliveryOverdue": "Delivery deadline passed without a recorded arrival",
    "FileReceived": "Intake accepted a file",
    "FileValidationFailed": "Intake recorded a validation failure",
    "SourceDeliveryIdConflict": "Intake quarantined a source delivery ID conflict",
    "FileProcessingStarted": "Processing attempt started",
    "FileProcessingCompleted": "Processing completed",
    "FileProcessingFailed": "Processing attempt failed",
    "ManualReprocessingRequested": "Operator requested a new attempt series",
    "ReconciliationQueued": "Reconciliation run queued",
    "ReconciliationStarted": "Reconciliation attempt started",
    "ReconciliationSourceMissing": "Reconciliation source missed its arrival deadline",
    "ReconciliationRetryScheduled": "Reconciliation retry scheduled",
    "ReconciliationCompleted": "Reconciliation results committed",
    "ReconciliationFailed": "Reconciliation exhausted execution attempts",
}
DETAILS = (
    "status", "error_code", "failure_reason", "attempt_series", "attempt_count_in_series",
    "next_retry_at", "deadline_at", "record_count", "debit_count", "credit_count", "zero_count",
    "existing_file_id", "reconciliation_run_id", "reconciliation_attempt", "exception_count",
)
PROJECTION_LOCK = 104857601


class UnknownPublication(ValueError):
    """A broker envelope does not identify an authoritative outbox publication."""


def _source():
    return (
        select(DeliveryEvent, DeliveryExpectation.integration_id, File.original_name, File.replaces_file_id)
        .join(DeliveryExpectation, DeliveryExpectation.id == DeliveryEvent.delivery_expectation_id)
        .outerjoin(File, File.id == DeliveryEvent.file_id)
    )


def _project(session, row):
    event, integration_id, filename, predecessor = row
    details = event.details if isinstance(event.details, dict) else {}
    payload = {key: details[key] for key in DETAILS
               if key in details and type(details[key]) in (str, int)}
    payload.update(integration_id=str(integration_id), file_id=str(event.file_id) if event.file_id else None,
                   filename=filename, replaces_file_id=str(predecessor) if predecessor else None)
    if event.event_type == "ManualReprocessingRequested":
        payload["actor_reference"] = event.actor_reference
    statement = insert(ActivityFeed).values(
        source_event_id=event.id, delivery_expectation_id=event.delivery_expectation_id,
        event_type=event.event_type, summary=SUMMARIES.get(event.event_type, "Delivery event recorded"),
        payload=payload, occurred_at=event.occurred_at,
    )
    session.execute(statement.on_conflict_do_update(
        index_elements=[ActivityFeed.source_event_id],
        set_={key: statement.excluded[key] for key in ("event_type", "summary", "payload", "occurred_at")},
    ))


def apply_publication(session: Session, event_id: UUID, event_type: str) -> bool:
    """The caller commits both writes before acknowledging RabbitMQ."""
    session.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": PROJECTION_LOCK})
    row = session.execute(
        _source().join(OutboxEvent, OutboxEvent.event_id == DeliveryEvent.id)
        .where(DeliveryEvent.id == event_id, OutboxEvent.event_type == event_type)
    ).one_or_none()
    if row is None:
        raise UnknownPublication("Publication does not match the outbox")
    claim = insert(InboxEvent).values(
        event_id=event_id, event_type=event_type, processed_at=datetime.now(timezone.utc), outcome="PROJECTED",
    ).on_conflict_do_nothing(index_elements=[InboxEvent.event_id]).returning(InboxEvent.event_id)
    if session.scalar(claim) is None:
        return False
    _project(session, row)
    return True


def rebuild_activity(session: Session) -> int:
    """Atomically refresh every authoritative projection, including missing rows."""
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PROJECTION_LOCK})
    count = 0
    for row in session.execute(_source().order_by(DeliveryEvent.id).execution_options(yield_per=200)):
        _project(session, row)
        count += 1
    return count
