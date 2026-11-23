from uuid import UUID, uuid4

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.enums import ActorType, DeliveryStatus
from backend.app.models.event import DeliveryEvent, OutboxEvent
from backend.app.models.integration import DeliveryExpectation, Integration
from backend.app.schemas.delivery_expectation import DeliveryExpectationCreate, DeliveryExpectationRead
from backend.app.telemetry import REQUEST_ID, report
from backend.app.security import audit
from backend.app.services.errors import (
    DuplicateDeliveryExpectationError,
    IntegrationNotFoundError,
)


def create_delivery_expectation(
    session: Session,
    integration_id: UUID,
    data: DeliveryExpectationCreate,
    *, operator_id=None,
) -> DeliveryExpectationRead:
    try:
        with session.begin():
            if session.get(Integration, integration_id) is None:
                raise IntegrationNotFoundError

            expectation = DeliveryExpectation(
                id=uuid4(),
                integration_id=integration_id,
                business_date=data.business_date,
                delivery_type=data.delivery_type,
                expected_pattern=data.expected_pattern,
                deadline_at=data.deadline_at,
                status=DeliveryStatus.EXPECTED,
            )
            session.add(expectation)
            session.flush()

            event_id = uuid4()
            event_payload = {
                "delivery_expectation_id": str(expectation.id),
                "integration_id": str(integration_id),
                "business_date": data.business_date.isoformat(),
                "delivery_type": data.delivery_type,
                "expected_pattern": data.expected_pattern,
                "deadline_at": data.deadline_at.isoformat(),
                "status": DeliveryStatus.EXPECTED.value,
            }
            if request_id := REQUEST_ID.get():
                event_payload["request_id"] = request_id
            session.add(
                DeliveryEvent(
                    id=event_id,
                    delivery_expectation_id=expectation.id,
                    event_type="DeliveryExpectationCreated",
                    actor_type=ActorType.SYSTEM,
                    actor_reference="opsbridge-api",
                    details=event_payload,
                )
            )
            session.add(
                OutboxEvent(
                    id=uuid4(),
                    event_id=event_id,
                    event_type="DeliveryExpectationCreated",
                    payload=event_payload,
                )
            )
            session.flush()
            response = DeliveryExpectationRead.model_validate(expectation)
            if operator_id is not None:
                audit(session, "EXPECTATION_CREATED", operator_id, expectation.id)

        report("EXPECTATION_CREATED", integration_id=integration_id,
               delivery_expectation_id=response.id, event_id=event_id)
        return response
    except IntegrityError as error:
        if _constraint_name(error) == "uq_delivery_expectation_delivery_type":
            raise DuplicateDeliveryExpectationError from None
        raise


def list_delivery_expectations(
    session: Session,
    *,
    limit: int,
    offset: int,
    integration_id: UUID | None = None,
    status: DeliveryStatus | None = None,
) -> list[DeliveryExpectationRead]:
    statement = select(DeliveryExpectation)
    if integration_id is not None:
        statement = statement.where(DeliveryExpectation.integration_id == integration_id)
    if status is not None:
        statement = statement.where(DeliveryExpectation.status == status)

    expectations = session.scalars(
        statement.order_by(desc(DeliveryExpectation.created_at), desc(DeliveryExpectation.id))
        .limit(limit)
        .offset(offset)
    ).all()
    return [DeliveryExpectationRead.model_validate(expectation) for expectation in expectations]


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None)
