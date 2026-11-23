from datetime import date, datetime, timezone
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.models.enums import DeliveryStatus


class DeliveryExpectationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_date: date
    delivery_type: str = Field(min_length=1, max_length=64)
    expected_pattern: str = Field(min_length=1, max_length=255)
    deadline_at: datetime

    @field_validator("delivery_type")
    @classmethod
    def validate_delivery_type(cls, value: str) -> str:
        if re.fullmatch(r"[A-Z0-9_]{1,64}", value, flags=re.ASCII) is None:
            raise ValueError("delivery_type must contain 1 to 64 uppercase ASCII letters, digits, or underscores")
        return value

    @field_validator("expected_pattern", mode="before")
    @classmethod
    def trim_expected_pattern(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("deadline_at")
    @classmethod
    def require_aware_utc_deadline(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deadline_at must include a timezone")
        return value.astimezone(timezone.utc)


class DeliveryExpectationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    integration_id: UUID
    business_date: date
    delivery_type: str
    expected_pattern: str
    deadline_at: datetime
    overdue_at: datetime | None
    status: DeliveryStatus
    current_file_id: UUID | None
    created_at: datetime
    updated_at: datetime
