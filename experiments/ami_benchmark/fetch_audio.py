import hashlib
import json
from urllib.request import urlopen

from fetch_references import ROOT

HOST = "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus"
MIRROR_REVISION = "a249db53de253a3a0a864c93a51d613159dfec7c"
MIRROR = f"https://huggingface.co/datasets/ggfox00000/dia-AMICorpus-all/resolve/{MIRROR_REVISION}"
API = f"https://huggingface.co/api/datasets/ggfox00000/dia-AMICorpus-all/tree/{MIRROR_REVISION}"


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            sha.update(block)
    return sha.hexdigest()


def main():
    cases = json.loads((ROOT / "selection.json").read_text(encoding="utf-8"))["cases"]
    names = {f"{case['meeting']}.Mix-Headset.wav" for case in cases}
    directory = ROOT / "source_audio"
    directory.mkdir(exist_ok=True)
    inventory = []
    for filename in sorted(names):
        meeting = filename.split(".")[0]
        path = directory / filename
        with urlopen(f"{API}/amicorpus/{meeting}/audio", timeout=30) as response:
            listing = json.load(response)
        entry = next((file for file in listing if file["path"].endswith("/" + filename)), None)
        if entry is None or "lfs" not in entry:
            raise ValueError(f"No pinned original WAV in selected mirror: {filename}")
        url = f"{MIRROR}/amicorpus/{meeting}/audio/{filename}"
        if not path.exists() or path.stat().st_size != entry["size"]:
            temp = path.with_suffix(".wav.part")
            with urlopen(url, timeout=90) as response, temp.open("wb") as destination:
                while data := response.read(1024 * 1024):
                    destination.write(data)
            temp.replace(path)
        file_hash = digest(path)
        if path.stat().st_size != entry["size"] or file_hash != entry["lfs"]["oid"]:
            raise ValueError(f"Wrong mirror WAV bytes: {path}")
        inventory.append({"filename": filename, "official_source_url": f"{HOST}/{meeting}/audio/{filename}", "download_url": url, "mirror_revision": MIRROR_REVISION, "sha256": file_hash, "bytes": entry["size"]})
        print(filename, entry["size"], file_hash, flush=True)
    (ROOT / "source_audio_inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
