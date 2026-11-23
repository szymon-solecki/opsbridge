"""Trusted-local Copilot endpoints with a bounded provider budget."""

from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from backend.app.database import get_db
from backend.app.services.copilot import ProviderError, analyze, get_provider, provider_mode
from backend.app.services.copilot_evidence import Query, RecordNotFound, UnsupportedQuestion, collect_evidence, parse_question
from backend.app.telemetry import report

router = APIRouter(prefix="/dashboard/copilot", tags=["copilot"])
_window = deque()
_lock = Lock()
_active = 0
MAX_BODY_BYTES = 2048


class Investigation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: UUID | None = None
    reconciliation_run_id: UUID | None = None
    exception_index: int | None = Field(default=None, ge=1, le=40_000)
    question: str | None = Field(default=None, min_length=1, max_length=320)


def resolve_investigation(request: Investigation) -> Query:
    if request.reconciliation_run_id is not None:
        if request.question is not None or request.incident_id is not None:
            raise UnsupportedQuestion
        return Query("reconciliation", request.reconciliation_run_id, request.exception_index)
    if request.exception_index is not None:
        raise UnsupportedQuestion
    if request.question is not None:
        return parse_question(request.question, request.incident_id)
    if request.incident_id is not None:
        return Query("incident", request.incident_id)
    raise UnsupportedQuestion


@contextmanager
def budget():
    global _active
    with _lock:
        now = monotonic()
        while _window and now - _window[0] >= 60:
            _window.popleft()
        if _active >= 4 or len(_window) >= 12:
            raise HTTPException(429, detail="copilot_busy", headers={"Retry-After": "15"})
        _window.append(now)
        _active += 1
    try:
        yield
    finally:
        with _lock:
            _active -= 1


@router.get("/status")
def status():
    return {"provider": provider_mode()}


@router.post("/investigate", openapi_extra={"requestBody": {"required": True,
    "content": {"application/json": {"schema": Investigation.model_json_schema()}}}})
async def investigate(http: Request, session=Depends(get_db)):
    body = bytearray()
    try:
        async for chunk in http.stream():
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                raise HTTPException(413, detail="copilot_request_too_large")
            body.extend(chunk)
        request = Investigation.model_validate_json(body)
    except (ValidationError, ClientDisconnect):
        raise HTTPException(422, detail="invalid_copilot_request") from None
    try:
        query = resolve_investigation(request)
    except UnsupportedQuestion:
        raise HTTPException(422, detail="unsupported_question") from None

    with budget():
        try:
            provider = get_provider()
            evidence = await run_in_threadpool(collect_evidence, session, query, datetime.now(timezone.utc))
            return await analyze(provider, query.kind, evidence)
        except RecordNotFound:
            raise HTTPException(404, detail="evidence_not_found") from None
        except SQLAlchemyError:
            report("COPILOT_EVIDENCE_UNAVAILABLE")
            raise HTTPException(503, detail="evidence_unavailable") from None
        except ProviderError as exc:
            report("COPILOT_PROVIDER_FAILED")
            status_code = {"provider_timeout": 504, "provider_disabled": 503,
                           "provider_unavailable": 503, "invalid_provider_response": 502}[exc.code]
            raise HTTPException(status_code, detail=exc.code) from None
