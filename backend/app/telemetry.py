"""Bounded metrics and structured operational logs without payloads."""

from contextvars import ContextVar
from functools import wraps
import json
import logging
import os
from datetime import datetime, timezone
from time import monotonic
from uuid import UUID, uuid4

from prometheus_client import Counter, Gauge, Histogram, start_http_server

REQUEST_ID = ContextVar("request_id", default=None)
REQUESTS = Counter("opsbridge_api_requests", "API responses", ("method", "route", "status"))
LATENCY = Histogram("opsbridge_api_duration_seconds", "Time to API response headers", ("method", "route"))
OPERATIONS = Histogram("opsbridge_worker_duration_seconds", "Worker operation duration", ("operation",))
OUTCOMES = Counter("opsbridge_worker_outcomes", "Worker operation outcomes", ("operation", "outcome"))
READY = Gauge("opsbridge_worker_ready", "Last worker dependency or cycle readiness", ("worker",))
IDS = {"integration_id", "delivery_expectation_id", "file_id", "incident_id", "event_id", "claim_id", "job_id", "request_id"}


def correlation_id(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError):
        return None


class JsonFormatter(logging.Formatter):
    def __init__(self, worker):
        super().__init__()
        self.worker = worker

    def format(self, record):
        fields = dict(getattr(record, "safe_fields", {}))
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "worker": self.worker,
            "code": fields.pop("code", "RUNTIME_LOG"),
        }
        data.update(fields)
        return json.dumps(data, separators=(",", ":"))


def configure_logging(worker):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(worker))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "pika"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("pika").setLevel(logging.WARNING)


def report(code, *, level=logging.INFO, **fields):
    safe = {key: correlation_id(value) for key, value in fields.items() if key in IDS}
    safe = {key: value for key, value in safe.items() if value is not None}
    request_id = REQUEST_ID.get()
    if request_id is not None:
        safe.setdefault("request_id", request_id)
    for key in ("route", "method", "status", "duration_ms"):
        if key in fields:
            safe[key] = fields[key]
    logging.getLogger("opsbridge").log(level, code, extra={"safe_fields": {"code": code, **safe}})


def outcome(operation, result):
    OUTCOMES.labels(operation, result).inc()


def timed(operation):
    def decorate(func):
        @wraps(func)
        def measured(*args, **kwargs):
            with OPERATIONS.labels(operation).time():
                try:
                    return func(*args, **kwargs)
                except Exception:
                    outcome(operation, "error")
                    raise
        return measured
    return decorate


def start_worker(worker):
    configure_logging(worker)
    READY.labels(worker).set(0)
    port = os.getenv("OPSBRIDGE_METRICS_PORT")
    if port:
        start_http_server(int(port))
    report("WORKER_STARTED")


class RequestTelemetry:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        request_id = correlation_id(headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")) or str(uuid4())
        token = REQUEST_ID.set(request_id)
        started = monotonic()
        recorded = False

        def observe(status):
            nonlocal recorded
            route = getattr(scope.get("route"), "path", "unmatched")
            method = scope["method"]
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                method = "OTHER"
            duration = monotonic() - started
            REQUESTS.labels(method, route, f"{status // 100}xx").inc()
            LATENCY.labels(method, route).observe(duration)
            path_ids = {"delivery_expectation_id" if key == "delivery_id" else key: value
                        for key, value in scope.get("path_params", {}).items() if key == "delivery_id" or key in IDS}
            report("HTTP_RESPONSE", route=route, method=method, status=status, **path_ids,
                   duration_ms=round(duration * 1000, 2))
            recorded = True

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
                observe(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            if not recorded:
                observe(500)
            raise
        finally:
            REQUEST_ID.reset(token)
