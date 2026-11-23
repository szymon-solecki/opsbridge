from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from backend.app.schemas.delivery_expectation import DeliveryExpectationCreate
from backend.app.schemas.integration import IntegrationCreate


def test_integration_create_trims_required_text() -> None:
    data = IntegrationCreate(name="  Treasury  ", source_name="  simulator  ")

    assert data.name == "Treasury"
    assert data.source_name == "simulator"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "   ", "source_name": "simulator"},
        {"name": "Treasury", "source_name": "\t "},
    ],
)
def test_integration_create_rejects_blank_required_text(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        IntegrationCreate.model_validate(payload)


def test_integration_create_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        IntegrationCreate(name="Treasury", source_name="simulator", active=False)


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "x" * 121, "source_name": "simulator"},
        {"name": "Treasury", "source_name": "x" * 121},
    ],
)
def test_integration_create_respects_column_lengths(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        IntegrationCreate.model_validate(payload)


def test_delivery_expectation_create_trims_pattern_and_normalizes_deadline_to_utc() -> None:
    data = DeliveryExpectationCreate(
        business_date=date(2025, 1, 2),
        delivery_type="TREASURY_TRANSACTIONS",
        expected_pattern="  statement-*.csv  ",
        deadline_at=datetime.fromisoformat("2025-01-02T12:30:00+02:00"),
    )

    assert data.expected_pattern == "statement-*.csv"
    assert data.deadline_at == datetime(2025, 1, 2, 10, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("expected_pattern", ["", "   ", "x" * 256])
def test_delivery_expectation_create_rejects_invalid_pattern(expected_pattern: str) -> None:
    with pytest.raises(ValidationError):
        DeliveryExpectationCreate(
            business_date=date(2025, 1, 2),
            delivery_type="TREASURY_TRANSACTIONS",
            expected_pattern=expected_pattern,
            deadline_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )


def test_delivery_expectation_create_rejects_naive_deadline() -> None:
    with pytest.raises(ValidationError, match="deadline_at must include a timezone"):
        DeliveryExpectationCreate(
            business_date=date(2025, 1, 2),
            delivery_type="TREASURY_TRANSACTIONS",
            expected_pattern="statement.csv",
            deadline_at=datetime(2025, 1, 2, 12, 30),
        )


def test_delivery_expectation_create_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DeliveryExpectationCreate(
            business_date=date(2025, 1, 2),
            delivery_type="TREASURY_TRANSACTIONS",
            expected_pattern="statement.csv",
            deadline_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
            status="COMPLETED",
        )


@pytest.mark.parametrize("delivery_type", ["lowercase", "HAS-DASH", "ÉTAT", "", "A" * 65])
def test_delivery_expectation_create_rejects_invalid_delivery_type(delivery_type: str) -> None:
    with pytest.raises(ValidationError):
        DeliveryExpectationCreate(
            business_date=date(2025, 1, 2),
            delivery_type=delivery_type,
            expected_pattern="statement.csv",
            deadline_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )


def test_delivery_expectation_create_accepts_maximum_delivery_type_length() -> None:
    data = DeliveryExpectationCreate(
        business_date=date(2025, 1, 2),
        delivery_type="A" * 64,
        expected_pattern="statement.csv",
        deadline_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )

    assert data.delivery_type == "A" * 64


def test_delivery_expectation_create_requires_delivery_type() -> None:
    with pytest.raises(ValidationError):
        DeliveryExpectationCreate.model_validate(
            {
                "business_date": "2025-01-02",
                "expected_pattern": "statement.csv",
                "deadline_at": "2025-01-02T00:00:00Z",
            }
        )
