from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.intake.csv_validation import validate_csv
from backend.app.intake.package import PackageValidationError
from backend.app.intake.paths import accepted_package_directory, quarantine_package_directory, work_claim_directory
from backend.app.intake.snapshot import create_snapshot, inspect_snapshot
from backend.app.intake.worker import finalize


HEADER = b"record_id,record_date,amount,currency,reference\n"


def package(source, data=HEADER, digest=None):
    source.mkdir(parents=True)
    (source / "input.csv").write_bytes(data)
    manifest = dict(contract_version=1, business_date="2026-01-01", delivery_type="DAILY",
                    payload=dict(file_name="input.csv", size_bytes=len(data),
                                 sha256=digest or sha256(data).hexdigest()))
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_private_copy_survives_source_mutation_and_interrupted_copy(tmp_path):
    package(tmp_path / "source")
    partial = tmp_path / "snapshot.partial"
    partial.mkdir()
    (partial / "input.csv").write_bytes(b"partial")
    snapshot = create_snapshot(tmp_path)
    (tmp_path / "source/input.csv").write_bytes(b"changed")
    assert create_snapshot(tmp_path) == snapshot
    assert inspect_snapshot(snapshot).error is None
    assert (snapshot / "input.csv").read_bytes() == HEADER


@pytest.mark.parametrize("change", ["digest", "size"])
def test_snapshot_reports_integrity_mismatch(tmp_path, change):
    package(tmp_path / "source")
    path = tmp_path / "source/manifest.json"
    doc = json.loads(path.read_text())
    doc["payload"]["sha256" if change == "digest" else "size_bytes"] = "0"*64 if change == "digest" else 0
    path.write_text(json.dumps(doc))
    inspected = inspect_snapshot(create_snapshot(tmp_path))
    assert inspected.error == "INTEGRITY_MISMATCH"
    assert inspected.digest == sha256(HEADER).hexdigest()
    assert inspected.manifest.delivery_type == "DAILY"


def test_snapshot_rejects_unexpected_files(tmp_path):
    package(tmp_path / "source")
    (tmp_path / "source/extra").touch()
    with pytest.raises(PackageValidationError):
        create_snapshot(tmp_path)
    assert not (tmp_path / "snapshot").exists()


@pytest.mark.skipif(os.name != "posix", reason="Linux SFTP filesystem")
@pytest.mark.parametrize("kind", ["symlink", "fifo", "hardlink"])
def test_private_copy_refuses_unsafe_payload_entries(tmp_path, kind):
    package(tmp_path / "source")
    path = tmp_path / "source/input.csv"
    original = tmp_path / "original"
    path.rename(original)
    if kind == "symlink":
        path.symlink_to(original)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.hardlink_to(original)
    with pytest.raises(PackageValidationError):
        create_snapshot(tmp_path)
    assert not (tmp_path / "snapshot").exists()
    assert original.read_bytes() == HEADER


@pytest.mark.parametrize(("data", "result"), [
    (HEADER, (0, None)),
    (b"\xef\xbb\xbf" + HEADER + b'id,2024-02-29,-.09,custom,"a,b"\n', (1, None)),
    (b"", (None, "CSV_HEADER_INVALID")),
    (HEADER + b"id,2026-02-29,3,X,x\n", (None, "CSV_ROW_INVALID")),
    (HEADER + b"id,20260101,3,X,x\n", (None, "CSV_ROW_INVALID")),
    (HEADER + b"id,2026-01-01,Infinity,X,x\n", (None, "CSV_ROW_INVALID")),
    (HEADER + b"id,2026-01-01,NaN,X,x\n", (None, "CSV_ROW_INVALID")),
    (HEADER + b'id,2026-01-01,1,X,"unfinished', (None, "CSV_ROW_INVALID")),
])
def test_csv_contract(tmp_path, data, result):
    path = tmp_path / "payload.csv"
    path.write_bytes(data)
    assert validate_csv(path) == result


@pytest.mark.parametrize("error", [None, "INVALID_PACKAGE"])
def test_finalization_resumes_after_either_rename(tmp_path, error):
    integration, claim = uuid4(), uuid4()
    work = work_claim_directory(integration, claim, root=tmp_path)
    package(work / "source")
    candidate = work / "source" if error else create_snapshot(work)
    candidate.rename(work / "package")
    finalize(tmp_path, integration, claim, error)
    finalize(tmp_path, integration, claim, error)
    build = quarantine_package_directory if error else accepted_package_directory
    destination = build(integration, claim, root=tmp_path)
    assert (destination / "input.csv").read_bytes() == HEADER
    assert (destination.parent / "quarantine_reason.json").exists() == bool(error)
