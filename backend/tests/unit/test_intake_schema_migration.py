import importlib.util
from pathlib import Path

from alembic import command
from alembic.config import Config


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "c51f9a6e2d84_add_delivery_type_and_conflict_incidents.py"
)
SPEC = importlib.util.spec_from_file_location("opsbridge_delivery_type_migration", MIGRATION_PATH)
assert SPEC is not None and SPEC.loader is not None
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


def _render_offline_upgrade(monkeypatch, capsys) -> str:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://offline:offline@localhost/opsbridge_test",
    )
    monkeypatch.setenv("OPSBRIDGE_EXPECTED_DATABASE", "opsbridge_test")
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "a84f2c91d6b0:c51f9a6e2d84", sql=True)
    return capsys.readouterr().out


def _render_offline_downgrade(monkeypatch, capsys) -> str:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://offline:offline@localhost/opsbridge_test",
    )
    monkeypatch.setenv("OPSBRIDGE_EXPECTED_DATABASE", "opsbridge_test")
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.downgrade(config, "c51f9a6e2d84:a84f2c91d6b0", sql=True)
    return capsys.readouterr().out


def test_offline_upgrade_renders_backfill_and_data_validation(monkeypatch, capsys) -> None:
    sql = _render_offline_upgrade(monkeypatch, capsys)

    assert "No explicit delivery_type mapping for expectation" in sql
    assert "Treasury Feed" in sql
    assert "treasury-*.csv" in sql
    assert "TREASURY_TRANSACTIONS" in sql
    assert "UPDATE delivery_expectations AS expectation" in sql
    assert "Every existing delivery expectation must have an explicit delivery_type mapping" in sql
    assert "The delivery_type backfill produces duplicate identity" in sql
    assert "GROUP BY integration_id, business_date, delivery_type" in sql


def test_offline_upgrade_renders_constraints_without_a_delivery_type_default(
    monkeypatch, capsys
) -> None:
    sql = _render_offline_upgrade(monkeypatch, capsys)

    assert 'ADD COLUMN delivery_type VARCHAR(64) COLLATE "C"' in sql
    delivery_type_column = next(
        line for line in sql.splitlines() if "ADD COLUMN delivery_type" in line
    )
    assert "DEFAULT" not in delivery_type_column.upper()
    assert "ALTER TABLE delivery_expectations ALTER COLUMN delivery_type SET NOT NULL" in sql
    assert "ck_delivery_expectations_delivery_type_format" in sql
    assert "uq_delivery_expectation_delivery_type" in sql
    assert "ck_incidents_conflict_key_matches_incident_type" in sql
    assert "uq_incidents_conflict_key" in sql


def test_offline_upgrade_preserves_enum_autocommit_order(monkeypatch, capsys) -> None:
    sql = _render_offline_upgrade(monkeypatch, capsys)

    commit_position = sql.index("COMMIT;")
    enum_position = sql.index("ALTER TYPE incident_type ADD VALUE IF NOT EXISTS")
    begin_position = sql.index("BEGIN;", enum_position)
    column_position = sql.index("ADD COLUMN delivery_type")
    assert commit_position < enum_position < begin_position < column_position


def test_offline_downgrade_renders_data_loss_guards_before_drops(monkeypatch, capsys) -> None:
    sql = _render_offline_downgrade(monkeypatch, capsys)

    guard_position = sql.index("DO $opsbridge_downgrade_guard$")
    expectations_guard_position = sql.index("Cannot downgrade while delivery expectations exist")
    conflict_guard_position = sql.index("Cannot downgrade while source delivery ID conflict incident history exists")
    first_drop_position = sql.index("DROP INDEX")
    assert guard_position < expectations_guard_position < conflict_guard_position < first_drop_position


def test_migration_preserves_existing_trigger_protections() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "trg_delivery_events_append_only" not in source
    assert "trg_files_replacement_link_protection" not in source
    assert 'down_revision: Union[str, None] = "a84f2c91d6b0"' in source
    initial_migration = (
        MIGRATION_PATH.parent / "a84f2c91d6b0_create_initial_opsbridge_schema.py"
    ).read_text(encoding="utf-8")
    assert "CREATE TRIGGER trg_delivery_events_append_only" in initial_migration
    assert "CREATE TRIGGER trg_files_replacement_link_protection" in initial_migration
