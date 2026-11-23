"""Run deterministic reconciliation over finalized private file snapshots."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import StringIO
import os
from pathlib import Path
import stat

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.app.intake.csv_validation import validated_amounts
from backend.app.intake.package import MAX_PAYLOAD_SIZE_BYTES, PackageValidationError, inspect_package
from backend.app.intake.paths import accepted_package_directory
from backend.app.intake.worker import lifecycle
from backend.app.models import (
    DeliveryExpectation, DeliveryStatus, File, FileStatus, Incident, IncidentStatus, IncidentType,
    IntakeClaim, IntakeClaimStatus, IntakeFinalLocation,
)
from backend.app.services.audit import record_event
from backend.app.services.incident_notifications import open_incident, resolve_incident
from backend.app.services.operations import ACTIVE
from backend.app.telemetry import outcome, report, timed


MAX_ATTEMPTS = 3
RETRY_DELAY = timedelta(seconds=5)
RETRYABLE = ("STORAGE_UNAVAILABLE", "WORKER_INTERRUPTED")
MESSAGES = {
    "STORAGE_UNAVAILABLE": "The finalized snapshot could not be read. Check storage availability.",
    "WORKER_INTERRUPTED": "The previous worker exited before persisting the processing result.",
    "SNAPSHOT_INVALID": "The finalized snapshot differs from the accepted file or violates its contract.",
}


@dataclass(frozen=True)
class Result:
    error: str | None = None
    record_count: int = 0
    debit_count: int = 0
    credit_count: int = 0
    zero_count: int = 0


class SnapshotReadError(ValueError):
    """An accepted snapshot could not be read or did not match its file record."""


def verified_payload(package: Path, file: File) -> bytes:
    try:
        # Missing storage is recoverable. An unsafe package shape is permanent.
        package.lstat()
        inspected = inspect_package(package)
        if inspected.payload_file_name != file.original_name:
            raise SnapshotReadError("SNAPSHOT_INVALID")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(inspected.payload_path, flags), "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise SnapshotReadError("SNAPSHOT_INVALID")
            content = stream.read(MAX_PAYLOAD_SIZE_BYTES + 1)
    except PackageValidationError as exc:
        if isinstance(exc.__cause__, OSError) and not isinstance(exc.__cause__, FileNotFoundError):
            raise SnapshotReadError("STORAGE_UNAVAILABLE") from None
        raise SnapshotReadError("SNAPSHOT_INVALID") from None
    except OSError:
        raise SnapshotReadError("STORAGE_UNAVAILABLE") from None
    if (len(content) > MAX_PAYLOAD_SIZE_BYTES or len(content) != file.size_bytes
            or sha256(content).hexdigest() != file.content_hash):
        raise SnapshotReadError("SNAPSHOT_INVALID")
    return content


def reconcile(package: Path, file: File) -> Result:
    """Classify signed amounts with no financial side effects or rounding."""
    try:
        content = verified_payload(package, file)
    except SnapshotReadError as error:
        return Result(error=str(error))
    debit = credit = zero = 0
    try:
        for amount in validated_amounts(StringIO(content.decode("utf-8-sig"), newline="")):
            if amount < 0:
                debit += 1
            elif amount > 0:
                credit += 1
            else:
                zero += 1
    except ValueError:
        return Result(error="SNAPSHOT_INVALID")
    return Result(record_count=debit + credit + zero, debit_count=debit, credit_count=credit, zero_count=zero)


def _accepted_claims(file_id):
    return select(IntakeClaim.id).where(
        IntakeClaim.file_id == file_id, IntakeClaim.status == IntakeClaimStatus.FINALIZED,
        IntakeClaim.final_location == IntakeFinalLocation.ACCEPTED, IntakeClaim.error_code.is_(None),
    ).order_by(IntakeClaim.created_at, IntakeClaim.id)


def _eligible(now):
    return or_(
        File.status == FileStatus.PROCESSING,
        and_(File.status == FileStatus.RECEIVED, File.attempt_count_in_series < MAX_ATTEMPTS),
        and_(File.status == FileStatus.PROCESSING_FAILED, File.attempt_count_in_series < MAX_ATTEMPTS,
             File.processing_error_code.in_(RETRYABLE), File.processed_at <= now - RETRY_DELAY),
    )


def _current(session, delivery_id, file_id):
    delivery = session.get(DeliveryExpectation, delivery_id, with_for_update=True)
    if delivery is None or delivery.current_file_id != file_id:
        return None, None
    return delivery, session.get(File, file_id, with_for_update=True)


def _set_status(delivery, file, status):
    file.status = status
    delivery.status = DeliveryStatus(status.value)


def _finish(session, delivery, file, result, now):
    file.processed_at = now
    file.processing_error_code = result.error
    file.processing_error_message = MESSAGES.get(result.error)
    incident = session.scalar(select(Incident).where(
        Incident.file_id == file.id, Incident.incident_type == IncidentType.PROCESSING_FAILURE,
        Incident.status.in_(ACTIVE),
    ).with_for_update())
    if result.error:
        _set_status(delivery, file, FileStatus.PROCESSING_FAILED)
        retry = result.error in RETRYABLE and file.attempt_count_in_series < MAX_ATTEMPTS
        if not retry and incident is None:
            open_incident(session, delivery, IncidentType.PROCESSING_FAILURE, now,
                          file_id=file.id, reason=MESSAGES[result.error])
        record_event(session, delivery, "FileProcessingFailed", now, actor="opsbridge-processing", file=file,
                     error_code=result.error, failure_reason=MESSAGES[result.error], retryable=result.error in RETRYABLE,
                     next_retry_at=(now + RETRY_DELAY).isoformat() if retry else None)
    else:
        _set_status(delivery, file, FileStatus.COMPLETED)
        if incident is not None:
            resolve_incident(session, delivery, incident, now, "A subsequent processing attempt completed.")
        record_event(session, delivery, "FileProcessingCompleted", now, actor="opsbridge-processing", file=file,
                     record_count=result.record_count, debit_count=result.debit_count,
                     credit_count=result.credit_count, zero_count=result.zero_count)


@timed("file_processing")
def process_file(engine, root, delivery_id, file_id, *, clock=None, processor=reconcile) -> bool:
    clock = clock or (lambda: datetime.now(timezone.utc))
    with lifecycle(engine, file_id, namespace="processing:file") as connection:
        if connection is None:
            return False
        with Session(connection, expire_on_commit=False) as session:
            with session.begin():
                delivery, file = _current(session, delivery_id, file_id)
                if file is None or not session.scalar(select(_eligible(clock())).where(File.id == file_id)):
                    return False
                if file.status == FileStatus.PROCESSING:
                    _finish(session, delivery, file, Result(error="WORKER_INTERRUPTED"), clock())
                    return True
                claim = session.scalar(_accepted_claims(file.id).limit(1))
                if claim is None:
                    return False
                file.attempt_count_in_series += 1
                _set_status(delivery, file, FileStatus.PROCESSING)
                record_event(session, delivery, "FileProcessingStarted", clock(), actor="opsbridge-processing", file=file)
            result = processor(accepted_package_directory(delivery.integration_id, claim, root=root), file)
            with session.begin():
                _finish(session, delivery, file, result, clock())
            outcome("file_processing", "failed" if result.error else "completed")
            report("FILE_PROCESSING_FAILED" if result.error else "FILE_PROCESSING_COMPLETED",
                   integration_id=delivery.integration_id, delivery_expectation_id=delivery_id, file_id=file_id)
            return True


def scan_processing(engine, root, *, limit=100):
    with Session(engine) as session:
        jobs = list(session.execute(
            select(DeliveryExpectation.id, File.id)
            .join(File, File.id == DeliveryExpectation.current_file_id)
            .where(_eligible(datetime.now(timezone.utc)),
                   or_(File.status == FileStatus.PROCESSING, _accepted_claims(File.id).exists()))
            .order_by(File.received_at, File.id).limit(limit)
        ))
    return sum(process_file(engine, root, delivery_id, file_id) for delivery_id, file_id in jobs)


def request_reprocessing(session: Session, delivery_id, file_id, actor: str, expected_series: int, *, now=None):
    """Queue a new series for a current file whose retryable failure exhausted its budget."""
    delivery, file = _current(session, delivery_id, file_id)
    if (file is None or file.attempt_series != expected_series or file.status != FileStatus.PROCESSING_FAILED
            or file.attempt_count_in_series != MAX_ATTEMPTS
            or file.processing_error_code not in RETRYABLE or session.scalar(_accepted_claims(file.id).limit(1)) is None):
        return None
    previous_error = file.processing_error_code
    file.attempt_series += 1
    file.attempt_count_in_series = 0
    file.processing_error_code = file.processing_error_message = None
    file.processed_at = None
    _set_status(delivery, file, FileStatus.RECEIVED)
    record_event(session, delivery, "ManualReprocessingRequested", now or datetime.now(timezone.utc),
                 actor=actor, operator=True, file=file, error_code=previous_error)
    return delivery
