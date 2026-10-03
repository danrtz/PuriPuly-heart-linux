import hashlib
import io
import tarfile

import pytest

from puripuly_heart.release_evidence.linux_managed_gemma_distribution import (
    LinuxRuntimeArchive,
    download_archive,
    extract_runtime,
    prepare_linux_runtime,
)


def test_cached_archive_is_verified_before_use(tmp_path):
    content = b"verified fixture"
    archive = tmp_path / "fixture.tar.gz"
    archive.write_bytes(content)
    contract = LinuxRuntimeArchive(
        "cpu", archive.name, len(content), hashlib.sha256(content).hexdigest()
    )
    assert download_archive(tmp_path, contract) == archive
    archive.write_bytes(b"X" * len(content))
    with pytest.raises(ValueError, match="SHA-256"):
        download_archive(tmp_path, contract)


def test_archive_cannot_escape_staging(tmp_path):
    archive = tmp_path / "malicious.tar.gz"
    with tarfile.open(archive, "w:gz") as target:
        member = tarfile.TarInfo("../../escaped")
        member.size = 1
        target.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(tarfile.FilterError):
        extract_runtime(archive, tmp_path / "runtime")
    assert not (tmp_path.parent / "escaped").exists()


def test_existing_unmanaged_directory_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    target = tmp_path / "runtime"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("existing data")
    with pytest.raises(ValueError, match="unmanaged"):
        prepare_linux_runtime(tmp_path / "cache", target)
    assert sentinel.read_text() == "existing data"
