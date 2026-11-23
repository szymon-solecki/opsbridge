"""Execute reconciliation runs under the existing worker and event contracts."""

from datetime import datetime, timedelta, timezone
from io import StringIO
from itertools import islice
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from backend.app.intake.csv_validation import validated_records
from backend.app.intake.paths import accepted_package_directory
from backend.app.intake.worker import lifecycle
from backend.app.models import DeliveryExpectation, DeliveryStatus, File, FileStatus, Incident, IncidentStatus, IncidentType
from backend.app.models.reconciliation import ReconciliationDefinition, ReconciliationRun
from backend.app.services.audit import record_event
from backend.app.services.incident_notifications import open_incident, resolve_incident
from backend.app.services.matching import MATCHED, MAX_ROWS, match
from backend.app.services.processing import SnapshotReadError, _accepted_claims, verified_payload
from backend.app.telemetry import report, timed

ACTIVE = ("WAITING", "RUNNING", "RETRY")
MAX_ATTEMPTS = 3
RUN_FIELDS = (ReconciliationRun.id, ReconciliationRun.definition_id, ReconciliationRun.parent_id,
              ReconciliationRun.status, ReconciliationRun.attempts, ReconciliationRun.created_at,
              ReconciliationRun.finished_at, ReconciliationRun.error_code, ReconciliationRun.source_a_delivery_id,
              ReconciliationRun.source_b_delivery_id, ReconciliationRun.file_a_id, ReconciliationRun.file_b_id)


def audit(session, delivery, run, event, now, *, operator_id=None, **details):
    record_event(session, delivery, event, now, actor=str(operator_id) if operator_id else "opsbridge-reconciliation",
                 operator=operator_id is not None, reconciliation_run_id=str(run.id),
                 reconciliation_attempt=run.attempts, **details)


def enqueue(session, definition, delivery, now, *, parent_id=None, run_id=None, operator_id=None):
    run = ReconciliationRun(id=run_id or uuid4(), definition_id=definition.id,
                            source_a_delivery_id=definition.source_a_delivery_id,
                            source_b_delivery_id=definition.source_b_delivery_id, parent_id=parent_id,
                            status="WAITING", attempts=0, next_attempt_at=now, missing_reported=False)
    session.add(run)
    audit(session, delivery, run, "ReconciliationQueued", now, operator_id=operator_id)
    return run


def _incident(session, delivery, run, now, reason=None):
    incident = session.scalar(select(Incident).where(Incident.reconciliation_run_id == run.id).with_for_update())
    if reason and incident is None:
        return open_incident(session, delivery, IncidentType.RECONCILIATION_FAILURE, now, reason=reason,
                             reconciliation_run_id=run.id)
    if reason is None and incident and incident.status != IncidentStatus.RESOLVED:
        resolve_incident(session, delivery, incident, now, "The reconciliation completed below the incident thresholds.")
    return incident


def _pinnable(session, delivery):
    if delivery.status != DeliveryStatus.COMPLETED or delivery.current_file_id is None:
        return None
    file = session.get(File, delivery.current_file_id)
    if file.status == FileStatus.COMPLETED and session.scalar(_accepted_claims(file.id).limit(1)):
        return file.id
    return None


def _start(session, run, definition, sources, now):
    if run.status == "WAITING":
        pins = [_pinnable(session, delivery) for delivery in sources]
        if None in pins:
            missing = any(delivery.current_file_id is None and delivery.deadline_at < now for delivery in sources)
            if missing and definition.incident_on_missing and not run.missing_reported:
                _incident(session, sources[0], run, now, "A required source file missed its arrival deadline.")
                run.missing_reported = True
                audit(session, sources[0], run, "ReconciliationSourceMissing", now)
            run.next_attempt_at = now + timedelta(seconds=5)
            return False
        run.file_a_id, run.file_b_id = pins
    if run.attempts >= MAX_ATTEMPTS:
        _fail(session, definition, sources[0], run, now, "WORKER_INTERRUPTED", retryable=False)
        return False
    run.attempts += 1
    run.status = "RUNNING"
    run.next_attempt_at = now
    audit(session, sources[0], run, "ReconciliationStarted", now)
    return True


def _fail(session, definition, delivery, run, now, code, *, retryable):
    run.error_code = code
    if retryable and run.attempts < MAX_ATTEMPTS:
        run.status = "RETRY"
        run.next_attempt_at = now + timedelta(seconds=2 ** run.attempts)
        audit(session, delivery, run, "ReconciliationRetryScheduled", now, error_code=code)
    else:
        run.status = "FAILED"
        run.finished_at = now
        if definition.incident_on_failure:
            _incident(session, delivery, run, now, "Reconciliation could not complete. Review the run audit.")
        audit(session, delivery, run, "ReconciliationFailed", now, error_code=code)


def _read_source(root, delivery, file, claim):
    if claim is None:
        raise SnapshotReadError("STORAGE_UNAVAILABLE")
    data = verified_payload(accepted_package_directory(delivery.integration_id, claim, root=root), file)
    try:
        records = list(islice(validated_records(StringIO(data.decode("utf-8-sig"), newline="")), MAX_ROWS + 1))
    except ValueError:
        raise SnapshotReadError("SNAPSHOT_INVALID") from None
    if len(records) > MAX_ROWS:
        raise SnapshotReadError("SOURCE_ROW_LIMIT")
    return records


@timed("reconciliation")
def execute_run(engine, root, run_id, *, clock=None, reader=_read_source):
    clock = clock or (lambda: datetime.now(timezone.utc))
    with lifecycle(engine, run_id, namespace="reconciliation:run") as connection:
        if connection is None:
            return False
        with Session(connection, expire_on_commit=False, autoflush=False) as session:
            with session.begin():
                run = session.scalar(select(ReconciliationRun).options(load_only(
                    *RUN_FIELDS, ReconciliationRun.next_attempt_at, ReconciliationRun.missing_reported,
                )).where(ReconciliationRun.id == run_id).with_for_update())
                if run is None or run.status not in ACTIVE or run.next_attempt_at > clock():
                    return False
                definition = session.get(ReconciliationDefinition, run.definition_id)
                pair = (run.source_a_delivery_id, run.source_b_delivery_id)
                loaded = {delivery.id: delivery for delivery in session.scalars(select(DeliveryExpectation)
                          .where(DeliveryExpectation.id.in_(pair)).order_by(DeliveryExpectation.id)
                          .with_for_update(read=True))}
                sources = [loaded[key] for key in pair]
                if not _start(session, run, definition, sources, clock()):
                    return False
                sources_data = [
                    (delivery, session.get(File, key), session.scalar(_accepted_claims(key).limit(1)))
                    for delivery, key in zip(sources, (run.file_a_id, run.file_b_id), strict=True)
                ]
            try:
                left, right = (reader(root, *source) for source in sources_data)
                snapshot, results, counts, material = match(left, right, business_date=sources[0].business_date,
                                                             match_on=definition.match_on, tolerance=definition.tolerance,
                                                             materiality=definition.materiality)
            except SnapshotReadError as error:
                with session.begin():
                    _fail(session, definition, sources[0], run, clock(), str(error),
                          retryable=str(error) == "STORAGE_UNAVAILABLE")
                return True
            now = clock()
            with session.begin():
                exceptions = sum(count for kind, count in counts.items() if kind not in MATCHED)
                threshold = definition.exception_limit is not None and exceptions >= definition.exception_limit
                run.status, run.finished_at, run.error_code = "COMPLETED", now, None
                run.snapshot = snapshot
                run.report = {"counts": counts, "material": material, "results": results}
                _incident(session, sources[0], run, now, "The run exceeded its reconciliation exception policy."
                          if threshold or material else None)
                audit(session, sources[0], run, "ReconciliationCompleted", now, exception_count=exceptions)
            report("RECONCILIATION_COMPLETED", delivery_expectation_id=sources[0].id)
            return True


def scan_reconciliation(engine, root, *, limit=25):
    with Session(engine) as session:
        keys = list(session.scalars(select(ReconciliationRun.id)
                    .where(ReconciliationRun.status.in_(ACTIVE),
                           ReconciliationRun.next_attempt_at <= datetime.now(timezone.utc))
                    .order_by(ReconciliationRun.next_attempt_at, ReconciliationRun.id).limit(limit)))
    return sum(execute_run(engine, root, key) for key in keys)
