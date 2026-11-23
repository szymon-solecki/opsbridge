"""Authenticate synthetic HTTP clients inside the disposable service namespace."""

import os

import httpx

from backend.app.security import COOKIE


def client(*, username="demo-admin", variable="OPSBRIDGE_DEMO_PASSWORD"):
    api = httpx.Client(base_url="http://127.0.0.1:8000", timeout=10)
    response = api.post("/auth/login", headers={"X-OpsBridge-Login": "1"},
                        json={"username": username, "password": os.environ[variable]})
    response.raise_for_status()
    api.principal = response.json()
    # HTTPX does not apply Chromium's localhost exception for secure cookies.
    api.headers.update({"Cookie": f"{COOKIE}={api.cookies[COOKIE]}", "X-CSRF-Token": api.principal["csrf"]})
    api.cookies.clear()
    return api
