"""HTTP router tests stub services; database behavior is tested separately."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timezone
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import backend.app.api.routers.delivery_expectations as delivery_expectation_routes
import backend.app.api.routers.integrations as integration_routes
from backend.app.database import get_db
from backend.app.main import app
from backend.app.security import Principal, authenticated, protected_by_default
from backend.app.models.enums import DeliveryStatus
from backend.app.schemas.delivery_expectation import DeliveryExpectationRead
from backend.app.schemas.integration import IntegrationRead
from backend.app.services.errors import (
    DuplicateDeliveryExpectationError,
    DuplicateIntegrationNameError,
    IntegrationNotFoundError,
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        yield cast(Session, object())

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[protected_by_default] = lambda: None
    app.dependency_overrides[authenticated] = lambda: Principal(uuid4(), 'test-admin', 'ADMIN', '', datetime.now(timezone.utc))
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        for dependency in (get_db, authenticated, protected_by_default):
            app.dependency_overrides.pop(dependency, None)


def _integration_response() -> IntegrationRead:
    now = datetime.now(timezone.utc)
    return IntegrationRead(
        id=uuid4(),
        name="Treasury",
        source_name="synthetic",
        active=True,
        created_at=now,
        updated_at=now,
    )


def _expectation_response(integration_id: UUID) -> DeliveryExpectationRead:
    now = datetime.now(timezone.utc)
    return DeliveryExpectationRead(
        id=uuid4(),
        integration_id=integration_id,
        business_date=date(2025, 1, 2),
        delivery_type="TREASURY_TRANSACTIONS",
        expected_pattern="daily-*.csv",
        deadline_at=datetime(2030, 4, 5, 10, 30, tzinfo=timezone.utc),
        overdue_at=None,
        status=DeliveryStatus.EXPECTED,
        current_file_id=None,
        created_at=now,
        updated_at=now,
    )


def test_create_integration_trims_values_and_returns_created_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _integration_response()
    captured: dict[str, object] = {}

    def fake_create(session: Session, data: object, **kwargs) -> IntegrationRead:
        captured["data"] = data
        return expected

    monkeypatch.setattr(integration_routes, "create_integration", fake_create)
    response = client.post(
        "/integrations",
        json={"name": "  Treasury  ", "source_name": "  synthetic  "},
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(expected.id)
    assert captured["data"].name == "Treasury"
    assert captured["data"].source_name == "synthetic"


def test_integration_router_maps_duplicate_and_rejects_extra_fields(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_duplicate(session: Session, data: object, **kwargs) -> IntegrationRead:
        raise DuplicateIntegrationNameError

    monkeypatch.setattr(integration_routes, "create_integration", raise_duplicate)
    duplicate_response = client.post(
        "/integrations",
        json={"name": "Treasury", "source_name": "synthetic"},
    )
    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {
        "detail": "An integration with this name already exists."
    }

    extra_field_response = client.post(
        "/integrations",
        json={"name": "Treasury", "source_name": "synthetic", "active": False},
    )
    assert extra_field_response.status_code == 422


def test_create_delivery_expectation_maps_errors_and_normalizes_input(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integration_id = uuid4()
    expected = _expectation_response(integration_id)
    captured: dict[str, object] = {}

    def fake_create(session: Session, received_id: UUID, data: object, **kwargs) -> DeliveryExpectationRead:
        captured["integration_id"] = received_id
        captured["data"] = data
        return expected

    monkeypatch.setattr(delivery_expectation_routes, "create_delivery_expectation", fake_create)
    response = client.post(
        f"/integrations/{integration_id}/delivery-expectations",
        json={
            "business_date": "2025-01-02",
            "delivery_type": "TREASURY_TRANSACTIONS",
            "expected_pattern": "  daily-*.csv  ",
            "deadline_at": "2030-04-05T12:30:00+02:00",
        },
    )

    assert response.status_code == 201
    assert captured["integration_id"] == integration_id
    assert captured["data"].delivery_type == "TREASURY_TRANSACTIONS"
    assert captured["data"].expected_pattern == "daily-*.csv"
    assert response.json()["delivery_type"] == "TREASURY_TRANSACTIONS"
    assert captured["data"].deadline_at == datetime(2030, 4, 5, 10, 30, tzinfo=timezone.utc)

    def raise_not_found(session: Session, received_id: UUID, data: object, **kwargs) -> DeliveryExpectationRead:
        raise IntegrationNotFoundError

    monkeypatch.setattr(delivery_expectation_routes, "create_delivery_expectation", raise_not_found)
    not_found_response = client.post(
        f"/integrations/{integration_id}/delivery-expectations",
        json={
            "business_date": "2025-01-02",
            "delivery_type": "TREASURY_TRANSACTIONS",
            "expected_pattern": "daily.csv",
            "deadline_at": "2030-04-05T12:30:00Z",
        },
    )
    assert not_found_response.status_code == 404
    assert not_found_response.json() == {"detail": "Integration not found."}

    def raise_duplicate(session: Session, received_id: UUID, data: object, **kwargs) -> DeliveryExpectationRead:
        raise DuplicateDeliveryExpectationError

    monkeypatch.setattr(delivery_expectation_routes, "create_delivery_expectation", raise_duplicate)
    duplicate_response = client.post(
        f"/integrations/{integration_id}/delivery-expectations",
        json={
            "business_date": "2025-01-02",
            "delivery_type": "TREASURY_TRANSACTIONS",
            "expected_pattern": "daily.csv",
            "deadline_at": "2030-04-05T12:30:00Z",
        },
    )
    assert duplicate_response.status_code == 409


def test_list_routes_pass_filters_and_pagination_to_services(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integration = _integration_response()
    expectation = _expectation_response(integration.id)
    calls: dict[str, object] = {}

    def fake_list_integrations(session: Session, *, limit: int, offset: int) -> list[IntegrationRead]:
        calls["integrations"] = (limit, offset)
        return [integration]

    def fake_list_expectations(
        session: Session,
        *,
        limit: int,
        offset: int,
        integration_id: UUID | None = None,
        status: DeliveryStatus | None = None,
    ) -> list[DeliveryExpectationRead]:
        calls["expectations"] = (limit, offset, integration_id, status)
        return [expectation]

    monkeypatch.setattr(integration_routes, "list_integrations", fake_list_integrations)
    monkeypatch.setattr(delivery_expectation_routes, "list_delivery_expectations", fake_list_expectations)

    integration_response = client.get("/integrations")
    expectation_response = client.get(
        f"/delivery-expectations?integration_id={integration.id}&status=EXPECTED&limit=7&offset=3"
    )

    assert integration_response.status_code == 200
    assert calls["integrations"] == (50, 0)
    assert expectation_response.status_code == 200
    assert calls["expectations"] == (7, 3, integration.id, DeliveryStatus.EXPECTED)
    assert client.get("/integrations?limit=101").status_code == 422
