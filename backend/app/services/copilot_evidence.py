"""Read bounded, privacy-filtered evidence for a fixed set of operations queries."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import aliased

from backend.app.models import (
    ActivityFeed, DeliveryEvent, DeliveryExpectation as Delivery, File, Incident, IntakeClaim, Integration,
    NotificationAttempt, NotificationJob, ReconciliationRun,
)
from backend.app.services.activity import SUMMARIES
from backend.app.services.matching import MATCHED, RESULTS

QUERY_LIMIT = 12
EVENT_LIMIT = 12
FILE_LIMIT = 4
JOB_LIMIT = 6
ACTIVITY_LIMIT = 4
CLAIM_LIMIT = 4
CLAIM_FAILURES = ("INTEGRITY_MISMATCH", "SOURCE_DELIVERY_ID_CONFLICT")
KNOWN_ERRORS = frozenset((
    "CSV_ENCODING_INVALID", "CSV_HEADER_INVALID", "CSV_ROW_INVALID", "CSV_EMPTY",
    "STORAGE_UNAVAILABLE", "WORKER_INTERRUPTED", "SNAPSHOT_INVALID",
))
FAILURES = ("FileValidationFailed", "FileProcessingFailed", "DeliveryOverdue", "SourceDeliveryIdConflict")


class UnsupportedQuestion(ValueError):
    """Use a supported operation or select a specific record."""


class RecordNotFound(ValueError):
    """The requested record does not exist in this workspace."""


@dataclass(frozen=True)
class Query:
    kind: str
    target: UUID | str | None = None
    exception_index: int | None = None


def parse_question(question, incident_id=None):
    query = " ".join(question.casefold().strip().rstrip("?.").split())
    patterns = {
        "unresolved": r"(?:which integrations (?:currently )?have|list integrations with|show integrations with) (?:unresolved|open|active) incidents",
        "sla": r"(?:which deliveries (?:breached|missed) (?:their |the )?sla|show (?:sla breaches|breached deliveries)|list sla breaches)",
        "today": r"(?:summarize|show|list) (?:today's operational problems|operational problems today|today's incidents)",
    }
    for kind, pattern in patterns.items():
        if re.fullmatch(pattern, query):
            return Query(kind)
    if re.fullmatch(r"what happened before (?:this |the )?incident was acknowledged", query) and incident_id:
        return Query("before_acknowledgement", incident_id)
    if match := re.fullmatch(r"why did (?:the )?([a-z0-9 _-]{1,64}) delivery fail", query, flags=re.ASCII):
        return Query("failed_delivery", re.sub(r"[- _]+", "_", match[1].strip()).upper())
    if match := re.fullmatch(r"why did delivery ([0-9a-f-]{36}) fail", query):
        try:
            return Query("delivery", UUID(match[1]))
        except ValueError:
            pass
    raise UnsupportedQuestion


@dataclass(frozen=True)
class Evidence:
    ref: str
    kind: str
    record_id: str
    timestamp: datetime
    fact: str
    label: str | None
    signal: str | None
    delivery_id: UUID | None = None


class EvidenceSet:
    def __init__(self):
        self.records: list[Evidence] = []
        self.limited = False
        self.allow_hypotheses = True
        self.gaps: list[str] = []

    def add(self, kind, record_id, at, fact, *, label=None, signal=None, delivery_id=None):
        self.records.append(Evidence(f"E{len(self.records) + 1}", kind, str(record_id), at, fact, label, signal, delivery_id))

    def rows(self, session, statement, limit):
        rows = list(session.execute(statement.limit(limit + 1)))
        self.limited |= len(rows) > limit
        return rows[:limit]


def _instant(at):
    return at.astimezone(timezone.utc).isoformat()


def _delivery_fields():
    return (Delivery.id, Delivery.integration_id, Delivery.delivery_type, Delivery.business_date, Delivery.status,
            Delivery.created_at, Delivery.deadline_at, Delivery.overdue_at, Delivery.current_file_id)


def _delivery_fact(evidence, row, *, breach_relevant=True):
    breach = f" A breach was recorded at {_instant(row.overdue_at)}." if row.overdue_at else ""
    evidence.add("delivery", row.id, row.overdue_at or row.created_at,
                 f"Delivery for {row.business_date.isoformat()} is {row.status.value}. "
                 f"Arrival deadline: {_instant(row.deadline_at)}.{breach}",
                 label=row.delivery_type, signal="DeliveryOverdue" if row.overdue_at and breach_relevant else None)


def _event_fields():
    return (DeliveryEvent.id, DeliveryEvent.occurred_at, DeliveryEvent.event_type, DeliveryEvent.file_id,
            DeliveryEvent.details["error_code"].astext.label("error"),
            DeliveryEvent.details["attempt_series"].astext.label("series"),
            DeliveryEvent.details["attempt_count_in_series"].astext.label("attempt"))


def _event_fact(evidence, row, *, relevant=True):
    error = _known_error(row.error)
    attempt = ""
    if row.series and re.fullmatch(r"[1-9][0-9]{0,8}", row.series) and row.attempt in ("0", "1", "2", "3"):
        attempt = f" Processing series {row.series}, attempt {row.attempt}."
    evidence.add("delivery_event", row.id, row.occurred_at,
                 SUMMARIES[row.event_type] + "." + attempt + error,
                 signal=(row.error if error else row.event_type) if relevant else None)


def _known_error(value):
    return f" Recorded code: {value}." if value in KNOWN_ERRORS else ""


def _claim_failures():
    return (IntakeClaim.status == "FINALIZED", IntakeClaim.final_location == "QUARANTINE",
            IntakeClaim.error_code.in_(CLAIM_FAILURES))


def _accepted_claim(claim):
    return (claim.status == "FINALIZED", claim.final_location == "ACCEPTED", claim.error_code.is_(None))


def _intake_history(session, evidence, delivery, linked, before, *, conflict_relevant):
    other = aliased(IntakeClaim)
    peers = select(other.id).where(other.file_id == IntakeClaim.file_id, other.id != IntakeClaim.id,
                                  other.integration_id == IntakeClaim.integration_id,
                                  other.delivery_expectation_id == IntakeClaim.delivery_expectation_id,
                                  *_accepted_claim(other))
    if before is not None:
        peers = peers.where(other.finalized_at < before)
    claims = select(IntakeClaim.id, IntakeClaim.finalized_at, IntakeClaim.error_code).where(
        IntakeClaim.integration_id == delivery.integration_id,
        IntakeClaim.delivery_expectation_id == delivery.id,
        or_(and_(*_claim_failures()), and_(*_accepted_claim(IntakeClaim), peers.exists())),
    )
    if linked is not None:
        claims = claims.where(IntakeClaim.file_id == linked)
    if before is not None:
        claims = claims.where(IntakeClaim.finalized_at < before)
    for row in evidence.rows(session, claims.order_by(IntakeClaim.finalized_at.desc(), IntakeClaim.id.desc()), CLAIM_LIMIT):
        if row.error_code == "INTEGRITY_MISMATCH":
            fact = "Intake quarantined this package with INTEGRITY_MISMATCH: the size or checksum verification failed."
        elif row.error_code == "SOURCE_DELIVERY_ID_CONFLICT":
            fact = "Intake quarantined this package with SOURCE_DELIVERY_ID_CONFLICT."
        else:
            fact = "Multiple accepted intake claims reference the same stored file, evidence of duplicate intake."
        signal = row.error_code if conflict_relevant and row.error_code == "SOURCE_DELIVERY_ID_CONFLICT" else None
        evidence.add("intake_claim", row.id, row.finalized_at, fact, signal=signal)


def _incident_fact(evidence, incident):
    evidence.add("incident", incident.id, incident.opened_at,
                 f"{incident.incident_type.value} incident is {incident.status.value}.",
                 signal=incident.incident_type.value, delivery_id=incident.delivery_expectation_id)
    if incident.acknowledged_at:
        evidence.add("incident_acknowledgement", incident.id, incident.acknowledged_at,
                     "The incident was acknowledged at this time.", delivery_id=incident.delivery_expectation_id)
    if incident.resolved_at:
        evidence.add("incident_resolution", incident.id, incident.resolved_at,
                     "The incident was resolved at this time.", delivery_id=incident.delivery_expectation_id)


INCIDENT_FIELDS = (
    Incident.id, Incident.delivery_expectation_id, Incident.file_id, Incident.incident_type,
    Incident.status, Incident.opened_at, Incident.acknowledged_at, Incident.resolved_at,
)


def _history(session, evidence, delivery, incident=None, before=None):
    breach_relevant = not incident or incident.incident_type.value == "MISSING_FILE"
    if before and delivery.overdue_at and delivery.overdue_at < before:
        evidence.add("delivery", delivery.id, delivery.overdue_at, "An SLA breach was already recorded.",
                     signal="DeliveryOverdue" if breach_relevant else None)
    if not before:
        _delivery_fact(evidence, delivery, breach_relevant=breach_relevant)
        integration = session.execute(select(Integration.id, Integration.created_at, Integration.active, Integration.name)
                                      .where(Integration.id == delivery.integration_id)).one()
        evidence.add("integration", integration.id, integration.created_at,
                     "Integration is configured active." if integration.active else "Integration is configured inactive.",
                     label=integration.name)
    events = select(*_event_fields()).where(
        DeliveryEvent.delivery_expectation_id == delivery.id, DeliveryEvent.event_type.in_(SUMMARIES),
    )
    current_file = delivery.current_file_id
    linked = incident.file_id if incident else None
    files = select(File.id, File.received_at, File.status, File.size_bytes, File.validation_error_code,
                   File.processing_error_code, File.attempt_series, File.attempt_count_in_series,
                   File.replaces_file_id).where(File.delivery_expectation_id == delivery.id)
    activity = select(ActivityFeed.source_event_id, ActivityFeed.occurred_at, ActivityFeed.event_type).where(
        ActivityFeed.delivery_expectation_id == delivery.id, ActivityFeed.event_type.in_(SUMMARIES),
    )
    if before:
        events = events.where(DeliveryEvent.occurred_at < before)
        activity = activity.where(ActivityFeed.occurred_at < before)
    else:
        for row in evidence.rows(session, files.order_by(
                (File.id == linked).desc() if linked else File.received_at.desc(),
                (File.id == current_file).desc() if current_file else File.received_at.desc(),
                File.received_at.desc(), File.id.desc()), FILE_LIMIT):
            error = _known_error(row.validation_error_code) or _known_error(row.processing_error_code)
            evidence.add("file", row.id, row.received_at,
                         f"File is {row.status.value}; size {row.size_bytes} bytes. "
                         f"Processing series {row.attempt_series}, attempts {row.attempt_count_in_series}."
                         + (" A replacement predecessor is recorded." if row.replaces_file_id else "") + error,
                         signal=(row.validation_error_code or row.processing_error_code)
                         if error and (incident is None or row.id == linked) else None)
    event_rows = evidence.rows(session, events.order_by(DeliveryEvent.occurred_at.desc(), DeliveryEvent.id.desc()), EVENT_LIMIT)
    for row in event_rows:
        relevant = incident is None or (linked is not None and row.file_id == linked)
        _event_fact(evidence, row, relevant=relevant)
    if not event_rows:
        evidence.gaps.append("No matching authoritative delivery events were recorded in this window.")
    _intake_history(session, evidence, delivery, linked, before,
                    conflict_relevant=incident is None or incident.incident_type.value == "SOURCE_DELIVERY_ID_CONFLICT")
    for row in evidence.rows(session, activity.order_by(ActivityFeed.occurred_at.desc(), ActivityFeed.source_event_id.desc()),
                             ACTIVITY_LIMIT):
        evidence.add("activity_projection", row.source_event_id, row.occurred_at,
                     "Activity feed projection exists for: " + SUMMARIES[row.event_type] + ".")
    if incident:
        _notifications(session, evidence, incident, before)


def _notifications(session, evidence, incident, before):
    jobs = select(NotificationJob.id, NotificationJob.event, NotificationJob.level, NotificationJob.status,
                  NotificationJob.scheduled_at, NotificationJob.finished_at).where(NotificationJob.incident_id == incident.id)
    if before:
        jobs = jobs.where(NotificationJob.scheduled_at < before)
    rows = evidence.rows(session, jobs.order_by(NotificationJob.scheduled_at.desc(), NotificationJob.id.desc()), JOB_LIMIT)
    for row in rows:
        if before and (not row.finished_at or row.finished_at >= before):
            continue
        evidence.add("notification_job", row.id, row.finished_at or row.scheduled_at,
                     f"Notification {row.event}, escalation level {row.level}: {row.status}.")
    if not rows:
        evidence.gaps.append("No notification jobs were recorded for this incident in the selected window.")
        return
    attempts = select(NotificationAttempt.job_id, NotificationAttempt.number, NotificationAttempt.status,
                      NotificationAttempt.started_at, NotificationAttempt.finished_at).where(
                          NotificationAttempt.job_id.in_([row.id for row in rows]))
    if before:
        attempts = attempts.where(NotificationAttempt.started_at < before)
    for row in evidence.rows(session, attempts.order_by(NotificationAttempt.started_at.desc(),
                                                         NotificationAttempt.job_id.desc(),
                                                         NotificationAttempt.number.desc()), JOB_LIMIT * 3):
        status = "STARTED" if before and (not row.finished_at or row.finished_at >= before) else row.status
        evidence.add("notification_attempt", f"{row.job_id}:{row.number}",
                     row.started_at if status == "STARTED" else row.finished_at or row.started_at,
                     f"Notification attempt {row.number}: {status}.")


def _focused(session, query, evidence):
    incident = None
    if query.kind in ("incident", "before_acknowledgement"):
        incident = session.execute(select(*INCIDENT_FIELDS).where(Incident.id == query.target)).one_or_none()
        if incident is None:
            raise RecordNotFound
        if query.kind == "before_acknowledgement":
            if not incident.acknowledged_at:
                _incident_fact(evidence, incident)
                evidence.allow_hypotheses = False
                evidence.gaps.append("There is no acknowledgement cutoff for this incident.")
                return
            evidence.add("incident_acknowledgement", incident.id, incident.acknowledged_at,
                         f"Acknowledgement cutoff: {_instant(incident.acknowledged_at)}.", delivery_id=incident.delivery_expectation_id)
            evidence.add("incident", incident.id, incident.opened_at,
                         f"{incident.incident_type.value} incident opened.", signal=incident.incident_type.value,
                         delivery_id=incident.delivery_expectation_id)
        else:
            _incident_fact(evidence, incident)
    if query.kind == "failed_delivery":
        matches = evidence.rows(session, select(*_delivery_fields()).where(
            Delivery.delivery_type == query.target,
            or_(Delivery.status.in_(("VALIDATION_FAILED", "PROCESSING_FAILED")),
                select(DeliveryEvent.id).where(DeliveryEvent.delivery_expectation_id == Delivery.id,
                                               DeliveryEvent.event_type.in_(FAILURES[:2])).exists(),
                select(IntakeClaim.id).where(IntakeClaim.integration_id == Delivery.integration_id,
                                              IntakeClaim.delivery_expectation_id == Delivery.id,
                                              *_claim_failures()).exists()),
        ).order_by(Delivery.business_date.desc(), Delivery.id.desc()), QUERY_LIMIT)
        if len(matches) != 1:
            evidence.allow_hypotheses = False
            for match in matches:
                _delivery_fact(evidence, match)
            evidence.gaps.append("Use a delivery ID to disambiguate matching deliveries." if matches else
                                 "No delivery with that type and recorded failure matched.")
            return
        delivery = matches[0]
    else:
        delivery = session.execute(select(*_delivery_fields()).where(
            Delivery.id == (incident.delivery_expectation_id if incident else query.target))).one_or_none()
        if delivery is None:
            raise RecordNotFound
    _history(session, evidence, delivery, incident,
             incident.acknowledged_at if query.kind == "before_acknowledgement" else None)


def _overview(session, query, evidence, now):
    if query.kind == "unresolved":
        count = func.count(Incident.id)
        rows = select(Integration.id, Integration.name, count.label("incident_count"), func.max(Incident.opened_at).label("latest")
                      ).join(Delivery, Integration.id == Delivery.integration_id
                      ).join(Incident, Incident.delivery_expectation_id == Delivery.id
                      ).where(Incident.status.in_(("OPEN", "ACKNOWLEDGED"))
                      ).group_by(Integration.id, Integration.name).order_by(count.desc(), Integration.id)
        for row in evidence.rows(session, rows, QUERY_LIMIT):
            evidence.add("integration", row.id, row.latest,
                         f"Integration has {row.incident_count} unresolved incident(s).", label=row.name)
    elif query.kind == "sla":
        rows = select(*_delivery_fields()).where(Delivery.overdue_at.is_not(None)
                                                ).order_by(Delivery.overdue_at.desc(), Delivery.id.desc())
        for row in evidence.rows(session, rows, QUERY_LIMIT):
            _delivery_fact(evidence, row)
    else:
        start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        opened = select(*INCIDENT_FIELDS).where(Incident.opened_at >= start, Incident.opened_at <= now
                                               ).order_by(Incident.opened_at.desc(), Incident.id.desc())
        for row in evidence.rows(session, opened, QUERY_LIMIT):
            _incident_fact(evidence, row)
        events = select(*_event_fields()).where(DeliveryEvent.event_type.in_(FAILURES),
                                                DeliveryEvent.occurred_at >= start, DeliveryEvent.occurred_at <= now
                                                ).order_by(DeliveryEvent.occurred_at.desc(), DeliveryEvent.id.desc())
        for row in evidence.rows(session, events, QUERY_LIMIT):
            _event_fact(evidence, row)


def collect_evidence(session, query, now):
    evidence = EvidenceSet()
    with session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        session.execute(text("SET LOCAL statement_timeout = '1500ms'"))
        if query.kind == "reconciliation":
            _reconciliation(session, query, evidence)
        elif query.kind in ("unresolved", "sla", "today"):
            _overview(session, query, evidence, now)
        else:
            _focused(session, query, evidence)
    if evidence.limited:
        evidence.gaps.append("Some evidence was omitted by per-source limits.")
    return evidence


def _reconciliation_facts(evidence, row, *, historical=False, signal_enabled=False):
    name = "Historical reconciliation run" if historical else "Reconciliation run"
    evidence.add("reconciliation_run", row.id, row.finished_at or row.created_at,
                 f"{name} is {row.status}. Recorded attempts {row.attempts}.")
    for kind in RESULTS:
        count = (row.counts or {}).get(kind)
        if type(count) is int and 0 < count <= 40_000:
            scope = "Historical run" if historical else "Run"
            evidence.add("reconciliation_summary", row.id, row.finished_at,
                         f"{scope} recorded {count} result group(s) in category {kind}.",
                         signal=kind if signal_enabled and kind not in MATCHED else None)


def _reconciliation(session, query, evidence):
    model = ReconciliationRun
    fields = [model.id, model.status, model.created_at, model.finished_at, model.attempts,
              model.source_a_delivery_id, model.source_b_delivery_id, model.parent_id, model.report["counts"].label("counts")]
    if query.exception_index is not None:
        fields.append(model.report["results"][query.exception_index - 1]["category"].astext.label("category"))
    row = session.execute(select(*fields).where(model.id == query.target)).one_or_none()
    if row is None:
        raise RecordNotFound
    _reconciliation_facts(evidence, row, signal_enabled=query.exception_index is None)
    if query.exception_index is None and row.parent_id:
        parent = session.execute(select(*fields).where(model.id == row.parent_id)).one()
        _reconciliation_facts(evidence, parent, historical=True)
    for source_id in (row.source_a_delivery_id, row.source_b_delivery_id):
        _delivery_fact(evidence, session.execute(select(*_delivery_fields()).where(Delivery.id == source_id)).one())
    if query.exception_index is not None:
        if row.category not in RESULTS or row.category in MATCHED:
            raise RecordNotFound
        evidence.add("reconciliation_exception", f"{row.id}:{query.exception_index}", row.finished_at,
                     f"The selected group was classified as {row.category}.", signal=row.category)
    if row.finished_at is None:
        evidence.gaps.append("This run has no final result yet.")
    else:
        evidence.gaps.append("Source-system records and upstream transmission logs are outside the analysis.")
