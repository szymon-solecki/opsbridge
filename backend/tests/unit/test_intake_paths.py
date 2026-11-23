from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.app.intake.paths import (
    accepted_claim_directory,
    accepted_package_directory,
    incoming_directory,
    integration_root,
    internal_root,
    quarantine_claim_directory,
    quarantine_package_directory,
    staging_directory,
    unknown_integration_quarantine_directory,
    work_claim_directory,
    work_snapshot_directory,
    work_source_directory,
)


def test_intake_paths_use_canonical_root_and_uuid_components(tmp_path: Path) -> None:
    integration_id = UUID("9e321e35-4257-41bf-9f82-6769772d5859")
    claim_id = UUID("e3d542be-d719-4e3e-92cf-27ac0cac02d1")
    root = tmp_path / "sftp-data"

    assert integration_root(integration_id, root=root) == root / str(integration_id)
    assert staging_directory(integration_id, root=root) == root / str(integration_id) / "staging"
    assert incoming_directory(integration_id, root=root) == root / str(integration_id) / "incoming"
    assert internal_root(root=root) == root / "_opsbridge"
    assert work_claim_directory(integration_id, claim_id, root=root) == (
        root / "_opsbridge" / "work" / str(integration_id) / str(claim_id)
    )
    assert work_source_directory(integration_id, claim_id, root=root) == (
        root / "_opsbridge" / "work" / str(integration_id) / str(claim_id) / "source"
    )
    assert work_snapshot_directory(integration_id, claim_id, root=root) == (
        root / "_opsbridge" / "work" / str(integration_id) / str(claim_id) / "snapshot"
    )
    assert accepted_claim_directory(integration_id, claim_id, root=root) == (
        root / "_opsbridge" / "accepted" / str(integration_id) / str(claim_id)
    )
    assert accepted_package_directory(integration_id, claim_id, root=root) == (
        root / "_opsbridge" / "accepted" / str(integration_id) / str(claim_id) / "package"
    )
    assert quarantine_claim_directory(integration_id, claim_id, root=root) == (
        root / "_opsbridge" / "quarantine" / str(integration_id) / str(claim_id)
    )
    assert quarantine_package_directory(integration_id, claim_id, root=root) == (
        root / "_opsbridge" / "quarantine" / str(integration_id) / str(claim_id) / "package"
    )
    assert unknown_integration_quarantine_directory(integration_id, claim_id, root=root) == (
        root / "_opsbridge" / "quarantine" / str(integration_id) / str(claim_id)
    )


@pytest.mark.parametrize("invalid_id", ["../outside", 42, None])
def test_path_builders_reject_unvalidated_identifiers(invalid_id: object) -> None:
    with pytest.raises(TypeError, match="validated UUID"):
        integration_root(invalid_id)  # type: ignore[arg-type]


def test_production_path_root_is_canonical() -> None:
    from backend.app.intake.paths import SFTP_DATA_ROOT

    assert SFTP_DATA_ROOT == Path("/srv/opsbridge-sftp")

