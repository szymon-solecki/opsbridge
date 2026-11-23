"""Check database session expiration, revocation and audit policy."""

from datetime import timedelta
import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.app import security
from backend.app.config import DATABASE_URL_FROM_PROCESS
from backend.app.event_worker import verified_engine
from backend.app.models.security import OperatorAccount, OperatorSession, SecurityAudit

pytestmark = pytest.mark.integration


def test_persisted_sessions_expire_and_can_be_revoked(monkeypatch):
    if os.getenv("OPSBRIDGE_RUN_INTEGRATION") != "1":
        pytest.skip("Integration tests require opt-in")
    if not DATABASE_URL_FROM_PROCESS:
        pytest.fail("An explicit isolated URL is required")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL_FROM_PROCESS)
    monkeypatch.setenv("OPSBRIDGE_EXPECTED_DATABASE", "opsbridge_test")
    engine = verified_engine()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            factory = lambda: Session(connection, join_transaction_mode="create_savepoint")
            monkeypatch.setattr(security, "get_sessionmaker", lambda: factory)
            with factory() as session, session.begin():
                account = OperatorAccount(username="test-" + uuid4().hex, password_hash="unused",
                                          role="OPERATOR", active=True)
                session.add(account)
                session.flush()
                key = account.id
                token, expires = security.new_session(session, key)
                second, _ = security.new_session(session, key)
                security.audit(session, "LOGIN_SUCCESS", key)
            assert security.identity(token).id == key
            assert security.identity(token).expires_at == expires
            with factory() as session, session.begin():
                assert session.get(OperatorSession, token) is None
                session.get(OperatorSession, security.digest(token)).expires_at = security.now() - timedelta(seconds=1)
                user_audit = session.scalar(select(SecurityAudit.id).where(SecurityAudit.operator_id == key))
                with pytest.raises(DBAPIError, match="audit records are immutable"), session.begin_nested():
                    session.execute(text("DELETE FROM security_audit_events WHERE id = :id"), {"id": user_audit})
            assert security.identity(token) is None
            assert security.identity(second).role == "OPERATOR"
            with factory() as session, session.begin():
                security.revoke(session, key)
            assert security.identity(second) is None
            transaction.rollback()
    finally:
        engine.dispose()
