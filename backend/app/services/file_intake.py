"""Apply one claim's domain outcome inside the caller's PostgreSQL transaction."""

from datetime import datetime, timezone
from fnmatch import fnmatchcase
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.app.intake.snapshot import Inspection
from backend.app.models import (
    ActorType, DeliveryEvent, DeliveryExpectation, DeliveryStatus, File, FileStatus,
    Incident, IncidentStatus, IncidentType, IntakeClaim, IntakeClaimStatus, Integration, OutboxEvent,
)
from backend.app.services.conflict_identity import source_delivery_conflict_key
from backend.app.services.incident_notifications import open_incident, resolve_incident


def expectation_query(claim, manifest):
    return select(DeliveryExpectation).where(
        DeliveryExpectation.integration_id == claim.integration_id,
        DeliveryExpectation.business_date == manifest.business_date,
        DeliveryExpectation.delivery_type == manifest.delivery_type,
    )


def _resolve(session, expectation, kind, now, reason, file_id=None):
    query = select(Incident).where(
        Incident.delivery_expectation_id == expectation.id, Incident.incident_type == kind,
        Incident.file_id == file_id, Incident.status != IncidentStatus.RESOLVED,
    ).with_for_update()
    for incident in session.scalars(query):
        resolve_incident(session, expectation, incident, now, reason)


def _event(session, claim, expectation, now, event_type, file_id, **details):
    payload = dict(delivery_expectation_id=str(expectation.id), integration_id=str(claim.integration_id),
                   file_id=str(file_id) if file_id else None, content_hash=claim.content_hash,
                   occurred_at=now.isoformat(), status=expectation.status.value, **details)
    event = DeliveryEvent(id=uuid4(), delivery_expectation_id=expectation.id, file_id=file_id,
                          event_type=event_type, occurred_at=now, actor_type=ActorType.SYSTEM,
                          actor_reference="opsbridge-intake", details=payload)
    session.add(OutboxEvent(delivery_event=event, payload=payload, event_type=(
        event_type if event_type == "SourceDeliveryIdConflict" else "DeliveryStatusChanged"
    )))


def committed_outcome(session: Session, claim: IntakeClaim, inspected: Inspection,
                      count: int | None, csv_error: str | None) -> None:
    if claim.status in (IntakeClaimStatus.COMMITTED, IntakeClaimStatus.FINALIZED):
        raise RuntimeError("Claim already committed")
    claim.error_code = _apply(session, claim, inspected, count, csv_error)
    claim.status = IntakeClaimStatus.COMMITTED


def _apply(session, claim, inspected, count, csv_error):
    manifest = inspected.manifest
    if manifest is None:
        return inspected.error
    expectation = session.scalar(expectation_query(claim, manifest).with_for_update())
    if expectation is None:
        return "EXPECTATION_UNKNOWN"
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"intake:business:{expectation.id}"})
    now = datetime.now(timezone.utc)
    claim.delivery_expectation_id = expectation.id
    claim.content_hash = inspected.digest
    claim.source_delivery_id = manifest.source_delivery_id
    _resolve(session, expectation, IncidentType.MISSING_FILE, now, f"Payload arrived in claim {claim.id}")
    integration = session.get(Integration, claim.integration_id, with_for_update={"read": True})
    if not integration.active:
        return "INTEGRATION_INACTIVE"
    if inspected.error:
        return inspected.error

    files = select(File).where(File.delivery_expectation_id == expectation.id)
    source_id = manifest.source_delivery_id
    if source_id is not None:
        original = session.scalar(files.where(File.source_delivery_id == source_id))
        if original is None:
            # A duplicate may have introduced another exact source ID for an existing file.
            alias = session.scalar(select(IntakeClaim.file_id).where(
                IntakeClaim.delivery_expectation_id == expectation.id,
                IntakeClaim.source_delivery_id.collate("C") == source_id, IntakeClaim.file_id.is_not(None),
                IntakeClaim.error_code.is_(None),
            ).limit(1))
            original = session.get(File, alias) if alias else None
        if original and original.content_hash != inspected.digest:
            key = source_delivery_conflict_key(expectation.id, source_id, inspected.digest)
            if session.scalar(select(Incident.id).where(Incident.conflict_key == key)) is None:
                open_incident(session, expectation, IncidentType.SOURCE_DELIVERY_ID_CONFLICT, now, conflict_key=key,
                              reason="Source delivery ID already identifies different content")
                _event(session, claim, expectation, now, "SourceDeliveryIdConflict", None,
                       error_code="SOURCE_DELIVERY_ID_CONFLICT", existing_file_id=str(original.id),
                       conflict_key=str(key), source_delivery_id=source_id)
            return "SOURCE_DELIVERY_ID_CONFLICT"

    duplicate = session.scalar(files.where(File.content_hash == inspected.digest))
    if duplicate:
        claim.file_id = duplicate.id
        return None
    current = session.get(File, expectation.current_file_id) if expectation.current_file_id else None
    if current and current.status != FileStatus.VALIDATION_FAILED:
        return "UNEXPECTED_DISTINCT_PAYLOAD"

    if not fnmatchcase(manifest.payload.file_name, expectation.expected_pattern):
        csv_error = "FILENAME_PATTERN_MISMATCH"
    status = FileStatus.VALIDATION_FAILED if csv_error else FileStatus.RECEIVED
    received = File(id=uuid4(), delivery_expectation_id=expectation.id, status=status,
                    original_name=manifest.payload.file_name, source_delivery_id=source_id,
                    content_hash=inspected.digest, size_bytes=inspected.size,
                    received_at=claim.created_at, validated_at=now, validation_error_code=csv_error,
                    replaces_file_id=current.id if current else None)
    session.add(received)
    session.flush()
    expectation.current_file_id = claim.file_id = received.id
    expectation.status = DeliveryStatus(status.value)
    if csv_error:
        open_incident(session, expectation, IncidentType.VALIDATION_FAILURE, now,
                      file_id=received.id, reason=csv_error)
    else:
        while current:
            _resolve(session, expectation, IncidentType.VALIDATION_FAILURE, now,
                     f"Replacement {received.id} validated", current.id)
            current = session.get(File, current.replaces_file_id) if current.replaces_file_id else None
    _event(session, claim, expectation, now, "FileValidationFailed" if csv_error else "FileReceived",
           received.id, record_count=count, error_code=csv_error)
    return None
