"""Write authoritative operation events and their outbox records atomically."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.models import ActorType, DeliveryEvent, DeliveryExpectation, OutboxEvent
from backend.app.telemetry import REQUEST_ID


def record_event(session: Session, delivery: DeliveryExpectation, kind: str, now: datetime, *,
                 actor: str, operator: bool = False, file=None, **details):
    payload = {
        "delivery_expectation_id": str(delivery.id),
        "integration_id": str(delivery.integration_id),
        "file_id": str(file.id) if file is not None else None,
        "status": delivery.status.value,
        "occurred_at": now.isoformat(),
        **details,
    }
    if file is not None:
        payload.update(attempt_series=file.attempt_series, attempt_count_in_series=file.attempt_count_in_series)
    if request_id := REQUEST_ID.get():
        payload["request_id"] = request_id
    event = DeliveryEvent(
        id=uuid4(), delivery_expectation_id=delivery.id, file_id=file.id if file is not None else None,
        event_type=kind, actor_type=ActorType.OPERATOR if operator else ActorType.SYSTEM,
        actor_reference=actor, occurred_at=now, details=payload,
    )
    session.add(OutboxEvent(
        delivery_event=event, event_type=kind if kind == "DeliveryOverdue" or kind.startswith("Reconciliation")
        else "DeliveryStatusChanged",
        payload=payload,
    ))
