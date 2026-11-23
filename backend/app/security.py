"""Central authorization and opaque cookie sessions."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import compare_digest, token_urlsafe
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, select

from backend.app.database import get_sessionmaker
from backend.app.models.security import OperatorAccount, OperatorSession, SecurityAudit

COOKIE = "__Host-opsbridge_session"
LIFETIME = timedelta(hours=8)
ROLES = {"VIEWER": 0, "OPERATOR": 1, "ADMIN": 2}
HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_DUMMY = None
PUBLIC = {("GET", "/health"), ("GET", "/ready"), ("GET", "/metrics"), ("POST", "/auth/login")}


def now():
    return datetime.now(timezone.utc)


def hash_password(password):
    return HASHER.hash(password)


def password_matches(encoded, password):
    try:
        return HASHER.verify(encoded, password)
    except (InvalidHashError, VerificationError):
        return False


def dummy_password_check(password):
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password(token_urlsafe(32))
    password_matches(_DUMMY, password)


def digest(token):
    return sha256(token.encode("ascii")).hexdigest()


def csrf_for(token):
    return digest("csrf:" + token)


@dataclass(frozen=True)
class Principal:
    id: UUID
    username: str
    role: str
    csrf: str
    expires_at: datetime


def identity(token):
    if not token or len(token) != 43 or not token.isascii():
        return None
    with get_sessionmaker()() as session:
        row = session.execute(
            select(OperatorAccount.id, OperatorAccount.username, OperatorAccount.role, OperatorSession.expires_at)
            .join(OperatorSession, OperatorSession.operator_id == OperatorAccount.id)
            .where(OperatorSession.digest == digest(token), OperatorSession.expires_at > now(), OperatorAccount.active)
        ).one_or_none()
        return Principal(row.id, row.username, row.role, csrf_for(token), row.expires_at) if row else None


def authenticated(request: Request):
    cached = getattr(request.state, "operator_principal", None)
    if cached is not None:
        return cached
    principal = identity(request.cookies.get(COOKIE))
    if principal is None:
        raise HTTPException(401, "Authentication required.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        token = request.headers.get("X-CSRF-Token", "")
        if len(token) != 64 or not token.isascii() or not compare_digest(token, principal.csrf):
            raise HTTPException(403, "CSRF validation failed.")
    request.state.operator_principal = principal
    return principal


def protected_by_default(request: Request, response: Response):
    if (request.method, request.url.path) not in PUBLIC:
        authenticated(request)
        response.headers["Cache-Control"] = "no-store"


def require(minimum):
    def authorize(principal=Depends(authenticated)):
        if ROLES[principal.role] < ROLES[minimum]:
            raise HTTPException(403, "Permission denied.")
        return principal
    return authorize


viewer = require("VIEWER")
operator = require("OPERATOR")
admin = require("ADMIN")


def audit(session, action, operator_id=None, target_id=None):
    session.add(SecurityAudit(action=action, operator_id=operator_id, target_id=target_id))


def new_session(session, operator_id):
    token = token_urlsafe(32)
    expires = now() + LIFETIME
    session.add(OperatorSession(digest=digest(token), operator_id=operator_id, expires_at=expires))
    return token, expires


def revoke(session, operator_id):
    session.execute(delete(OperatorSession).where(OperatorSession.operator_id == operator_id))
