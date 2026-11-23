from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.security import admin
from backend.app.models.enums import DeliveryStatus
from backend.app.schemas.delivery_expectation import DeliveryExpectationCreate, DeliveryExpectationRead
from backend.app.services.delivery_expectations import (
    create_delivery_expectation,
    list_delivery_expectations,
)
from backend.app.services.errors import (
    DuplicateDeliveryExpectationError,
    IntegrationNotFoundError,
)


router = APIRouter(tags=["delivery-expectations"])


@router.post(
    "/integrations/{integration_id}/delivery-expectations",
    response_model=DeliveryExpectationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_delivery_expectation_endpoint(
    integration_id: UUID,
    data: DeliveryExpectationCreate,
    session: Session = Depends(get_db),
    principal=Depends(admin),
) -> DeliveryExpectationRead:
    try:
        return create_delivery_expectation(session, integration_id, data, operator_id=principal.id)
    except IntegrationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found.",
        ) from None
    except DuplicateDeliveryExpectationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A delivery expectation with this identity already exists.",
        ) from None


@router.get("/delivery-expectations", response_model=list[DeliveryExpectationRead])
def list_delivery_expectations_endpoint(
    integration_id: UUID | None = None,
    status_filter: DeliveryStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> list[DeliveryExpectationRead]:
    return list_delivery_expectations(
        session,
        limit=limit,
        offset=offset,
        integration_id=integration_id,
        status=status_filter,
    )
