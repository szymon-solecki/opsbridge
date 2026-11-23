"""Read models for the operations workspace."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, computed_field
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, joinedload

from backend.app.database import get_db
from backend.app.models.security import NotificationPolicyDocument
from backend.app.security import ROLES, admin, audit, operator, viewer
from backend.app.models import ActivityFeed, DeliveryEvent, DeliveryExpectation, DeliveryStatus, File, FileStatus, Incident, Integration
from backend.app.schemas.delivery_expectation import DeliveryExpectationRead
from backend.app.schemas.integration import IntegrationRead
from backend.app.services.operations import attention_items, operations_summary
from backend.app.services.processing import MAX_ATTEMPTS, RETRY_DELAY, RETRYABLE, request_reprocessing
from backend.app.models import IncidentAcknowledgement, NotificationAttempt, NotificationJob
from backend.app.services.incident_notifications import acknowledge_incident
from backend.app.services.notification_policy import Rule, SEVERITY, policies, validate_rules

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class ActivityEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_event_id: UUID
    delivery_expectation_id: UUID
    event_type: str
    summary: str
    payload: dict | None
    occurred_at: datetime


class ActivityPage(BaseModel):
    items: list[ActivityEntry]
    next_before_at: datetime | None = None
    next_before_id: UUID | None = None


@router.get("/activity", response_model=ActivityPage)
def activity(
    integration_id: UUID | None = None,
    delivery_id: UUID | None = None,
    event_type: str | None = Query(None, min_length=1, max_length=100),
    before_at: AwareDatetime | None = None,
    before_id: UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
):
    if (before_at is None) != (before_id is None):
        raise HTTPException(422, "Both activity cursor fields are required.")
    query = select(ActivityFeed)
    if integration_id is not None:
        query = query.join(DeliveryExpectation, DeliveryExpectation.id == ActivityFeed.delivery_expectation_id).where(
            DeliveryExpectation.integration_id == integration_id
        )
    if delivery_id is not None:
        query = query.where(ActivityFeed.delivery_expectation_id == delivery_id)
    if event_type is not None:
        query = query.where(ActivityFeed.event_type == event_type)
    if before_at is not None:
        query = query.where(tuple_(ActivityFeed.occurred_at, ActivityFeed.source_event_id) < tuple_(before_at, before_id))
    rows = list(session.scalars(query.order_by(
        ActivityFeed.occurred_at.desc(), ActivityFeed.source_event_id.desc(),
    ).limit(limit + 1)))
    after = rows[limit - 1] if len(rows) > limit else None
    return ActivityPage(items=[ActivityEntry.model_validate(row) for row in rows[:limit]],
                        next_before_at=after.occurred_at if after else None,
                        next_before_id=after.source_event_id if after else None)


class CurrentFile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_name: str
    size_bytes: int
    received_at: datetime
    content_hash: str
    validation_error_code: str | None
    processing_error_code: str | None
    processing_error_message: str | None
    status: FileStatus
    attempt_series: int
    attempt_count_in_series: int
    processed_at: datetime | None
    replaces_file_id: UUID | None

    @computed_field
    @property
    def next_retry_at(self) -> datetime | None:
        if (self.status == FileStatus.PROCESSING_FAILED and self.processing_error_code in RETRYABLE
                and self.attempt_count_in_series < MAX_ATTEMPTS and self.processed_at is not None):
            return self.processed_at + RETRY_DELAY
        return None

    @computed_field
    @property
    def can_reprocess(self) -> bool:
        return (self.status == FileStatus.PROCESSING_FAILED and self.processing_error_code in RETRYABLE
                and self.attempt_count_in_series == MAX_ATTEMPTS)


class DashboardDelivery(DeliveryExpectationRead):
    current_file: CurrentFile | None


class ReprocessingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    file_id: UUID
    attempt_series: int = Field(strict=True, ge=1)
    confirmed: StrictBool


class DashboardOverview(BaseModel):
    integrations: list[IntegrationRead]
    counts: dict[DeliveryStatus, int]
    metrics: dict[str, int]
    activity: dict[UUID, dict[str, int | datetime | None]]
    incidents_by_type: dict[str, int]
    as_of: datetime
    reprocessing_enabled: bool


@router.get("/overview")
def overview(session: Session = Depends(get_db), principal=Depends(viewer)) -> DashboardOverview:
    integrations = session.scalars(select(Integration).order_by(Integration.name, Integration.id))
    counts = session.execute(select(DeliveryExpectation.status, func.count()).group_by(DeliveryExpectation.status))
    now = datetime.now(timezone.utc)
    metrics, activity, incident_counts, by_type = operations_summary(session, now)
    for integration_id, count in incident_counts.items():
        activity.setdefault(integration_id, {})["active_incidents"] = count
    return DashboardOverview(
        integrations=[IntegrationRead.model_validate(row) for row in integrations],
        counts=dict(counts.all()),
        metrics=metrics,
        activity=activity,
        incidents_by_type=by_type,
        as_of=now,
        reprocessing_enabled=ROLES[principal.role] >= ROLES["OPERATOR"],
    )


@router.get("/attention")
def attention(
    integration_id: UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
):
    return attention_items(session, datetime.now(timezone.utc), limit, integration_id)


@router.get("/deliveries", response_model=list[DashboardDelivery])
def deliveries(
    integration_id: UUID | None = None,
    status: DeliveryStatus | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
    sort: Literal["newest", "deadline"] = "newest",
):
    query = select(DeliveryExpectation).options(joinedload(DeliveryExpectation.current_file))
    if integration_id is not None:
        query = query.where(DeliveryExpectation.integration_id == integration_id)
    if status is not None:
        query = query.where(DeliveryExpectation.status == status)
    order = DeliveryExpectation.deadline_at.asc() if sort == "deadline" else DeliveryExpectation.created_at.desc()
    return session.scalars(query.order_by(order, DeliveryExpectation.id.desc()).offset(offset).limit(limit)).all()


@router.get("/deliveries/{delivery_id}", response_model=DashboardDelivery)
def delivery(delivery_id: UUID, session: Session = Depends(get_db)):
    result = session.get(DeliveryExpectation, delivery_id, options=[joinedload(DeliveryExpectation.current_file)])
    if result is None:
        raise HTTPException(404, "Delivery expectation not found.")
    return result


@router.post("/deliveries/{delivery_id}/reprocess", status_code=202)
def reprocess(delivery_id: UUID, request: ReprocessingRequest, session: Session = Depends(get_db),
              principal=Depends(operator)):
    if not request.confirmed:
        raise HTTPException(422, "Explicit confirmation is required.")
    with session.begin():
        if request_reprocessing(session, delivery_id, request.file_id, str(principal.id), request.attempt_series) is None:
            raise HTTPException(409, "This file is no longer eligible for reprocessing.")
        audit(session, "FILE_REPROCESS_REQUESTED", principal.id, request.file_id)
    return {"status": "queued"}


class AcknowledgementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    comment: str | None = Field(default=None, max_length=500)


@router.get("/notification-policies")
def notification_policies(session: Session = Depends(get_db)):
    return {"rules": policies(session), "severity_by_incident_type": SEVERITY}


@router.put("/notification-policies")
def update_notification_policies(rules: list[Rule], session: Session = Depends(get_db), principal=Depends(admin)):
    try:
        verified = validate_rules(rules)
    except ValueError:
        raise HTTPException(422, "Invalid notification policies.") from None
    document = [rule.model_dump(mode="json") for rule in verified]
    with session.begin():
        session.execute(insert(NotificationPolicyDocument).values(id=1, rules=document).on_conflict_do_update(
            index_elements=[NotificationPolicyDocument.id], set_={"rules": document},
        ))
        audit(session, "NOTIFICATION_POLICY_CHANGED", principal.id)
    return {"rules": verified}


@router.post("/incidents/{incident_id}/acknowledge")
def acknowledge(incident_id: UUID, request: AcknowledgementRequest, session: Session = Depends(get_db),
                principal=Depends(operator)):
    with session.begin():
        result = acknowledge_incident(session, incident_id, datetime.now(timezone.utc),
                                      operator=str(principal.id), comment=request.comment or None)
        if result is None:
            raise HTTPException(409, "The incident is no longer open.")
        audit(session, "INCIDENT_ACKNOWLEDGED", principal.id, incident_id)
        return {"incident_id": result.incident_id, "operator": result.operator,
                "acknowledged_at": result.acknowledged_at, "comment": result.comment}


def _notification_history(session, incident_ids):
    jobs = list(session.scalars(select(NotificationJob).where(
        NotificationJob.incident_id.in_(incident_ids),
    ).order_by(NotificationJob.scheduled_at, NotificationJob.level, NotificationJob.id)))
    attempts = {}
    for row in session.scalars(select(NotificationAttempt).where(
        NotificationAttempt.job_id.in_([job.id for job in jobs]),
    ).order_by(NotificationAttempt.number)):
        attempts.setdefault(row.job_id, []).append({key: getattr(row, key) for key in (
            "number", "status", "started_at", "finished_at", "error_code",
        )})
    history = {}
    for job in jobs:
        details = {key: getattr(job, key) for key in (
            "id", "event", "level", "severity", "owner", "recipient", "status",
            "scheduled_at", "next_attempt_at", "finished_at", "attempt_count", "last_error",
        )}
        details["attempts"] = attempts.get(job.id, [])
        history.setdefault(job.incident_id, []).append(details)
    return history


@router.get("/deliveries/{delivery_id}/incidents")
def incidents(delivery_id: UUID, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
              session: Session = Depends(get_db), principal=Depends(viewer)):
    if session.get(DeliveryExpectation, delivery_id) is None:
        raise HTTPException(404, "Delivery expectation not found.")
    rows = list(session.scalars(select(Incident).where(Incident.delivery_expectation_id == delivery_id)
                                .order_by(Incident.opened_at.desc(), Incident.id.desc()).offset(offset).limit(limit)))
    if not rows:
        return []
    ids = [row.id for row in rows]
    jobs = _notification_history(session, ids)
    audit = {row.incident_id: row for row in session.scalars(
        select(IncidentAcknowledgement).where(IncidentAcknowledgement.incident_id.in_(ids))
    )}
    return [
        {key: getattr(row, key) for key in ("id", "incident_type", "status", "reason", "opened_at",
                                            "acknowledged_at", "resolved_at", "resolution_reason", "reconciliation_run_id")}
        | {"notifications": jobs.get(row.id, []), "severity": SEVERITY[row.incident_type],
           "acknowledgement_enabled": ROLES[principal.role] >= ROLES["OPERATOR"], "operator": audit[row.id].operator if row.id in audit else None,
           "acknowledgement_comment": audit[row.id].comment if row.id in audit else None}
        for row in rows
    ]


@router.get("/deliveries/{delivery_id}/events")
def events(
    delivery_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
):
    if session.get(DeliveryExpectation, delivery_id) is None:
        raise HTTPException(404, "Delivery expectation not found.")
    statement = (
        select(DeliveryEvent, File.original_name, File.replaces_file_id)
        .outerjoin(File, File.id == DeliveryEvent.file_id)
        .where(DeliveryEvent.delivery_expectation_id == delivery_id)
        .order_by(DeliveryEvent.occurred_at, DeliveryEvent.id)
        .offset(offset).limit(limit)
    )
    result = []
    for event, filename, predecessor in session.execute(statement):
        details = event.details if isinstance(event.details, dict) else {}
        result.append({
            "id": event.id, "delivery_id": event.delivery_expectation_id, "event_type": event.event_type,
            "occurred_at": event.occurred_at, "file_id": event.file_id, "filename": filename,
            "replaces_file_id": predecessor,
            "actor_reference": event.actor_reference,
            "details": {
                key: details[key] for key in ("error_code", "record_count", "existing_file_id",
                    "attempt_series", "attempt_count_in_series", "failure_reason", "next_retry_at",
                    "debit_count", "credit_count", "zero_count", "reconciliation_run_id",
                    "reconciliation_attempt", "exception_count")
                if key in details and type(details[key]) in (str, int)
            },
        })
    return result
