"""Exercise transactional invalidation on the isolated PostgreSQL test database."""

import os
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy.engine import make_url

from backend.app.config import DATABASE_URL_FROM_PROCESS, normalize_database_url
from backend.app.realtime import CHANNEL

pytestmark = pytest.mark.integration


def test_invalidation_is_coalesced_on_commit_and_absent_on_rollback():
    if os.getenv("OPSBRIDGE_RUN_INTEGRATION") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in")
    if not DATABASE_URL_FROM_PROCESS:
        pytest.fail("Explicit test database URL required")
    target = make_url(normalize_database_url(DATABASE_URL_FROM_PROCESS))
    assert target.database == "opsbridge_test" and not target.query
    assert target.host in {"127.0.0.1", "localhost", "postgres"}
    url = target.set(drivername="postgresql").render_as_string(hide_password=False)
    key = uuid4()
    with psycopg.connect(url, autocommit=True) as listener, psycopg.connect(url, autocommit=True) as writer:
        for connection in (listener, writer):
            assert connection.execute("SELECT current_database()").fetchone() == ("opsbridge_test",)
        listener.execute(f"LISTEN {CHANNEL}")
        insert = "INSERT INTO integrations (id, name, source_name) VALUES (%s, %s, 'synthetic')"
        with writer.transaction(force_rollback=True):
            writer.execute(insert, (key, f"rolled-back-{key}"))
        assert list(listener.notifies(timeout=0.2, stop_after=1)) == []
        try:
            with writer.transaction():
                writer.execute(insert, (key, f"committed-{key}"))
                writer.execute("UPDATE integrations SET active = false WHERE id = %s", (key,))
            notifications = list(listener.notifies(timeout=2, stop_after=1))
            assert [(item.channel, item.payload) for item in notifications] == [(CHANNEL, "")]
            assert list(listener.notifies(timeout=0.2, stop_after=1)) == []
        finally:
            writer.execute("DELETE FROM integrations WHERE id = %s", (key,))
