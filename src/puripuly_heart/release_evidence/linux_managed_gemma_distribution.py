from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from puripuly_heart.core.local_translation.runtime_profile import (
    LLAMA_CPP_BUILD,
    LLAMA_CPP_COMMIT,
    default_llama_runtime_root,
)


@dataclass(frozen=True, slots=True)
class LinuxRuntimeArchive:
    backend: str
    filename: str
    size_bytes: int
    sha256: str


LINUX_ARCHIVES = (
    LinuxRuntimeArchive(
        "cpu",
        "llama-b11537-bin-ubuntu-x64.tar.gz",
        17_801_203,
        "ee03a40fcf16d2ebf88c02f7eac6ae40fbaf332aec18c18651dcd441610a5451",
    ),
    LinuxRuntimeArchive(
        "vulkan",
        "llama-b11537-bin-ubuntu-vulkan-x64.tar.gz",
        31_763_213,
        "81908d169e6a07e115d0fbad7f94acba0597140fad957507c8f9dd75e65f4721",
    ),
)
MANIFEST_FILENAME = "linux-runtime-manifest.json"


def verify_archive(path: Path, contract: LinuxRuntimeArchive) -> None:
    if path.stat().st_size != contract.size_bytes:
        raise ValueError(f"Incorrect archive size: {contract.filename}")
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != contract.sha256:
        raise ValueError(f"Incorrect archive SHA-256: {contract.filename}")


def download_archive(cache_dir: Path, contract: LinuxRuntimeArchive) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / contract.filename
    if destination.is_file():
        verify_archive(destination, contract)
        return destination
    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_BUILD}/{contract.filename}"
    with tempfile.NamedTemporaryFile(dir=cache_dir, delete=False) as target:
        temporary = Path(target.name)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "PuriPulyHeart-Linux"})
            with urllib.request.urlopen(request, timeout=60) as source:
                shutil.copyfileobj(source, target)
            target.flush()
            verify_archive(temporary, contract)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination


def extract_runtime(archive_path: Path, destination: Path) -> None:
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        root = Path(temporary)
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(root, filter="data")
        extracted = root / f"llama-{LLAMA_CPP_BUILD}"
        for filename in ("llama-server", "LICENSE"):
            if not (extracted / filename).is_file():
                raise ValueError(f"Linux runtime is missing {filename}")
        extracted.rename(destination)


def prepare_linux_runtime(cache_dir: Path, output_root: Path) -> Path:
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("The pinned Linux runtime supports x86-64 Linux")
    output_root = output_root.resolve()
    manifest_path = output_root / MANIFEST_FILENAME
    if output_root.exists():
        if not manifest_path.is_file():
            raise ValueError(f"Refusing to replace an unmanaged runtime directory: {output_root}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("build") != LLAMA_CPP_BUILD or manifest.get("commit") != LLAMA_CPP_COMMIT:
            raise ValueError("Existing Linux runtime has a different build identity")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_root.parent) as temporary:
        staged = Path(temporary) / "runtime"
        staged.mkdir()
        records = []
        for contract in LINUX_ARCHIVES:
            archive = download_archive(cache_dir, contract)
            extract_runtime(archive, staged / contract.backend)
            records.append(
                {
                    "backend": contract.backend,
                    "archive": contract.filename,
                    "sha256": contract.sha256,
                }
            )
        (staged / MANIFEST_FILENAME).write_text(
            json.dumps(
                {
                    "build": LLAMA_CPP_BUILD,
                    "commit": LLAMA_CPP_COMMIT,
                    "platform": "linux-x86_64",
                    "archives": records,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        backup = Path(temporary) / "previous"
        if output_root.exists():
            output_root.rename(backup)
        try:
            staged.rename(output_root)
        except BaseException:
            if backup.exists():
                backup.rename(output_root)
            raise
    return output_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare verified native Linux llama.cpp runtimes")
    parser.add_argument("--cache-dir", type=Path, default=Path("build/llama-cache"))
    parser.add_argument("--output-root", type=Path, default=default_llama_runtime_root())
    args = parser.parse_args()
    root = prepare_linux_runtime(args.cache_dir, args.output_root)
    print(
        json.dumps(
            {"runtime_root": str(root), "build": LLAMA_CPP_BUILD, "platform": "linux-x86_64"}
        )
    )


if __name__ == "__main__":
    main()
