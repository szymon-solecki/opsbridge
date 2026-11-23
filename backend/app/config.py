"""Application configuration loaded from the environment and local .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Preserve which URL was supplied by the process before local dotenv loading.
DATABASE_URL_FROM_PROCESS = os.getenv("DATABASE_URL")
load_dotenv(PROJECT_ROOT / ".env")


def normalize_database_url(database_url: str) -> str:
    """Ensure SQLAlchemy uses the psycopg 3 driver for PostgreSQL URLs."""
    value = database_url.strip()
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://") :]
    if value.startswith("postgresql+psycopg://"):
        return value
    raise ValueError("DATABASE_URL must use the PostgreSQL scheme")


def get_database_url() -> str:
    """Return the normalized URL, without including credentials in errors."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url or not database_url.strip():
        raise RuntimeError("DATABASE_URL is not configured")
    return normalize_database_url(database_url)


def verify_database_target(expected_database: str | None, actual_database: str | None) -> None:
    """Fail closed unless an explicit expected database matches the target."""
    if not expected_database or not expected_database.strip():
        raise RuntimeError("OPSBRIDGE_EXPECTED_DATABASE must be set for Alembic migrations")
    if not actual_database:
        raise RuntimeError("Unable to determine the Alembic target database")
    if expected_database != actual_database:
        raise RuntimeError(
            "Refusing Alembic migration: expected database "
            f"{expected_database!r}, connected database {actual_database!r}"
        )
