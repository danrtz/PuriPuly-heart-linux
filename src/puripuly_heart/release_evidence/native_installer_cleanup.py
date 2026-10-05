from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LEGACY_SCHEMA = "puripuly-heart/legacy-pyinstaller-ownership/v1"
NATIVE_SCHEMA = "puripuly-heart/native-artifact-manifest/v1"
PLAN_SCHEMA = "puripuly-heart/native-installer-cleanup/v1"
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_RESERVED = re.compile(
    r"(?:CON|CONIN\$|CONOUT\$|CLOCK\$|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])(?: *\.| *$)",
    re.IGNORECASE,
)


def normalize_windows_relative(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("ownership paths must be nonempty strings")
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    for part in parts:
        if (
            not part
            or part in {".", ".."}
            or part[-1] in " ."
            or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
            or _RESERVED.match(part)
        ):
            raise ValueError(f"unsafe Windows relative ownership path: {value!r}")
    return normalized


def preserved_user_path(value: str) -> bool:
    root = normalize_windows_relative(value).split("/", 1)[0].casefold()
    return (
        root.split(".", 1)[0] in {"settings", "secrets", "prompts", "extensions", "models"}
        or root == ".env"
        or root.startswith(".env.")
    )


@dataclass(frozen=True)
class OwnedFile:
    path: str
    bytes: int
    sha256: str

    @property
    def key(self) -> str:
        return self.path.casefold()

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "bytes": self.bytes, "sha256": self.sha256}


def read_inventory(payload: dict[str, Any], schema: str) -> dict[str, OwnedFile]:
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        raise ValueError(f"expected manifest schema {schema}")
    inventory = payload.get("inventory")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("manifest inventory must be a nonempty list")
    result: dict[str, OwnedFile] = {}
    for row in inventory:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise ValueError("inventory entries must contain exactly path, bytes and sha256")
        path = normalize_windows_relative(row["path"])
        size = row["bytes"]
        digest = row["sha256"]
        if type(size) is not int or not 0 <= size <= 2**63 - 1:
            raise ValueError(f"invalid inventory size for {path}")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError(f"invalid SHA256 for {path}")
        owned = OwnedFile(path, size, digest.lower())
        if owned.key in result:
            raise ValueError(f"case-insensitive duplicate inventory path: {path}")
        result[owned.key] = owned
    for key in result:
        parts = key.split("/")
        for index in range(1, len(parts)):
            if "/".join(parts[:index]) in result:
                raise ValueError(f"inventory file is also a directory ancestor: {key}")
    return result


def obsolete_owned_files(legacy: dict[str, Any], native: dict[str, Any]) -> tuple[OwnedFile, ...]:
    old = read_inventory(legacy, LEGACY_SCHEMA)
    new = read_inventory(native, NATIVE_SCHEMA)
    obsolete = {
        key: row for key, row in old.items() if key not in new and not preserved_user_path(row.path)
    }
    for key in new:
        parts = key.split("/")
        for index in range(1, len(parts)):
            if "/".join(parts[:index]) in obsolete:
                raise ValueError(f"obsolete file conflicts with a new directory: {key}")
    for key in obsolete:
        parts = key.split("/")
        for index in range(1, len(parts)):
            if "/".join(parts[:index]) in new:
                raise ValueError(f"new file conflicts with an obsolete directory: {key}")
    return tuple(obsolete[key] for key in sorted(obsolete))


def cleanup_plan(legacy_bytes: bytes, native_bytes: bytes) -> dict[str, Any]:
    legacy = json.loads(legacy_bytes)
    native = json.loads(native_bytes)
    owned = obsolete_owned_files(legacy, native)
    old = read_inventory(legacy, LEGACY_SCHEMA)
    new = read_inventory(native, NATIVE_SCHEMA)
    preserved = [
        old[key].path
        for key in sorted(old)
        if key not in new and preserved_user_path(old[key].path)
    ]
    directories: set[str] = set()
    for row in owned:
        parts = row.path.split("/")
        directories.update("/".join(parts[:index]) for index in range(1, len(parts)))
    return {
        "schema": PLAN_SCHEMA,
        "legacy_manifest_sha256": hashlib.sha256(legacy_bytes).hexdigest(),
        "native_manifest_sha256": hashlib.sha256(native_bytes).hexdigest(),
        "inventory": [row.as_dict() for row in owned],
        "directories": sorted(directories, key=lambda path: (-path.count("/"), path.casefold())),
        "preserved_paths": preserved,
    }


def render_include(plan: dict[str, Any]) -> str:
    serialized = json.dumps(plan, ensure_ascii=True, separators=(",", ":"))
    chunks = [serialized[index : index + 200] for index in range(0, len(serialized), 200)]
    lines = [
        '#if GetSHA256OfFile(MyPackagedAppDir + "\\native-artifact-manifest.json") != "'
        + plan["native_manifest_sha256"]
        + '"',
        "  #error Native cleanup include does not match the final packaged native artifact manifest. Regenerate it after finalizing the payload.",
        "#endif",
        "procedure WriteNativeCleanupPlan(const FileName: String);",
        "var",
        "  Plan: String;",
        "begin",
        "  Plan := '';",
    ]
    lines.extend("  Plan := Plan + '" + chunk.replace("'", "''") + "';" for chunk in chunks)
    lines.extend(
        [
            "  if not SaveStringToFile(FileName, Plan, False) then begin",
            "    RaiseException('Cannot write native cleanup ownership plan.');",
            "  end;",
            "end;",
            "",
        ]
    )
    return "\n".join(lines)


def generate_include(legacy_manifest: Path, native_manifest: Path, output: Path) -> dict[str, Any]:
    if output.resolve() in {legacy_manifest.resolve(), native_manifest.resolve()}:
        raise ValueError("cleanup output must not overwrite an input manifest")
    plan = cleanup_plan(legacy_manifest.read_bytes(), native_manifest.read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_include(plan), encoding="utf-8")
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-manifest", required=True, type=Path)
    parser.add_argument("--native-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    plan = generate_include(args.legacy_manifest, args.native_manifest, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "obsolete_files": len(plan["inventory"]),
                "preserved_paths": plan["preserved_paths"],
                "native_manifest_sha256": plan["native_manifest_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
