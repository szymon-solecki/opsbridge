"""Copy untrusted package bytes once, then work exclusively from the private copy."""

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import shutil
import stat

from backend.app.intake.manifest import DeliveryManifest, ManifestValidationError, parse_manifest
from backend.app.intake.package import (
    MANIFEST_FILENAME, MAX_MANIFEST_SIZE_BYTES, MAX_PAYLOAD_SIZE_BYTES,
    PackageValidationError, inspect_package, is_safe_basename,
)


@dataclass(frozen=True)
class Inspection:
    manifest: DeliveryManifest | None = None
    digest: str | None = None
    size: int = 0
    error: str | None = None


def sync_directory(path: Path) -> None:
    """Persist directory entries on the Linux worker's filesystem."""
    if os.name == "posix":
        descriptor = os.open(path, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _regular_copy(source: Path, target: Path, limit: int) -> None:
    before = source.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
        raise PackageValidationError("unsafe or oversized package entry")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags | getattr(os, "O_NONBLOCK", 0))
    except PermissionError as exc:
        raise PackageValidationError("unreadable source entry") from exc
    with os.fdopen(descriptor, "rb") as src:
        opened = os.fstat(src.fileno())
        if not os.path.samestat(before, opened) or not stat.S_ISREG(opened.st_mode):
            raise PackageValidationError("entry changed during inspection")
        with target.open("xb") as dst:
            total = 0
            while chunk := src.read(min(65536, limit - total + 1)):
                total += len(chunk)
                if total > limit:
                    raise PackageValidationError("entry exceeds size limit")
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        after = os.fstat(src.fileno())
        if (total != before.st_size or opened.st_size != after.st_size
                or opened.st_mtime_ns != after.st_mtime_ns
                or (os.name == "posix" and before.st_ctime_ns != after.st_ctime_ns)
                or not os.path.samestat(after, source.lstat())):
            raise PackageValidationError("entry changed during copy")


def create_snapshot(work: Path) -> Path:
    """The caller owns the private work directory and holds the claim lock."""
    snapshot = work / "snapshot"
    if snapshot.is_dir():
        return snapshot
    source = work / "source"
    initial = source.lstat()
    if not stat.S_ISDIR(initial.st_mode):
        raise PackageValidationError("package must be a directory")
    partial = work / "snapshot.partial"
    if partial.exists():
        shutil.rmtree(partial)  # Contains only worker-created regular files.
    partial.mkdir(mode=0o700)
    names = set()
    try:
        listing = os.scandir(source)
    except PermissionError as exc:
        raise PackageValidationError("unreadable source directory") from exc
    with listing as entries:
        for entry in entries:
            if len(names) == 2 or not is_safe_basename(entry.name):
                raise PackageValidationError("unexpected package entries")
            if entry.name == MANIFEST_FILENAME:
                limit = MAX_MANIFEST_SIZE_BYTES
            elif entry.name.lower().endswith(".csv") and not names - {MANIFEST_FILENAME}:
                limit = MAX_PAYLOAD_SIZE_BYTES
            else:
                raise PackageValidationError("unexpected package entry")
            names.add(entry.name)
            _regular_copy(source / entry.name, partial / entry.name, limit)
    if len(names) != 2 or MANIFEST_FILENAME not in names:
        raise PackageValidationError("incomplete package")
    if source.lstat().st_ctime_ns != initial.st_ctime_ns:
        raise PackageValidationError("package changed during copy")
    sync_directory(partial)
    partial.rename(snapshot)
    sync_directory(work)
    return snapshot


def inspect_snapshot(snapshot: Path) -> Inspection:
    package = inspect_package(snapshot)
    try:
        manifest = parse_manifest(package)
    except ManifestValidationError:
        return Inspection(error="INVALID_MANIFEST")
    # PostgreSQL text cannot represent NUL or unpaired Unicode surrogates.
    for value in (manifest.source_delivery_id or "", manifest.payload.file_name):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return Inspection(error="INVALID_MANIFEST")
        if "\0" in value:
            return Inspection(error="INVALID_MANIFEST")
    digest = sha256()
    with package.payload_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    matches = actual == manifest.payload.sha256 and package.payload_size_bytes == manifest.payload.size_bytes
    return Inspection(manifest, actual, package.payload_size_bytes, None if matches else "INTEGRITY_MISMATCH")
