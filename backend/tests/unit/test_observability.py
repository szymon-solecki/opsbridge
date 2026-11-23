import asyncio
import json
import logging
from uuid import uuid4

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
import pytest

from backend.app import main, monitoring
from backend.app.realtime import DashboardSignal
from backend.app.telemetry import JsonFormatter, REQUEST_ID, outcome, report


@pytest.fixture
def captured_logs(caplog, monkeypatch):
    # Offline Alembic tests configure the root logger in-process.
    logger = logging.getLogger("opsbridge")
    monkeypatch.setattr(logger, "disabled", False)
    monkeypatch.setattr(logger, "propagate", False)
    monkeypatch.setattr(logger, "handlers", [caplog.handler])
    caplog.set_level(logging.INFO, logger="opsbridge")
    return caplog


def test_http_log_correlation_and_metrics(captured_logs):
    request_id = str(uuid4())
    before = REGISTRY.get_sample_value("opsbridge_api_requests_total",
                                       {"method": "GET", "route": "/health", "status": "2xx"}) or 0
    with TestClient(main.app) as client:
        assert client.get("/health?unused=private", headers={"X-Request-ID": request_id}).headers["x-request-id"] == request_id
        assert client.get("/private-missing-url").status_code == 404
    logs = [json.loads(JsonFormatter("api").format(item)) for item in captured_logs.records if item.name == "opsbridge"]
    assert any(item["request_id"] == request_id and item["route"] == "/health" for item in logs), logs
    assert any(item["route"] == "unmatched" and item["status"] == 404 for item in logs)
    assert "private" not in json.dumps(logs)
    assert REGISTRY.get_sample_value("opsbridge_api_requests_total",
                                     {"method": "GET", "route": "/health", "status": "2xx"}) == before + 1
    assert REQUEST_ID.get() is None


def test_logging_does_not_render_arbitrary_messages_and_rejects_invalid_ids(captured_logs):
    identifier = uuid4()
    report("FILE", file_id=identifier, incident_id="not-an-id", payload="private")
    dependency = logging.LogRecord("third-party", logging.WARNING, "", 0, "secret %s", ("value",), None)
    formatted = [json.loads(JsonFormatter("test-worker").format(item)) for item in [*captured_logs.records, dependency]]
    file_log = next((item for item in formatted if item["code"] == "FILE"), None)
    assert file_log and file_log["file_id"] == str(identifier), formatted
    assert "incident_id" not in file_log
    assert any(item["code"] == "RUNTIME_LOG" for item in formatted)
    assert all(word not in json.dumps(formatted) for word in ("secret", "private", "payload"))


def test_readiness_distinguishes_dependency_states(monkeypatch):
    monkeypatch.delenv("RABBITMQ_URL", raising=False)
    monkeypatch.setattr(monitoring, "get_engine", lambda: (_ for _ in ()).throw(RuntimeError()))
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        reply = client.get("/ready")
        assert reply.status_code == 503
        assert reply.json()["dependencies"] == {
            "database": "unavailable", "schema": "unavailable", "broker": "not_configured",
        }
        monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@127.0.0.1/")
        monkeypatch.setattr(monitoring.pika, "BlockingConnection", lambda _: (_ for _ in ()).throw(OSError()))
        assert client.get("/ready").json()["dependencies"]["broker"] == "unavailable"
        monkeypatch.setattr(main, "dependencies",
                            lambda: {"database": "ready", "schema": "unavailable", "broker": "ready"})
        assert client.get("/ready").status_code == 503
        monkeypatch.setattr(main, "dependencies", lambda: {"database": "ready", "schema": "ready", "broker": "ready"})
        assert client.get("/ready").status_code == 200


def test_metrics_distinguish_durable_outcomes_and_scrape_failure(monkeypatch):
    monkeypatch.setattr(monitoring, "metrics_snapshot", lambda: (
        {"FileReceived": 4}, 2, {"ACCEPTED": 3}, [], {"due": 8, "failed": 1},
        {"STARTED": 1, "FAILED": 2}, {"PENDING": 7},
    ))
    outcome("activity_consume", "dead_letter")
    metrics = monitoring.api_metrics().decode()
    assert 'opsbridge_delivery_events_total{event="FileReceived"} 4.0' in metrics
    assert "opsbridge_processing_retries_total 2.0" in metrics
    assert 'opsbridge_outbox_backlog{state="due"} 8.0' in metrics
    assert 'opsbridge_notification_attempts_total{outcome="FAILED"} 2.0' in metrics
    assert 'opsbridge_notification_jobs{state="PENDING"} 7.0' in metrics
    assert 'opsbridge_worker_outcomes_total{operation="activity_consume",outcome="dead_letter"}' in metrics
    monkeypatch.setattr(monitoring, "metrics_snapshot", lambda: (_ for _ in ()).throw(RuntimeError()))
    metrics = monitoring.api_metrics().decode()
    assert "opsbridge_database_up 0.0" in metrics
    assert "opsbridge_outbox_backlog" not in metrics


def test_stream_invalidates_on_new_connection_and_reports_listener_loss(monkeypatch):
    async def scenario():
        hub = DashboardSignal()
        monkeypatch.setattr(hub, "start", lambda: None)
        hub.connected(True)
        first = hub.stream()
        assert "retry:" in await anext(first)
        assert "event: invalidate" in await anext(first)
        hub.broadcast()
        # A scheduled broadcast is delivered while the generator waits.
        asyncio.get_running_loop().call_soon(hub.broadcast)
        assert "event: invalidate" in await anext(first)
        hub.connected(False)
        assert "event: unavailable" in await anext(first)
        await first.aclose()
        assert not hub.subscribers
        hub.connected(True)
        second = hub.stream()
        await anext(second)
        assert "event: invalidate" in await anext(second)
        await second.aclose()

    asyncio.run(scenario())
