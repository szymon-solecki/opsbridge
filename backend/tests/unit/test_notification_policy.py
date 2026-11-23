from uuid import uuid4

import pytest

from backend.app.models.enums import IncidentType
from backend.app.services.notification_policy import Rule, select_recipients, synthetic_address, unique_recipients
from backend.app.notification_worker import Envelope, send_to_mailpit


def test_policy_selects_event_specific_recipient_override_and_deduplicates():
    integration = uuid4()
    shared = {"owner": "Ops", "email": "ops@opsbridge.test"}
    override = {"owner": "Treasury", "email": "TREASURY@OPSBRIDGE.TEST"}
    rules = [
        Rule(opened=[shared], resolved=[shared]),
        Rule(incident_type="MISSING_FILE", severity="HIGH", opened=[shared]),
        Rule(integration_id=integration, incident_type="MISSING_FILE", opened=[override, override]),
    ]
    args = (rules, integration, IncidentType.MISSING_FILE, "HIGH")
    assert [row.email for row in unique_recipients(select_recipients(*args, "opened"))] == ["treasury@opsbridge.test"]
    assert [row.email for row in select_recipients(*args, "resolved")] == ["ops@opsbridge.test"]
    assert [row.email for row in select_recipients(
        rules, uuid4(), IncidentType.VALIDATION_FAILURE, "MEDIUM", "opened")] == ["ops@opsbridge.test"]


@pytest.mark.parametrize("email", ["x@example.com", "bad..name@opsbridge.test", "a@-bad.test", "operator\n@opsbridge.test"])
def test_synthetic_recipient_validation(email):
    with pytest.raises(ValueError, match="synthetic"):
        synthetic_address(email)


def test_external_smtp_is_rejected_before_connecting(monkeypatch):
    def never_connect(*_, **__):
        pytest.fail("An external SMTP connection was attempted")

    monkeypatch.setattr("smtplib.SMTP", never_connect)
    with pytest.raises(ValueError, match="local Mailpit"):
        send_to_mailpit(Envelope(uuid4(), uuid4(), "ops@opsbridge.test", "OPENED", "HIGH", 0), "smtp.example.test")
