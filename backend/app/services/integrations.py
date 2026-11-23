from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.integration import Integration
from backend.app.security import audit
from backend.app.schemas.integration import IntegrationCreate, IntegrationRead
from backend.app.services.errors import DuplicateIntegrationNameError


def create_integration(session: Session, data: IntegrationCreate, *, operator_id=None) -> IntegrationRead:
    try:
        with session.begin():
            integration = Integration(name=data.name, source_name=data.source_name)
            session.add(integration)
            session.flush()
            if operator_id is not None:
                audit(session, "INTEGRATION_CREATED", operator_id, integration.id)
            response = IntegrationRead.model_validate(integration)
        return response
    except IntegrityError as error:
        if _constraint_name(error) == "uq_integrations_name":
            raise DuplicateIntegrationNameError from None
        raise


def list_integrations(session: Session, *, limit: int, offset: int) -> list[IntegrationRead]:
    integrations = session.scalars(
        select(Integration)
        .order_by(desc(Integration.created_at), desc(Integration.id))
        .limit(limit)
        .offset(offset)
    ).all()
    return [IntegrationRead.model_validate(integration) for integration in integrations]


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None)
