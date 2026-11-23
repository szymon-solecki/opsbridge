"""Exercise authorization independently of browser visibility."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from backend.app import security
from backend.app.api.routers import auth
from backend.app.database import get_db
from backend.app.main import app


def test_password_hashes_are_salted_and_verify():
    value = "synthetic password used only by this test"
    first, second = security.hash_password(value), security.hash_password(value)
    assert first.startswith("$argon2id$") and first != second and value not in first
    assert security.password_matches(first, value)
    assert not security.password_matches(first, "wrong synthetic value")
    assert not security.password_matches("malformed", value)


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(app, base_url="https://testserver") as value:
            yield value
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("path", ["/dashboard/overview", "/integrations", "/delivery-expectations",
                                 "/dashboard/reconciliation", "/dashboard/stream",
                                 "/dashboard/copilot/status", "/auth/operators"])
def test_all_protected_surfaces_require_a_session(client, path):
    assert client.get(path).status_code == 401


def test_forged_admin_fields_and_legacy_flags_do_not_grant_permissions(client, monkeypatch):
    csrf = security.csrf_for("synthetic")
    principal = security.Principal(uuid4(), "viewer", "VIEWER", csrf, security.now() + timedelta(hours=1))
    monkeypatch.setattr(security, "identity", lambda _: principal)
    monkeypatch.setenv("OPSBRIDGE_ENABLE_INCIDENT_ACK", "1")
    key = str(uuid4())
    headers = {"X-CSRF-Token": csrf, "X-OpsBridge-Local-Demo": "1", "X-Role": "ADMIN"}
    for method, endpoint, data in (
        ("POST", f"/dashboard/incidents/{key}/acknowledge", {}),
        ("POST", f"/dashboard/reconciliation/runs/{key}/rerun", {"confirmed": True, "request_id": key}),
        ("POST", f"/dashboard/deliveries/{key}/reprocess", {"confirmed": True, "attempt_series": 1, "file_id": key}),
        ("PATCH", f"/auth/operators/{principal.id}", {"role": "ADMIN"}),
        ("PUT", "/dashboard/notification-policies", []),
    ):
        assert client.request(method, endpoint, headers=headers, json=data).status_code == 403
    assert client.get("/dashboard/copilot/status").status_code == 200


def test_csrf_required_even_for_admin_and_inputs_are_not_echoed(client, monkeypatch):
    principal = security.Principal(uuid4(), "administrator", "ADMIN", "x" * 64, security.now() + timedelta(hours=1))
    monkeypatch.setattr(security, "identity", lambda _: principal)
    assert client.put("/dashboard/notification-policies", json=[]).status_code == 403
    assert client.put("/dashboard/notification-policies", headers={"X-CSRF-Token": "y" * 64}, json=[]).status_code == 403
    test_secret = "synthetic malformed password marker"
    response = client.post("/auth/login", headers={"X-OpsBridge-Login": "1"},
                           json={"username": "administrator", "password": [test_secret]})
    assert response.status_code == 422 and test_secret not in response.text


def test_fifth_parallel_sign_in_is_throttled_and_slots_are_released(client, monkeypatch):
    entered = Barrier(5)
    release = Event()

    class ParkedSession:
        def begin(self):
            if not release.is_set():
                entered.wait(timeout=10)
                assert release.wait(timeout=10)
            raise HTTPException(401, "Synthetic sign-in rejection")

    monkeypatch.setitem(app.dependency_overrides, get_db, ParkedSession)
    monkeypatch.setattr(auth, "_window", deque())
    monkeypatch.setattr(auth, "_in_flight", 0)

    def sign_in():
        return client.post("/auth/login", headers={"X-OpsBridge-Login": "1"}, json={
            "username": "synthetic", "password": "synthetic test value",
        }).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        requests = [pool.submit(sign_in) for _ in range(4)]
        try:
            entered.wait(timeout=10)
            assert sign_in() == 429
        finally:
            release.set()
        assert [request.result(timeout=10) for request in requests] == [401] * 4
    assert sign_in() == 401
