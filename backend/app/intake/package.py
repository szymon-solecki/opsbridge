"""Safe inspection of the bounded package shape used by file intake."""

from dataclasses import dataclass
import os
from pathlib import Path
import stat


MANIFEST_FILENAME = "manifest.json"
MAX_MANIFEST_SIZE_BYTES = 64 * 1024
MAX_PAYLOAD_SIZE_BYTES = 10 * 1024 * 1024
MAX_PACKAGE_SIZE_BYTES = MAX_MANIFEST_SIZE_BYTES + MAX_PAYLOAD_SIZE_BYTES


class PackageValidationError(ValueError):
    """Raised when a package contains unsafe or unexpected filesystem entries."""


@dataclass(frozen=True)
class PackageInspection:
    """Validated package paths and sizes; payload content remains untrusted."""

    package_directory: Path
    manifest_path: Path
    payload_path: Path
    payload_file_name: str
    manifest_size_bytes: int
    payload_size_bytes: int
    total_size_bytes: int


def is_safe_basename(file_name: str) -> bool:
    """Return whether a name is a safe, single filesystem basename."""
    if not file_name or file_name in {".", ".."}:
        return False
    if file_name != Path(file_name).name:
        return False
    if "/" in file_name or "\\" in file_name or ":" in file_name:
        return False
    return not any(ord(character) < 32 or ord(character) == 127 for character in file_name)


def inspect_package(package_directory: Path) -> PackageInspection:
    """Validate the direct package entries and enforce all byte-size limits."""
    package_directory = Path(package_directory)
    try:
        root_stat = package_directory.lstat()
    except OSError as error:
        raise PackageValidationError("package directory is unavailable") from error
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise PackageValidationError("package path must be a real directory")

    manifest_entry: tuple[str, os.stat_result] | None = None
    payload_entries: list[tuple[str, os.stat_result]] = []
    try:
        with os.scandir(package_directory) as entries:
            for entry in entries:
                if not is_safe_basename(entry.name):
                    raise PackageValidationError("package contains an unsafe filename")
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                except OSError as error:
                    raise PackageValidationError("package entry cannot be inspected") from error
                if not stat.S_ISREG(entry_stat.st_mode) or entry.is_symlink():
                    raise PackageValidationError("package entries must be regular files")

                if entry.name == MANIFEST_FILENAME:
                    if manifest_entry is not None:
                        raise PackageValidationError("package must contain exactly one manifest")
                    manifest_entry = (entry.name, entry_stat)
                elif entry.name.lower().endswith(".csv"):
                    payload_entries.append((entry.name, entry_stat))
                else:
                    raise PackageValidationError("package contains an unexpected entry")
    except PackageValidationError:
        raise
    except OSError as error:
        raise PackageValidationError("package entries cannot be listed") from error

    if manifest_entry is None:
        raise PackageValidationError("package must contain manifest.json")
    if len(payload_entries) != 1:
        raise PackageValidationError("package must contain exactly one CSV payload")

    manifest_name, manifest_stat = manifest_entry
    payload_name, payload_stat = payload_entries[0]
    manifest_size = manifest_stat.st_size
    payload_size = payload_stat.st_size
    if manifest_size > MAX_MANIFEST_SIZE_BYTES:
        raise PackageValidationError("manifest exceeds the 64 KiB limit")
    if payload_size > MAX_PAYLOAD_SIZE_BYTES:
        raise PackageValidationError("payload exceeds the 10 MiB limit")
    total_size = manifest_size + payload_size
    if total_size > MAX_PACKAGE_SIZE_BYTES:
        raise PackageValidationError("package exceeds the total size limit")

    return PackageInspection(
        package_directory=package_directory,
        manifest_path=package_directory / manifest_name,
        payload_path=package_directory / payload_name,
        payload_file_name=payload_name,
        manifest_size_bytes=manifest_size,
        payload_size_bytes=payload_size,
        total_size_bytes=total_size,
    )

