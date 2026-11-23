import pytest

from backend.app.config import (
    get_database_url,
    normalize_database_url,
    verify_database_target,
)


def test_normalize_database_url_selects_psycopg_driver() -> None:
    assert normalize_database_url("postgresql://localhost/db") == (
        "postgresql+psycopg://localhost/db"
    )


def test_get_database_url_requires_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL is not configured"):
        get_database_url()


def test_verify_database_target_requires_explicit_expectation() -> None:
    with pytest.raises(RuntimeError, match="OPSBRIDGE_EXPECTED_DATABASE"):
        verify_database_target(None, "opsbridge_test")


def test_verify_database_target_accepts_matching_database_name() -> None:
    verify_database_target("opsbridge_test", "opsbridge_test")


def test_verify_database_target_rejects_database_name_mismatch() -> None:
    with pytest.raises(RuntimeError, match="Refusing Alembic migration"):
        verify_database_target("opsbridge_test", "opsbridge")
