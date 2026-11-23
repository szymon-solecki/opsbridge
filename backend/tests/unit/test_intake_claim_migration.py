from pathlib import Path

from alembic import command
from alembic.config import Config


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REVISION = "d2b17c4e806a"
PARENT_REVISION = "c51f9a6e2d84"


def _render(monkeypatch, capsys, operation: str) -> str:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://offline:offline@localhost/opsbridge_test",
    )
    monkeypatch.setenv("OPSBRIDGE_EXPECTED_DATABASE", "opsbridge_test")
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    if operation == "upgrade":
        command.upgrade(config, f"{PARENT_REVISION}:{REVISION}", sql=True)
    else:
        command.downgrade(config, f"{REVISION}:{PARENT_REVISION}", sql=True)
    return capsys.readouterr().out


def test_offline_upgrade_creates_enums_parent_key_claim_table_constraints_and_indexes(
    monkeypatch, capsys
) -> None:
    sql = _render(monkeypatch, capsys, "upgrade")

    assert "CREATE TYPE intake_claim_status AS ENUM" in sql
    assert "CREATE TYPE intake_final_location AS ENUM" in sql
    assert sql.index("CREATE TYPE intake_claim_status") < sql.index("CREATE TABLE intake_claims")
    assert sql.index("CREATE TYPE intake_final_location") < sql.index("CREATE TABLE intake_claims")
    assert sql.index("uq_delivery_expectations_id_integration") < sql.index("CREATE TABLE intake_claims")
    assert "CREATE TABLE intake_claims" in sql
    assert "ck_intake_claims_file_requires_expectation" in sql
    assert "ck_intake_claims_content_hash_sha256_format" in sql
    assert "ck_intake_claims_source_delivery_id_nonblank" in sql
    assert "ck_intake_claims_finalization_fields_match_status" in sql
    assert "fk_intake_claims_expectation_same_integration" in sql
    assert "fk_intake_claims_file_same_expectation" in sql
    assert "ix_intake_claims_status_created_at" in sql
    assert "ix_intake_claims_integration_created_at" in sql
    assert "work_path" not in sql


def test_offline_downgrade_drops_claim_dependencies_before_enum_types(monkeypatch, capsys) -> None:
    sql = _render(monkeypatch, capsys, "downgrade")

    table_drop = sql.index("DROP TABLE intake_claims")
    unique_drop = sql.index("DROP CONSTRAINT uq_delivery_expectations_id_integration")
    final_enum_drop = sql.index("DROP TYPE intake_final_location")
    status_enum_drop = sql.index("DROP TYPE intake_claim_status")
    assert table_drop < unique_drop < final_enum_drop < status_enum_drop
    assert "DROP INDEX ix_intake_claims_integration_created_at" in sql
    assert "DROP INDEX ix_intake_claims_status_created_at" in sql
