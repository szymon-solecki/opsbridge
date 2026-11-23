"""Strict parser for the V1 SFTP package manifest."""

from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
import re
import stat

from backend.app.intake.package import (
    MANIFEST_FILENAME,
    MAX_MANIFEST_SIZE_BYTES,
    PackageInspection,
    PackageValidationError,
    is_safe_basename,
)


_DELIVERY_TYPE_PATTERN = re.compile(r"[A-Z0-9_]{1,64}", flags=re.ASCII)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", flags=re.ASCII)


class ManifestValidationError(ValueError):
    """Raised when manifest JSON or fields do not match the V1 contract."""


@dataclass(frozen=True)
class PayloadManifest:
    """Manifest declaration for the package's single CSV payload."""

    file_name: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class DeliveryManifest:
    """Validated V1 delivery identity and payload declaration."""

    contract_version: int
    business_date: date
    delivery_type: str
    source_delivery_id: str | None
    payload: PayloadManifest


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestValidationError("manifest contains a duplicate JSON object key")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise ManifestValidationError("manifest contains a non-standard JSON value")


def _read_manifest_bounded(path: Path, expected_size: int) -> bytes:
    """Read a regular manifest without following links and with a hard byte cap."""
    try:
        before = path.lstat()
    except OSError as error:
        raise ManifestValidationError("manifest is unavailable") from error
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise ManifestValidationError("manifest must be a regular file")
    if before.st_size > MAX_MANIFEST_SIZE_BYTES or before.st_size != expected_size:
        raise ManifestValidationError("manifest size changed or exceeds the 64 KiB limit")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ManifestValidationError("manifest cannot be opened safely") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ManifestValidationError("manifest changed during inspection")
        if opened.st_size > MAX_MANIFEST_SIZE_BYTES or opened.st_size != expected_size:
            raise ManifestValidationError("manifest size changed or exceeds the 64 KiB limit")
        with os.fdopen(descriptor, "rb", closefd=False) as manifest_file:
            content = manifest_file.read(MAX_MANIFEST_SIZE_BYTES + 1)
        if len(content) > MAX_MANIFEST_SIZE_BYTES or len(content) != expected_size:
            raise ManifestValidationError("manifest size changed or exceeds the 64 KiB limit")
        return content
    finally:
        os.close(descriptor)


def _require_exact_fields(
    value: object,
    *,
    required: set[str],
    optional: set[str] | None = None,
    context: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ManifestValidationError(f"{context} must be a JSON object")
    allowed = required | (optional or set())
    actual = set(value)
    if not required <= actual:
        raise ManifestValidationError(f"{context} is missing required fields")
    if actual - allowed:
        raise ManifestValidationError(f"{context} contains unknown fields")
    return value


def parse_manifest(package: PackageInspection) -> DeliveryManifest:
    """Parse and validate the bounded manifest for an inspected package."""
    if package.manifest_path.name != MANIFEST_FILENAME:
        raise ManifestValidationError("manifest filename must be manifest.json")
    content = _read_manifest_bounded(package.manifest_path, package.manifest_size_bytes)
    try:
        text = content.decode("utf-8", errors="strict")
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
        )
    except ManifestValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestValidationError("manifest is not valid UTF-8 JSON") from error
    except (RecursionError, ValueError) as error:
        raise ManifestValidationError("manifest JSON exceeds parser limits") from error

    root = _require_exact_fields(
        document,
        required={"contract_version", "business_date", "delivery_type", "payload"},
        optional={"source_delivery_id"},
        context="manifest",
    )

    version = root["contract_version"]
    if type(version) is not int or version != 1:
        raise ManifestValidationError("contract_version must be the integer 1")

    business_date_value = root["business_date"]
    if not isinstance(business_date_value, str) or _DATE_PATTERN.fullmatch(business_date_value) is None:
        raise ManifestValidationError("business_date must use YYYY-MM-DD format")
    try:
        business_date = date.fromisoformat(business_date_value)
    except ValueError as error:
        raise ManifestValidationError("business_date must be a valid calendar date") from error

    delivery_type = root["delivery_type"]
    if not isinstance(delivery_type, str) or _DELIVERY_TYPE_PATTERN.fullmatch(delivery_type) is None:
        raise ManifestValidationError("delivery_type must contain 1 to 64 uppercase ASCII letters, digits, or underscores")

    source_delivery_id: str | None = None
    if "source_delivery_id" in root:
        source_value = root["source_delivery_id"]
        if not isinstance(source_value, str):
            raise ManifestValidationError("source_delivery_id must be a string when supplied")
        if not source_value.strip() or len(source_value) > 255:
            raise ManifestValidationError("source_delivery_id must be non-empty and at most 255 characters")
        source_delivery_id = source_value

    payload_value = _require_exact_fields(
        root["payload"],
        required={"file_name", "size_bytes", "sha256"},
        context="payload",
    )
    file_name = payload_value["file_name"]
    if not isinstance(file_name, str) or not is_safe_basename(file_name):
        raise ManifestValidationError("payload.file_name must be a safe basename")
    if file_name != package.payload_file_name:
        raise ManifestValidationError("payload.file_name does not match the package CSV entry")

    size_bytes = payload_value["size_bytes"]
    if type(size_bytes) is not int or not 0 <= size_bytes <= 10 * 1024 * 1024:
        raise ManifestValidationError("payload.size_bytes must be an integer within the 10 MiB limit")

    sha256 = payload_value["sha256"]
    if not isinstance(sha256, str) or _SHA256_PATTERN.fullmatch(sha256) is None:
        raise ManifestValidationError("payload.sha256 must be 64 lowercase hexadecimal characters")

    return DeliveryManifest(
        contract_version=version,
        business_date=business_date,
        delivery_type=delivery_type,
        source_delivery_id=source_delivery_id,
        payload=PayloadManifest(file_name=file_name, size_bytes=size_bytes, sha256=sha256),
    )

