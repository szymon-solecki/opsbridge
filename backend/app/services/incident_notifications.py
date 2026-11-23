"""Incident lifecycle changes and notification requests share a transaction."""

from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.app.models import Incident, IncidentAcknowledgement, IncidentStatus, NotificationJob
from backend.app.services.notification_policy import SEVERITY, policies, select_recipients, unique_recipients
from backend.app.telemetry import report


def _enqueue(session, incident, event, level, deadline, recipients):
    rows = [
        dict(incident_id=incident.id, event=event, level=level, severity=SEVERITY[incident.incident_type],
             owner=recipient.owner, recipient=recipient.email, status="PENDING", scheduled_at=deadline,
             next_attempt_at=deadline, attempt_count=0)
        for recipient in unique_recipients(recipients)
    ]
    if rows:
        session.execute(insert(NotificationJob).values(rows).on_conflict_do_nothing(
            constraint="uq_notification_job_identity"
        ))


def _rule_depth(session, incident, delivery, field):
    return select_recipients(policies(session), delivery.integration_id, incident.incident_type,
                             SEVERITY[incident.incident_type], field)


def open_incident(session: Session, delivery, kind, now, *, reason, file_id=None, conflict_key=None,
                  reconciliation_run_id=None):
    incident = Incident(delivery_expectation_id=delivery.id, incident_type=kind, opened_at=now,
                        reason=reason, file_id=file_id, conflict_key=conflict_key,
                        reconciliation_run_id=reconciliation_run_id)
    session.add(incident)
    session.flush()
    _enqueue(session, incident, "OPENED", 0, now, _rule_depth(session, incident, delivery, "opened"))
    for level, step in enumerate(_rule_depth(session, incident, delivery, "escalations"), 1):
        _enqueue(session, incident, "ESCALATED", level, now + timedelta(seconds=step.after_seconds), step.recipients)
    report("INCIDENT_OPEN_STAGED", integration_id=delivery.integration_id, delivery_expectation_id=delivery.id,
           incident_id=incident.id, file_id=file_id)
    return incident


def _cancel_escalations(session, incident, now):
    session.execute(update(NotificationJob).where(
        NotificationJob.incident_id == incident.id, NotificationJob.event == "ESCALATED",
        NotificationJob.status == "PENDING",
    ).values(status="CANCELLED", finished_at=now))


def resolve_incident(session: Session, delivery, incident, now, reason):
    """Called with the incident row locked by intake or processing."""
    if incident.status == IncidentStatus.RESOLVED:
        return False
    incident.status = IncidentStatus.RESOLVED
    incident.resolved_at = now
    incident.resolution_reason = reason
    _cancel_escalations(session, incident, now)
    _enqueue(session, incident, "RESOLVED", 0, now, _rule_depth(session, incident, delivery, "resolved"))
    report("INCIDENT_RESOLUTION_STAGED", integration_id=delivery.integration_id, delivery_expectation_id=delivery.id,
           incident_id=incident.id, file_id=incident.file_id)
    return True


def acknowledge_incident(session: Session, incident_id, now, *, operator, comment):
    incident = session.get(Incident, incident_id, with_for_update=True)
    if incident is None or incident.status != IncidentStatus.OPEN:
        return None
    incident.status = IncidentStatus.ACKNOWLEDGED
    incident.acknowledged_at = now
    audit = IncidentAcknowledgement(incident_id=incident_id, operator=operator, acknowledged_at=now, comment=comment)
    session.add(audit)
    _cancel_escalations(session, incident, now)
    report("INCIDENT_ACKNOWLEDGEMENT_STAGED", incident_id=incident.id,
           delivery_expectation_id=incident.delivery_expectation_id, file_id=incident.file_id)
    return audit
