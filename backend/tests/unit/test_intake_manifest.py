import json
from pathlib import Path

import pytest

from backend.app.intake.manifest import ManifestValidationError, parse_manifest
from backend.app.intake.package import MAX_MANIFEST_SIZE_BYTES, PackageInspection, inspect_package


def _manifest_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "contract_version": 1,
        "business_date": "2026-11-18",
        "delivery_type": "TREASURY_TRANSACTIONS",
        "source_delivery_id": "Vendor-Case-Sensitive-01",
        "payload": {
            "file_name": "payload.csv",
            "size_bytes": 3,
            "sha256": "a" * 64,
        },
    }
    document.update(overrides)
    return document


def _write_package(
    tmp_path: Path,
    raw_manifest: str | bytes | None = None,
) -> tuple[Path, PackageInspection]:
    package = tmp_path / "package"
    package.mkdir()
    raw = raw_manifest if raw_manifest is not None else json.dumps(_manifest_document())
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    (package / "manifest.json").write_bytes(raw)
    (package / "payload.csv").write_bytes(b"a,b")
    return package, inspect_package(package)


def test_parse_manifest_accepts_contract_and_preserves_source_id_case(tmp_path: Path) -> None:
    _, inspected = _write_package(tmp_path)

    manifest = parse_manifest(inspected)  # type: ignore[arg-type]

    assert manifest.contract_version == 1
    assert manifest.business_date.isoformat() == "2026-11-18"
    assert manifest.delivery_type == "TREASURY_TRANSACTIONS"
    assert manifest.source_delivery_id == "Vendor-Case-Sensitive-01"
    assert manifest.payload.file_name == "payload.csv"
    assert manifest.payload.size_bytes == 3


@pytest.mark.parametrize("version", ["1", 1.0, True, 2, 0])
def test_parse_manifest_requires_exact_integer_version_one(tmp_path: Path, version: object) -> None:
    document = _manifest_document(contract_version=version)
    _, inspected = _write_package(tmp_path, json.dumps(document))

    with pytest.raises(ManifestValidationError, match="integer 1"):
        parse_manifest(inspected)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("business_date", "2026-2-01"),
        ("business_date", "2026-02-30"),
        ("delivery_type", "lowercase"),
        ("delivery_type", "HAS-DASH"),
        ("delivery_type", "A" * 65),
        ("source_delivery_id", ""),
        ("source_delivery_id", " \t "),
        ("source_delivery_id", "x" * 256),
    ],
)
def test_parse_manifest_rejects_invalid_identity_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    _, inspected = _write_package(tmp_path, json.dumps(_manifest_document(**{field: value})))

    with pytest.raises(ManifestValidationError):
        parse_manifest(inspected)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("size_bytes", True),
        ("size_bytes", 3.0),
        ("size_bytes", -1),
        ("size_bytes", 10 * 1024 * 1024 + 1),
        ("sha256", "A" * 64),
        ("sha256", "a" * 63),
        ("file_name", "../payload.csv"),
        ("file_name", "other.csv"),
    ],
)
def test_parse_manifest_rejects_invalid_payload_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    payload = dict(_manifest_document()["payload"])
    payload[field] = value
    _, inspected = _write_package(tmp_path, json.dumps(_manifest_document(payload=payload)))

    with pytest.raises(ManifestValidationError):
        parse_manifest(inspected)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "raw",
    [
        '{"contract_version":1,"contract_version":1}',
        '{"contract_version":1,"payload":{"file_name":"payload.csv","file_name":"payload.csv"}}',
    ],
)
def test_parse_manifest_rejects_duplicate_keys_at_every_depth(tmp_path: Path, raw: str) -> None:
    _, inspected = _write_package(tmp_path, raw)

    with pytest.raises(ManifestValidationError, match="duplicate JSON object key"):
        parse_manifest(inspected)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "document",
    [
        {**_manifest_document(), "unexpected": "value"},
        {**_manifest_document(), "payload": {**_manifest_document()["payload"], "unexpected": 1}},
    ],
)
def test_parse_manifest_rejects_unknown_fields_at_each_level(
    tmp_path: Path,
    document: dict[str, object],
) -> None:
    _, inspected = _write_package(tmp_path, json.dumps(document))

    with pytest.raises(ManifestValidationError, match="unknown fields"):
        parse_manifest(inspected)  # type: ignore[arg-type]


def test_parse_manifest_rejects_invalid_utf8_and_nonstandard_json_constants(tmp_path: Path) -> None:
    _, inspected = _write_package(tmp_path, b"\xff")
    with pytest.raises(ManifestValidationError, match="UTF-8 JSON"):
        parse_manifest(inspected)  # type: ignore[arg-type]

    other_root = tmp_path / "other"
    other_root.mkdir()
    _, inspected = _write_package(
        other_root,
        json.dumps(_manifest_document()).replace('"contract_version": 1', '"contract_version": NaN'),
    )
    with pytest.raises(ManifestValidationError, match="non-standard JSON"):
        parse_manifest(inspected)  # type: ignore[arg-type]


def test_parse_manifest_converts_deep_json_recursion_error(tmp_path: Path, monkeypatch) -> None:
    # The C decoder's stack budget varies by platform. Exercise the same JSON
    # decoder with the standard library scanner governed by Python's recursion limit.
    monkeypatch.setattr(json.scanner, "make_scanner", json.scanner.py_make_scanner)
    raw = "[" * 2_000 + "0" + "]" * 2_000
    assert len(raw.encode("utf-8")) < MAX_MANIFEST_SIZE_BYTES
    _, inspected = _write_package(tmp_path, raw)

    with pytest.raises(ManifestValidationError, match="manifest JSON exceeds parser limits"):
        parse_manifest(inspected)  # type: ignore[arg-type]


def test_parse_manifest_converts_excessively_long_integer_error(tmp_path: Path) -> None:
    raw = json.dumps(_manifest_document()).replace(
        '"contract_version": 1',
        '"contract_version": ' + ("9" * 5_000),
    )
    assert len(raw.encode("utf-8")) < MAX_MANIFEST_SIZE_BYTES
    _, inspected = _write_package(tmp_path, raw)

    with pytest.raises(ManifestValidationError, match="manifest JSON exceeds parser limits"):
        parse_manifest(inspected)  # type: ignore[arg-type]


def test_parse_manifest_rejects_manifest_that_grows_after_inspection(tmp_path: Path) -> None:
    package, inspected = _write_package(tmp_path)
    with (package / "manifest.json").open("r+b") as stream:
        stream.truncate(64 * 1024 + 1)

    with pytest.raises(ManifestValidationError, match="64 KiB limit"):
        parse_manifest(inspected)  # type: ignore[arg-type]

