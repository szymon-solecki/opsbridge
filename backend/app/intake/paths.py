"""Canonical filesystem paths used by the OpsBridge intake worker."""

from pathlib import Path
from uuid import UUID


SFTP_DATA_ROOT = Path("/srv/opsbridge-sftp")
INTERNAL_ROOT_NAME = "_opsbridge"


def _uuid_component(value: UUID) -> str:
    if not isinstance(value, UUID):
        raise TypeError("path identifiers must be validated UUID values")
    return str(value)


def integration_root(integration_id: UUID, *, root: Path = SFTP_DATA_ROOT) -> Path:
    """Return the SFTP chroot directory for a validated integration UUID."""
    return root / _uuid_component(integration_id)


def staging_directory(integration_id: UUID, *, root: Path = SFTP_DATA_ROOT) -> Path:
    """Return the vendor staging directory for an integration."""
    return integration_root(integration_id, root=root) / "staging"


def incoming_directory(integration_id: UUID, *, root: Path = SFTP_DATA_ROOT) -> Path:
    """Return the published package directory for an integration."""
    return integration_root(integration_id, root=root) / "incoming"


def internal_root(*, root: Path = SFTP_DATA_ROOT) -> Path:
    """Return the backend-only directory outside vendor SFTP chroots."""
    return root / INTERNAL_ROOT_NAME


def work_claim_directory(
    integration_id: UUID,
    claim_id: UUID,
    *,
    root: Path = SFTP_DATA_ROOT,
) -> Path:
    """Return the deterministic work directory for a claim."""
    return internal_root(root=root) / "work" / _uuid_component(integration_id) / _uuid_component(claim_id)


def work_source_directory(
    integration_id: UUID,
    claim_id: UUID,
    *,
    root: Path = SFTP_DATA_ROOT,
) -> Path:
    """Return the claimed source-package directory."""
    return work_claim_directory(integration_id, claim_id, root=root) / "source"


def work_snapshot_directory(
    integration_id: UUID,
    claim_id: UUID,
    *,
    root: Path = SFTP_DATA_ROOT,
) -> Path:
    """Return the private snapshot directory for a claim."""
    return work_claim_directory(integration_id, claim_id, root=root) / "snapshot"


def accepted_claim_directory(
    integration_id: UUID,
    claim_id: UUID,
    *,
    root: Path = SFTP_DATA_ROOT,
) -> Path:
    """Return the deterministic accepted-package directory for a claim."""
    return internal_root(root=root) / "accepted" / _uuid_component(integration_id) / _uuid_component(claim_id)


def accepted_package_directory(
    integration_id: UUID,
    claim_id: UUID,
    *,
    root: Path = SFTP_DATA_ROOT,
) -> Path:
    """Return the accepted package path for a claim."""
    return accepted_claim_directory(integration_id, claim_id, root=root) / "package"


def quarantine_claim_directory(
    integration_id: UUID,
    claim_id: UUID,
    *,
    root: Path = SFTP_DATA_ROOT,
) -> Path:
    """Return the deterministic quarantine directory for a claim."""
    return internal_root(root=root) / "quarantine" / _uuid_component(integration_id) / _uuid_component(claim_id)


def quarantine_package_directory(
    integration_id: UUID,
    claim_id: UUID,
    *,
    root: Path = SFTP_DATA_ROOT,
) -> Path:
    """Return the quarantined package path for a claim."""
    return quarantine_claim_directory(integration_id, claim_id, root=root) / "package"


def unknown_integration_quarantine_directory(
    integration_id: UUID,
    upload_token: UUID,
    *,
    root: Path = SFTP_DATA_ROOT,
) -> Path:
    """Return a deterministic filesystem-only quarantine directory."""
    return (
        internal_root(root=root)
        / "quarantine"
        / _uuid_component(integration_id)
        / _uuid_component(upload_token)
    )

