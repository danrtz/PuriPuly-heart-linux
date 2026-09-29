import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
REVISION = "9527b7c64846fb38316a610f32e9d3466bd6d8b7"
BASE = f"https://raw.githubusercontent.com/nttcslab-sp/diar-forced-alignment/{REVISION}/AMI/test"
MEETINGS = tuple(f"{prefix}{suffix}" for prefix in ("EN2002", "ES2004", "IS1009", "TS3003") for suffix in "abcd")


def main():
    root = ROOT / "references" / "source"
    root.mkdir(parents=True, exist_ok=True)
    inventory = []
    for meeting in MEETINGS:
        url = f"{BASE}/{meeting}.rttm"
        with urlopen(url, timeout=90) as response:
            data = response.read()
        text = data.decode("utf-8")
        lines = text.splitlines()
        if not lines or any(len(parts := line.split()) != 10 or parts[0] != "SPEAKER" or parts[1] != meeting for line in lines):
            raise ValueError(f"Malformed pinned reference: {meeting}")
        (root / f"{meeting}.rttm").write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        inventory.append({"meeting": meeting, "reference_url": url, "reference_sha256": digest, "segments": len(lines)})
        print(meeting, len(lines), digest, flush=True)
    (ROOT / "references" / "source_inventory.json").write_text(json.dumps({"repository_revision": REVISION, "files": inventory}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
