"""Persist first detection of a missing delivery without changing its status."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import DeliveryExpectation as Delivery
from backend.app.models import File, Incident, IncidentType, IntakeClaim, IntakeClaimStatus
from backend.app.services.audit import record_event
from backend.app.services.incident_notifications import open_incident
from backend.app.services.operations import ACTIVE
from backend.app.telemetry import report, timed


def recorded_arrival(delivery_id):
    return (
        select(File.id).where(File.delivery_expectation_id == delivery_id).exists()
        | select(IntakeClaim.id).where(
            IntakeClaim.delivery_expectation_id == delivery_id,
            IntakeClaim.status.in_((IntakeClaimStatus.COMMITTED, IntakeClaimStatus.FINALIZED)),
        ).exists()
    )


@timed("sla_scan")
def detect_overdue(session: Session, now: datetime | None = None, *, limit: int = 100) -> int:
    """Use the caller's transaction. Intake takes the same expectation row lock."""
    horizon = now if now is not None else datetime.now(timezone.utc)
    candidates = list(session.scalars(
        select(Delivery).where(Delivery.overdue_at.is_(None), Delivery.deadline_at < horizon,
                               ~recorded_arrival(Delivery.id))
        .order_by(Delivery.deadline_at, Delivery.id).limit(limit).with_for_update(skip_locked=True)
    ))
    detected = 0
    for delivery in candidates:
        # A fresh statement after acquiring the lock observes intake commits,
        # including identifiable arrivals without a File row.
        if session.scalar(select(recorded_arrival(delivery.id))):
            continue
        at = now if now is not None else datetime.now(timezone.utc)
        delivery.overdue_at = at
        incident = session.scalar(select(Incident).where(
            Incident.delivery_expectation_id == delivery.id,
            Incident.incident_type == IncidentType.MISSING_FILE, Incident.status.in_(ACTIVE),
        ))
        if incident is None:
            open_incident(session, delivery, IncidentType.MISSING_FILE, at,
                          reason="Delivery deadline passed without an identifiable arrival.")
        record_event(session, delivery, "DeliveryOverdue", at, actor="opsbridge-sla",
                     deadline_at=delivery.deadline_at.isoformat())
        report("SLA_BREACH_DETECTED", integration_id=delivery.integration_id, delivery_expectation_id=delivery.id)
        detected += 1
    return detected
