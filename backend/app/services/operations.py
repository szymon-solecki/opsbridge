"""Operational read models derived from delivery, intake and incident records."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import String, case, cast, func, literal, select, union_all
from sqlalchemy.orm import Session

from backend.app.models import DeliveryExpectation as Delivery
from backend.app.models import DeliveryStatus, File, Incident, IncidentStatus, IntakeClaim, IntakeClaimStatus


FAILURES = (DeliveryStatus.VALIDATION_FAILED, DeliveryStatus.PROCESSING_FAILED)
ACTIVE = (IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED)
PRIORITY = {
    "RECONCILIATION_FAILURE": 4,
    "SOURCE_DELIVERY_ID_CONFLICT": 1,
    "PROCESSING_FAILURE": 2,
    "VALIDATION_FAILURE": 3,
    "MISSING_FILE": 4,
}
ACTIONS = {
    "SOURCE_DELIVERY_ID_CONFLICT": "Compare the retained file with the quarantined submission and ask the sender to confirm the source delivery ID.",
    "RECONCILIATION_FAILURE": "Review the linked reconciliation run and its source deliveries.",
    "PROCESSING_FAILURE": "Review the recorded processing error and confirm how to recover the delivery.",
    "VALIDATION_FAILURE": "Check the recorded validation error and request a corrected file from the sender.",
    "MISSING_FILE": "Check the incoming SFTP handoff and confirm the delivery schedule with the sender.",
}


def arrival_facts():
    # Intake links a claim to an expectation only when the manifest and physical
    # payload established arrival. Quarantined arrivals can have no File row.
    arrivals = union_all(
        select(File.delivery_expectation_id.label("delivery_id"), File.received_at.label("arrival")),
        select(IntakeClaim.delivery_expectation_id, IntakeClaim.created_at).where(
            IntakeClaim.delivery_expectation_id.is_not(None),
            IntakeClaim.status.in_((IntakeClaimStatus.COMMITTED, IntakeClaimStatus.FINALIZED)),
        ),
    ).subquery()
    return select(
        arrivals.c.delivery_id, func.min(arrivals.c.arrival).label("first_arrival"),
        func.max(arrivals.c.arrival).label("last_arrival"),
    ).group_by(arrivals.c.delivery_id).subquery()


def operations_summary(session: Session, now: datetime):
    arrival = arrival_facts()
    pending = arrival.c.first_arrival.is_(None)
    counts = session.execute(
        select(
            Delivery.integration_id, func.count().label("total"),
            func.count().filter(~pending).label("received"),
            func.count().filter(Delivery.status == DeliveryStatus.VALIDATION_FAILED).label("validation_failed"),
            func.count().filter(Delivery.status.in_(FAILURES)).label("failed"),
            func.count().filter(pending, Delivery.deadline_at >= now).label("pending"),
            func.count().filter(pending, Delivery.deadline_at < now).label("overdue"),
            func.count().filter(Delivery.overdue_at.is_not(None)).label("breached"),
            func.count().filter(arrival.c.first_arrival <= Delivery.deadline_at).label("on_time"),
            func.max(arrival.c.last_arrival).label("last_arrival"),
        ).outerjoin(arrival, arrival.c.delivery_id == Delivery.id).group_by(Delivery.integration_id)
    ).mappings()
    stats = {row["integration_id"]: row for row in counts}
    incidents = session.execute(select(Delivery.integration_id, Incident.incident_type, func.count())
        .join(Delivery, Delivery.id == Incident.delivery_expectation_id)
        .where(Incident.status.in_(ACTIVE)).group_by(Delivery.integration_id, Incident.incident_type))
    by_integration = {}
    by_type = {}
    for integration_id, kind, count in incidents:
        by_integration[integration_id] = by_integration.get(integration_id, 0) + count
        by_type[kind.value] = by_type.get(kind.value, 0) + count
    fields = ("total", "received", "validation_failed", "failed", "pending", "overdue", "breached", "on_time")
    totals = dict.fromkeys(fields, 0)
    activity = {}
    for integration_id, row in stats.items():
        activity[integration_id] = {key: row[key] for key in fields} | {"last_arrival": row["last_arrival"]}
        for key in fields:
            totals[key] += row[key]
    return totals, activity, by_integration, by_type


def attention_items(session: Session, now: datetime, limit: int, integration_id: UUID | None):
    arrival = arrival_facts()
    # Combine persisted incidents with computed exceptions for which no matching
    # active incident exists. A delivery can have several distinct problems.
    incident_kind = cast(Incident.incident_type, String)
    columns = (Delivery.id.label("delivery_id"), Delivery.integration_id, Delivery.delivery_type,
               Delivery.business_date, Delivery.status, Delivery.deadline_at)
    actual = select(
        *columns, incident_kind.label("kind"), Incident.reason,
        Incident.opened_at.label("at"), cast(Incident.id, String).label("key"),
        case(PRIORITY, value=incident_kind, else_=5).label("rank"),
        literal(True).label("recorded_incident"),
    ).join(Incident, Incident.delivery_expectation_id == Delivery.id).where(Incident.status.in_(ACTIVE))

    def fallback(kind, condition, reason, at):
        exists = select(Incident.id).where(
            Incident.delivery_expectation_id == Delivery.id,
            Incident.incident_type == kind, Incident.status.in_(ACTIVE),
        ).exists()
        return select(*columns, literal(kind), reason, at, cast(Delivery.id, String),
                      literal(PRIORITY[kind]), literal(False)).outerjoin(arrival, arrival.c.delivery_id == Delivery.id).outerjoin(
            File, File.id == Delivery.current_file_id
        ).where(condition, ~exists)

    problems = union_all(
        actual,
        fallback("PROCESSING_FAILURE", Delivery.status == DeliveryStatus.PROCESSING_FAILED,
                 File.processing_error_code, File.processed_at),
        fallback("VALIDATION_FAILURE", Delivery.status == DeliveryStatus.VALIDATION_FAILED,
                 File.validation_error_code, File.validated_at),
        fallback("MISSING_FILE", (Delivery.deadline_at < now) & arrival.c.first_arrival.is_(None),
                 literal("The deadline passed with no recorded arrival."), Delivery.deadline_at),
    ).subquery()
    query = select(problems).order_by(problems.c.rank, problems.c.deadline_at, problems.c.key)
    if integration_id is not None:
        query = query.where(problems.c.integration_id == integration_id)
    return [dict(row) | {"action": ACTIONS.get(row["kind"], "Review the recorded incident.")}
            for row in session.execute(query.limit(limit)).mappings()]
