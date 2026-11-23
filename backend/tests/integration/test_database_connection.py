import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ArgumentError
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from backend.app.config import DATABASE_URL_FROM_PROCESS, normalize_database_url
from backend.app.event_worker import verified_engine


@pytest.mark.integration
def test_postgresql_connection() -> None:
    import os

    if os.environ.get("OPSBRIDGE_RUN_INTEGRATION") != "1":
        pytest.skip("Set OPSBRIDGE_RUN_INTEGRATION=1 to run database integration tests")

    if not DATABASE_URL_FROM_PROCESS:
        pytest.fail("Set DATABASE_URL explicitly in the process environment for integration tests")

    try:
        database_url = normalize_database_url(DATABASE_URL_FROM_PROCESS)
        parsed_url = make_url(database_url)
    except (ArgumentError, ValueError):
        pytest.fail("Integration test DATABASE_URL must use a valid PostgreSQL URL")

    database_name = parsed_url.database
    if database_name != "opsbridge_test":
        pytest.fail("Integration tests require DATABASE_URL to target opsbridge_test")

    engine = create_engine(parsed_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()


@pytest.mark.integration
def test_event_worker_reuses_connection_and_reconnects_after_disconnect(monkeypatch):
    import os

    if os.environ.get("OPSBRIDGE_RUN_INTEGRATION") != "1":
        pytest.skip("Set OPSBRIDGE_RUN_INTEGRATION=1 to run database integration tests")
    if not DATABASE_URL_FROM_PROCESS:
        pytest.fail("An explicit isolated database URL is required")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL_FROM_PROCESS)
    monkeypatch.setenv("OPSBRIDGE_EXPECTED_DATABASE", "opsbridge_test")
    worker = verified_engine(reuse_connection=True)
    try:
        with worker.connect() as connection:
            pid = connection.scalar(text("SELECT pg_backend_pid()"))
        with worker.connect() as connection:
            assert connection.scalar(text("SELECT pg_backend_pid()")) == pid
        control = verified_engine()
        try:
            # Terminate only the checked-in test connection opened above.
            with control.connect() as connection:
                assert connection.scalar(text("SELECT pg_terminate_backend(:pid, 5000)"), {"pid": pid})
        finally:
            control.dispose()
        with worker.connect() as connection:
            assert connection.scalar(text("SELECT pg_backend_pid()")) != pid
            assert connection.scalar(text("SELECT current_database()")) == "opsbridge_test"
    finally:
        worker.dispose()
