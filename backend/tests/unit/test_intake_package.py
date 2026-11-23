from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from backend.app.intake.package import (
    MAX_MANIFEST_SIZE_BYTES,
    MAX_PACKAGE_SIZE_BYTES,
    MAX_PAYLOAD_SIZE_BYTES,
    PackageValidationError,
    inspect_package,
    is_safe_basename,
)
from backend.app.intake import package as package_module


def _write_package(package: Path, *, payload: bytes = b"id\n") -> None:
    package.mkdir()
    (package / "manifest.json").write_text("{}", encoding="utf-8")
    (package / "payload.csv").write_bytes(payload)


def test_inspect_accepts_one_manifest_and_one_csv(tmp_path: Path) -> None:
    package = tmp_path / "package"
    _write_package(package)

    inspected = inspect_package(package)

    assert inspected.manifest_path.name == "manifest.json"
    assert inspected.payload_file_name == "payload.csv"
    assert inspected.manifest_size_bytes == 2
    assert inspected.payload_size_bytes == 3
    assert inspected.total_size_bytes == 5


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ([], "manifest.json"),
        (["payload.csv"], "manifest.json"),
        (["manifest.json", "one.csv", "two.csv"], "exactly one CSV"),
        (["manifest.json", "payload.csv", "notes.txt"], "unexpected entry"),
    ],
)
def test_inspect_rejects_invalid_package_shape(
    tmp_path: Path,
    entries: list[str],
    message: str,
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    for name in entries:
        if name == "manifest.json":
            (package / name).write_text("{}", encoding="utf-8")
        elif name.endswith(".csv"):
            (package / name).write_text("data", encoding="utf-8")
        else:
            (package / name).write_text("unexpected", encoding="utf-8")

    with pytest.raises(PackageValidationError, match=message):
        inspect_package(package)


@pytest.mark.parametrize("file_name", ["../payload.csv", "folder\\payload.csv", "C:payload.csv", "bad\nname.csv"])
def test_safe_basename_rejects_paths_and_control_characters(file_name: str) -> None:
    assert not is_safe_basename(file_name)


def test_inspect_rejects_directory_entry(tmp_path: Path) -> None:
    package = tmp_path / "package"
    _write_package(package)
    (package / "nested").mkdir()

    with pytest.raises(PackageValidationError, match="regular files"):
        inspect_package(package)


def test_inspect_rejects_symlink_entry_without_following_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "package"
    package.mkdir()

    class FakeEntry:
        def __init__(self, name: str, *, symlink: bool = False) -> None:
            self.name = name
            self.symlink = symlink

        def stat(self, *, follow_symlinks: bool) -> SimpleNamespace:
            assert follow_symlinks is False
            mode = stat.S_IFLNK | 0o777 if self.symlink else stat.S_IFREG | 0o644
            return SimpleNamespace(st_mode=mode, st_size=1)

        def is_symlink(self) -> bool:
            return self.symlink

    class FakeEntries:
        def __enter__(self) -> list[FakeEntry]:
            return [FakeEntry("manifest.json"), FakeEntry("payload.csv", symlink=True)]

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(package_module.os, "scandir", lambda _: FakeEntries())

    with pytest.raises(PackageValidationError, match="regular files"):
        inspect_package(package)


@pytest.mark.parametrize(
    ("manifest_size", "payload_size", "message"),
    [
        (MAX_MANIFEST_SIZE_BYTES + 1, 1, "manifest exceeds"),
        (2, MAX_PAYLOAD_SIZE_BYTES + 1, "payload exceeds"),
    ],
)
def test_inspect_enforces_individual_size_limits_before_reading(
    tmp_path: Path,
    manifest_size: int,
    payload_size: int,
    message: str,
) -> None:
    package = tmp_path / "package"
    _write_package(package)
    manifest = package / "manifest.json"
    payload = package / "payload.csv"
    with manifest.open("r+b") as stream:
        stream.truncate(manifest_size)
    with payload.open("r+b") as stream:
        stream.truncate(payload_size)

    with pytest.raises(PackageValidationError, match=message):
        inspect_package(package)


def test_package_total_limit_is_the_sum_of_bounded_entries() -> None:
    assert MAX_PACKAGE_SIZE_BYTES == MAX_MANIFEST_SIZE_BYTES + MAX_PAYLOAD_SIZE_BYTES

