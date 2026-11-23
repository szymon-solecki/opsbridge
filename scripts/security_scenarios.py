"""Exercise the real API inside the disposable namespace."""

from contextlib import closing
from secrets import token_urlsafe

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.event_worker import verified_engine
from backend.app.models.security import SecurityAudit
from demo_http import client

with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as guest:
    assert guest.get("/dashboard/overview").status_code == 401
    failed = guest.post("/auth/login", headers={"X-OpsBridge-Login": "1"}, json={
        "username": "demo-admin", "password": "deliberately incorrect synthetic password",
    })
    assert failed.status_code == 401

with closing(client()) as admin, closing(client(username="demo-operator", variable="OPSBRIDGE_OPERATOR_PASSWORD")) as operator:
    actor = admin.principal["id"]
    subject = operator.principal["id"]
    endpoint = "/auth/operators/" + subject
    assert operator.get("/auth/operators").status_code == 403
    assert operator.patch(endpoint, json={"role": "ADMIN"}).status_code == 403
    assert admin.patch("/auth/operators/" + actor, json={"role": "VIEWER"}).status_code == 409
    existing = admin.get("/dashboard/notification-policies").json()["rules"]
    assert operator.put("/dashboard/notification-policies", json=existing).status_code == 403
    assert admin.put("/dashboard/notification-policies", json=existing).status_code == 200
    assert admin.patch(endpoint, json={"role": "VIEWER"}).status_code == 200
    assert operator.get("/auth/session").status_code == 401
    assert admin.patch(endpoint, json={"role": "OPERATOR"}).status_code == 200
    created = admin.post("/auth/operators", json={"username": "test-audit-viewer",
                         "password": token_urlsafe(24), "role": "VIEWER"})
    assert created.status_code == 201
    assert admin.patch("/auth/operators/" + created.json()["id"], json={"active": False}).status_code == 200

engine = verified_engine()
try:
    with Session(engine) as session:
        events = set(session.scalars(select(SecurityAudit.action)))
        assert {"LOGIN_SUCCESS", "LOGIN_FAILURE", "ACCOUNT_PROVISIONED", "ROLE_CHANGED",
                "ACCOUNT_CREATED", "ACCOUNT_STATUS_CHANGED",
                "NOTIFICATION_POLICY_CHANGED"} <= events
finally:
    engine.dispose()
print("Authentication verified: audited failures and role changes, session revocation and privileged policy writes.")
