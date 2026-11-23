import os
import sys
from logging.config import fileConfig
from pathlib import Path

# Capture the confirmation before importing application configuration, which
# loads local .env values for DATABASE_URL.
EXPECTED_DATABASE_FROM_PROCESS = os.getenv("OPSBRIDGE_EXPECTED_DATABASE")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy import pool
from sqlalchemy.engine import Connection, make_url

from backend.app.config import get_database_url, verify_database_target
from backend.app.models import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def require_expected_database() -> str:
    if not EXPECTED_DATABASE_FROM_PROCESS or not EXPECTED_DATABASE_FROM_PROCESS.strip():
        raise RuntimeError("OPSBRIDGE_EXPECTED_DATABASE must be set for Alembic migrations")
    return EXPECTED_DATABASE_FROM_PROCESS


def run_migrations_offline() -> None:
    url = get_database_url()
    expected_database = require_expected_database()
    verify_database_target(expected_database, make_url(url).database)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection, expected_database: str) -> None:
    if connection.in_transaction():
        raise RuntimeError(
            "Alembic requires a connection without an active transaction before configuration"
        )

    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        if not connection.in_transaction():
            raise RuntimeError("Alembic did not start a transaction before migration execution")

        actual_database = connection.execute(text("SELECT current_database()")).scalar_one()
        verify_database_target(expected_database, actual_database)
        context.run_migrations()


def run_migrations_online() -> None:
    expected_database = require_expected_database()
    connectable = create_engine(make_url(get_database_url()), poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            do_run_migrations(connection, expected_database)
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
