from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.security import admin
from backend.app.schemas.integration import IntegrationCreate, IntegrationRead
from backend.app.services.errors import DuplicateIntegrationNameError
from backend.app.services.integrations import create_integration, list_integrations


router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.post("", response_model=IntegrationRead, status_code=status.HTTP_201_CREATED)
def create_integration_endpoint(
    data: IntegrationCreate,
    session: Session = Depends(get_db),
    principal=Depends(admin),
) -> IntegrationRead:
    try:
        return create_integration(session, data, operator_id=principal.id)
    except DuplicateIntegrationNameError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An integration with this name already exists.",
        ) from None


@router.get("", response_model=list[IntegrationRead])
def list_integrations_endpoint(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> list[IntegrationRead]:
    return list_integrations(session, limit=limit, offset=offset)
