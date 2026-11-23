"""Validated local notification policy and deterministic rule selection."""

from functools import lru_cache
import os
from pathlib import Path
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from backend.app.models.enums import IncidentType
from backend.app.models.security import NotificationPolicyDocument


Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
SEVERITY = {
    IncidentType.MISSING_FILE: "HIGH",
    IncidentType.VALIDATION_FAILURE: "MEDIUM",
    IncidentType.PROCESSING_FAILURE: "HIGH",
    IncidentType.SOURCE_DELIVERY_ID_CONFLICT: "CRITICAL",
    IncidentType.RECONCILIATION_FAILURE: "HIGH",
}
LOCAL_PART = re.compile(r"[a-z0-9_+%-]+(?:\.[a-z0-9_+%-]+)*", re.ASCII)
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)


def synthetic_address(value: str) -> str:
    address = value.strip().lower()
    local, separator, domain = address.partition("@")
    labels = domain.split(".")
    if (not separator or len(address) > 254 or not 1 <= len(local) <= 64 or not LOCAL_PART.fullmatch(local)
            or len(labels) < 2 or labels[-1] != "test" or not all(LABEL.fullmatch(label) for label in labels)):
        raise ValueError("A valid synthetic .test recipient is required")
    return address


class PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Recipient(PolicyModel):
    owner: str = Field(min_length=1, max_length=100)
    email: str

    _validate_email = field_validator("email")(synthetic_address)


class Escalation(PolicyModel):
    after_seconds: int = Field(strict=True, ge=1, le=2592000)
    recipients: list[Recipient] = Field(min_length=1, max_length=20)


class Rule(PolicyModel):
    integration_id: UUID | None = None
    incident_type: IncidentType | None = None
    severity: Severity | None = None
    opened: list[Recipient] | None = Field(default=None, max_length=20)
    resolved: list[Recipient] | None = Field(default=None, max_length=20)
    escalations: list[Escalation] | None = Field(default=None, max_length=5)

    @model_validator(mode="after")
    def validate_levels(self):
        delays = [step.after_seconds for step in self.escalations or ()]
        if delays != sorted(set(delays)):
            raise ValueError("Escalation deadlines must increase")
        return self


@lru_cache(maxsize=2)
def _parse(raw: str) -> tuple[Rule, ...]:
    try:
        rules = TypeAdapter(list[Rule]).validate_json(raw)
        keys = {(rule.integration_id, rule.incident_type, rule.severity) for rule in rules}
        if len(keys) != len(rules) or len(rules) > 100:
            raise ValueError
        return tuple(rules)
    except ValueError:
        raise ValueError("Invalid incident notification policy") from None


@lru_cache(maxsize=1)
def _default_policy():
    return _parse(Path(__file__).parents[1].joinpath("notification_policies.json").read_text(encoding="utf-8"))


def policies(session=None) -> tuple[Rule, ...]:
    if session is not None:
        document = session.get(NotificationPolicyDocument, 1)
        if document is not None:
            return tuple(Rule.model_validate(rule) for rule in document.rules)
    override = os.getenv("OPSBRIDGE_NOTIFICATION_POLICIES")
    return _parse(override) if override else _default_policy()


def validate_rules(rules):
    return _parse(TypeAdapter(list[Rule]).dump_json(rules).decode())


def select_recipients(rules, integration_id, incident_type, severity, field):
    def specificity(rule):
        return (rule.integration_id is not None, rule.incident_type is not None, rule.severity is not None)

    matches = [
        rule for rule in rules
        if rule.integration_id in (None, integration_id) and rule.incident_type in (None, incident_type)
        and rule.severity in (None, severity) and getattr(rule, field) is not None
    ]
    return getattr(max(matches, key=specificity), field) if matches else ()


def unique_recipients(recipients):
    return {recipient.email: recipient for recipient in reversed(recipients)}.values()
