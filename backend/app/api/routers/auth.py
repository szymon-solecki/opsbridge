"""Authentication and administration for local operator accounts."""

from collections import deque
from datetime import timedelta
from threading import Lock
from time import monotonic
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from backend.app.database import get_db
from backend.app.models.security import OperatorAccount, OperatorSession, SecurityAudit
from backend.app.security import COOKIE, LIFETIME, admin, audit, csrf_for, digest, dummy_password_check, hash_password
from backend.app.security import new_session, now, password_matches, revoke, viewer

router = APIRouter(prefix="/auth", tags=["auth"])
ROLE = Literal["VIEWER", "OPERATOR", "ADMIN"]
USERNAME = r"^[a-z0-9][a-z0-9_.-]{2,63}$"
_window = deque()
_login_lock = Lock()
_in_flight = 0


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Login(Strict):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=256)


class Create(Strict):
    username: str = Field(pattern=USERNAME, max_length=64)
    password: SecretStr = Field(min_length=12, max_length=256)
    role: ROLE


class Change(Strict):
    role: ROLE | None = None
    active: bool | None = None
    password: SecretStr | None = Field(default=None, min_length=12, max_length=256)


@router.post("/login")
def login(body: Login, request: Request, response: Response, session=Depends(get_db),
          x_opsbridge_login: Literal["1"] | None = Header(None)):
    global _in_flight
    if not x_opsbridge_login:
        raise HTTPException(403, "Login requires a same-origin request.")
    with _login_lock:
        at = monotonic()
        while _window and at - _window[0] >= 60:
            _window.popleft()
        if len(_window) >= 60 or _in_flight >= 4:
            raise HTTPException(429, "Too many login attempts. Try again later.")
        _window.append(at)
        _in_flight += 1
    try:
        with session.begin():
            account = session.scalar(select(OperatorAccount)
                                     .where(OperatorAccount.username == body.username.lower()).with_for_update())
            failures = session.scalar(select(func.count()).select_from(SecurityAudit).where(
                SecurityAudit.operator_id == account.id, SecurityAudit.action == "LOGIN_FAILURE",
                SecurityAudit.occurred_at > now() - timedelta(minutes=1),
            )) if account else 0
            accepted = False
            if failures < 5:
                password = body.password.get_secret_value()
                if account and account.active:
                    accepted = password_matches(account.password_hash, password)
                else:
                    dummy_password_check(password)
                audit(session, "LOGIN_SUCCESS" if accepted else "LOGIN_FAILURE", account.id if account else None)
            else:
                audit(session, "LOGIN_THROTTLED", account.id)
            if accepted:
                previous = request.cookies.get(COOKIE)
                if previous and len(previous) == 43 and previous.isascii():
                    session.execute(delete(OperatorSession).where(OperatorSession.digest == digest(previous)))
                session.execute(delete(OperatorSession).where(
                    OperatorSession.operator_id == account.id, OperatorSession.expires_at <= now()))
                token, expires = new_session(session, account.id)
                result = {"id": account.id, "username": account.username, "role": account.role,
                          "csrf": csrf_for(token), "expires_at": expires}
        if not accepted:
            # Same response for known, unknown, inactive, and throttled accounts.
            raise HTTPException(401, "Invalid credentials or temporarily rate limited.")
    finally:
        with _login_lock:
            _in_flight -= 1
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(COOKIE, token, secure=True, httponly=True, samesite="strict", path="/",
                        max_age=int(LIFETIME.total_seconds()))
    return result


@router.get("/session")
def current(response: Response, principal=Depends(viewer)):
    response.headers["Cache-Control"] = "no-store"
    return principal


@router.post("/logout", status_code=204)
def logout(request: Request, principal=Depends(viewer), session=Depends(get_db)):
    with session.begin():
        session.execute(delete(OperatorSession).where(OperatorSession.digest == digest(request.cookies[COOKIE])))
        audit(session, "LOGOUT", principal.id)
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return response


@router.get("/operators")
def accounts(_principal=Depends(admin), session=Depends(get_db)):
    rows = session.execute(select(OperatorAccount.id, OperatorAccount.username, OperatorAccount.role,
                                  OperatorAccount.active).order_by(OperatorAccount.username).limit(200))
    return [dict(row._mapping) for row in rows]


def _account_view(account):
    return {"id": account.id, "username": account.username, "role": account.role, "active": account.active}


@router.post("/operators", status_code=201)
def create(body: Create, principal=Depends(admin), session=Depends(get_db)):
    try:
        with session.begin():
            account = OperatorAccount(username=body.username, role=body.role, active=True,
                                      password_hash=hash_password(body.password.get_secret_value()))
            session.add(account)
            session.flush()
            audit(session, "ACCOUNT_CREATED", principal.id, account.id)
            return _account_view(account)
    except IntegrityError as error:
        if getattr(getattr(error.orig, "diag", None), "constraint_name", None) == "uq_operator_accounts_username":
            raise HTTPException(409, "Username already exists.") from None
        raise


@router.patch("/operators/{operator_id}")
def change(operator_id: UUID, body: Change, principal=Depends(admin), session=Depends(get_db)):
    with session.begin():
        session.execute(text("SELECT pg_advisory_xact_lock(104857670)"))
        # Recheck the acting admin after serializing concurrent privilege changes.
        actor = session.get(OperatorAccount, principal.id)
        if actor is None or not actor.active or actor.role != "ADMIN":
            raise HTTPException(403, "Permission denied.")
        account = session.get(OperatorAccount, operator_id, with_for_update=True)
        if account is None:
            raise HTTPException(404, "Operator not found.")
        if operator_id == principal.id and (body.active is False or body.role not in {None, "ADMIN"}):
            raise HTTPException(409, "Administrators cannot remove their own administrative access.")
        if body.role is not None and body.role != account.role:
            account.role = body.role
            audit(session, "ROLE_CHANGED", principal.id, operator_id)
        if body.active is not None and body.active != account.active:
            account.active = body.active
            audit(session, "ACCOUNT_STATUS_CHANGED", principal.id, operator_id)
        if body.password is not None:
            account.password_hash = hash_password(body.password.get_secret_value())
            audit(session, "PASSWORD_RESET", principal.id, operator_id)
        if session.is_modified(account):
            revoke(session, operator_id)
        return _account_view(account)
