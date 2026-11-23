"""Reconciliation workbench API for the trusted isolated workspace."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only

from backend.app.database import get_db
from backend.app.security import ROLES, admin, audit, operator, viewer
from backend.app.models import DeliveryExpectation, Incident, Integration, ReconciliationDefinition, ReconciliationRun
from backend.app.services.matching import RESULTS
from backend.app.services.reconciliation import ACTIVE, RUN_FIELDS, enqueue

router = APIRouter(prefix="/dashboard/reconciliation", tags=["reconciliation"])

RESULT_PAGE_SQL = """
SELECT jsonb_agg(page.item ORDER BY page.ordinality) AS items
FROM (
    SELECT entry.ordinality, jsonb_build_object(
        'index', entry.ordinality,
        'category', entry.result -> 'category',
        'currency', entry.result -> 'currency',
        'difference', entry.result -> 'difference',
        'count_a', jsonb_array_length(entry.result -> 'source_a'),
        'count_b', jsonb_array_length(entry.result -> 'source_b')
    ) AS item
    FROM jsonb_array_elements(reconciliation_runs.report -> 'results')
         WITH ORDINALITY AS entry(result, ordinality)
    WHERE CAST(:category AS text) IS NULL OR entry.result ->> 'category' = :category
    ORDER BY entry.ordinality
    LIMIT :fetch OFFSET :offset
) AS page
"""
RESULT_PAGE = text(RESULT_PAGE_SQL).columns(items=JSONB).scalar_subquery()


class DefinitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    business_date: date
    source_a_delivery_id: UUID
    source_b_delivery_id: UUID
    match_on: Literal["record_id", "reference"] = "reference"
    tolerance: Decimal = Field(default=Decimal("0"), ge=0, max_digits=24, decimal_places=6)
    materiality: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=6)
    exception_limit: int | None = Field(default=None, ge=1, le=40_000)
    incident_on_missing: bool = False
    incident_on_failure: bool = True
    supersedes_run_id: UUID | None = None
    confirmed: bool = False

    @field_validator("tolerance", "materiality", mode="before")
    @classmethod
    def decimal_input(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("Use an exact decimal string or integer.")
        return value


class RerunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    request_id: UUID


def _run_view(run):
    return {field.key: getattr(run, field.key) for field in RUN_FIELDS}


def _source_rows(session, ids):
    rows = session.execute(select(DeliveryExpectation, Integration.name)
        .join(Integration, Integration.id == DeliveryExpectation.integration_id)
        .where(DeliveryExpectation.id.in_(ids))).all()
    return {item.id: (item, name) for item, name in rows}


@router.get("")
def list_runs(limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=10000), session=Depends(get_db),
              principal=Depends(viewer)):
    run = ReconciliationRun
    rows = session.execute(select(run, ReconciliationDefinition.name, run.report["counts"].label("counts"))
                           .options(load_only(*RUN_FIELDS))
                           .join(ReconciliationDefinition, ReconciliationDefinition.id == run.definition_id)
                           .order_by(run.created_at.desc(), run.id.desc()).limit(limit + 1).offset(offset)).all()
    return {"items": [_run_view(item) | {"name": name, "counts": counts} for item, name, counts in rows[:limit]],
            "has_more": len(rows) > limit, "rerun_enabled": ROLES[principal.role] >= ROLES["OPERATOR"]}


@router.get("/runs/{run_id}")
def detail(run_id: UUID, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=40000),
           category: Literal[*RESULTS] | None = None, session=Depends(get_db)):
    statement = (select(ReconciliationRun, ReconciliationRun.report["counts"], ReconciliationRun.report["material"],
                        RESULT_PAGE).options(load_only(*RUN_FIELDS)).where(ReconciliationRun.id == run_id))
    found = session.execute(statement, {"category": category, "fetch": limit + 1, "offset": offset}).one_or_none()
    if found is None:
        raise HTTPException(404, "Reconciliation run not found.")
    run, counts, material, page = found
    page = page or []
    definition = session.get(ReconciliationDefinition, run.definition_id)
    ids = [run.source_a_delivery_id, run.source_b_delivery_id]
    sources = _source_rows(session, ids)
    incident_id = session.scalar(select(Incident.id).where(Incident.reconciliation_run_id == run.id))
    return _run_view(run) | {
        "name": definition.name, "match_on": definition.match_on, "tolerance": str(definition.tolerance),
        "counts": counts, "material": material or False,
        "incident_id": incident_id, "items": page[:limit], "has_more": len(page) > limit,
        "sources": [{"id": key, "integration": sources[key][1], "delivery_type": sources[key][0].delivery_type,
                     "business_date": sources[key][0].business_date, "status": sources[key][0].status}
                    for key in ids],
    }


def _commit_conflicts(exception):
    name = getattr(getattr(exception.orig, "diag", None), "constraint_name", None)
    if name in {"uq_reconciliation_named_source_pair", "uq_reconciliation_active_run", "pk_reconciliation_runs"}:
        raise HTTPException(409, "This source pair or active run already exists.") from None
    raise exception


@router.post("/definitions", status_code=201)
def create_definition(body: DefinitionRequest, session=Depends(get_db), principal=Depends(admin)):
    try:
        with session.begin():
            ids = [body.source_a_delivery_id, body.source_b_delivery_id]
            found = _source_rows(session, ids)
            if len(found) != 2:
                raise HTTPException(422, "Select two existing source deliveries.")
            left, right = (found[key][0] for key in ids)
            if left.integration_id == right.integration_id or any(row.business_date != body.business_date for row in (left, right)):
                raise HTTPException(422, "Sources must be independent and share the reconciliation business date.")
            if body.supersedes_run_id:
                previous = session.scalar(select(ReconciliationRun).options(load_only(*RUN_FIELDS))
                                          .where(ReconciliationRun.id == body.supersedes_run_id))
                if not body.confirmed or previous is None or previous.status in ACTIVE:
                    raise HTTPException(422, "Confirm a completed or failed run to reconcile corrected sources.")
                former_ids = [previous.source_a_delivery_id, previous.source_b_delivery_id]
                former = _source_rows(session, former_ids)
                if any((former[old][0].integration_id, former[old][0].business_date)
                       != (found[new][0].integration_id, body.business_date) for old, new in zip(former_ids, ids, strict=True)):
                    raise HTTPException(422, "Corrected sources must preserve both source integrations and date.")
            definition = ReconciliationDefinition(**body.model_dump(exclude={"business_date", "supersedes_run_id", "confirmed"}))
            session.add(definition)
            session.flush()
            run = enqueue(session, definition, left, datetime.now(timezone.utc), parent_id=body.supersedes_run_id, operator_id=principal.id)
            audit(session, "RECONCILIATION_DEFINITION_CREATED", principal.id, definition.id)
            response = {"definition_id": definition.id, "run_id": run.id}
        return response
    except IntegrityError as error:
        _commit_conflicts(error)


@router.post("/runs/{run_id}/rerun", status_code=202)
def rerun(run_id: UUID, body: RerunRequest, session=Depends(get_db), principal=Depends(operator)):
    try:
        with session.begin():
            original = session.scalar(select(ReconciliationRun).options(load_only(*RUN_FIELDS))
                                      .where(ReconciliationRun.id == run_id))
            if original is None:
                raise HTTPException(404, "Reconciliation run not found.")
            definition = session.get(ReconciliationDefinition, original.definition_id, with_for_update=True)
            existing = session.scalar(select(ReconciliationRun).options(load_only(*RUN_FIELDS))
                                      .where(ReconciliationRun.id == body.request_id))
            if existing:
                if existing.parent_id == run_id:
                    return {"run_id": existing.id}
                raise HTTPException(409, "This request ID is already in use.")
            if original.status in ACTIVE or session.scalar(select(ReconciliationRun.id)
                    .where(ReconciliationRun.definition_id == definition.id, ReconciliationRun.status.in_(ACTIVE)).limit(1)):
                raise HTTPException(409, "A run is already active for this definition.")
            delivery = session.get(DeliveryExpectation, definition.source_a_delivery_id)
            run = enqueue(session, definition, delivery, datetime.now(timezone.utc), parent_id=run_id, run_id=body.request_id, operator_id=principal.id)
            audit(session, "RECONCILIATION_RERUN_QUEUED", principal.id, run.id)
            response = {"run_id": run.id}
        return response
    except IntegrityError as error:
        _commit_conflicts(error)
