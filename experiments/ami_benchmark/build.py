import hashlib
import json
import wave
from decimal import Decimal
from pathlib import Path

from fetch_references import REVISION, ROOT
from fetch_audio import HOST


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            sha.update(block)
    return sha.hexdigest()


def source_data(path, start, duration, output):
    with wave.open(str(path), "rb") as source:
        params = (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype())
        if params != (1, 2, 16000, "NONE"):
            raise ValueError(f"Source must be uncompressed 16-kHz mono 16-bit PCM: {path} {params}")
        if source.getnframes() < (start + duration) * 16000:
            raise ValueError(f"Source shorter than selected window: {path}")
        frames = source.getnframes()
        source.setpos(start * 16000)
        pcm_hash = hashlib.sha256()
        with wave.open(str(output), "wb") as target:
            target.setparams(source.getparams())
            remaining = duration * 16000
            while remaining:
                data = source.readframes(min(remaining, 65536))
                if not data:
                    raise ValueError(f"Unexpected truncated source: {path}")
                target.writeframesraw(data)
                pcm_hash.update(data)
                remaining -= len(data) // 2
        with wave.open(str(output), "rb") as check:
            if check.getnframes() != duration * 16000 or (check.getnchannels(), check.getsampwidth(), check.getframerate()) != (1, 2, 16000):
                raise ValueError(f"Invalid extracted clip: {output}")
        return frames, pcm_hash.hexdigest()


def clipped_reference(meeting, case_id, start, duration):
    first, end = Decimal(start), Decimal(start + duration)
    rows = []
    path = ROOT / "references" / "source" / f"{meeting}.rttm"
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 10 or parts[0] != "SPEAKER" or parts[1] != meeting:
            raise ValueError(f"Invalid source annotation: {line}")
        a, b = Decimal(parts[3]), Decimal(parts[3]) + Decimal(parts[4])
        left, right = max(first, a), min(end, b)
        if left < right:
            parts[1] = case_id
            parts[3] = format(left - first, "f")
            parts[4] = format(right - left, "f")
            rows.append(" ".join(parts))
    if not rows:
        raise ValueError(f"No source annotation for {case_id}")
    return "\n".join(rows) + "\n"


def main():
    selection = json.loads((ROOT / "selection.json").read_text(encoding="utf-8"))
    inventory = json.loads((ROOT / "references" / "source_inventory.json").read_text(encoding="utf-8"))
    if len(selection["cases"]) != 6 or inventory["repository_revision"] != REVISION:
        raise ValueError("Selection/reference revision mismatch")
    by_meeting = {item["meeting"]: item for item in inventory["files"]}
    sources = {item["filename"]: item for item in json.loads((ROOT / "source_audio_inventory.json").read_text(encoding="utf-8"))}
    far_field = json.loads((ROOT / "far_field_inventory.json").read_text(encoding="utf-8"))
    clips = ROOT / "audio"
    refs = ROOT / "references" / "cases"
    clips.mkdir(exist_ok=True)
    refs.mkdir(exist_ok=True)
    cases = selection["cases"] + [{**next(item for item in selection["cases"] if item["id"] == "overlap_heavy"), "id": "far_field_pair"}]
    manifest = {"benchmark": "AMItest-derived scenario subset", "split": "AMI/test", "reference_repository_revision": REVISION, "reference_kind": "third-party forced-aligned annotation, not manually validated clip labels", "selection_sha256": digest(ROOT / "selection.json"), "cases": []}
    for case in cases:
        meeting = case["meeting"]
        if meeting not in by_meeting:
            raise ValueError(f"Not a test meeting: {meeting}")
        reference_file = ROOT / "references" / "source" / f"{meeting}.rttm"
        if digest(reference_file) != by_meeting[meeting]["reference_sha256"]:
            raise ValueError(f"Changed source reference: {meeting}")
        mic = "Array1-01" if case["id"] == "far_field_pair" else "Mix-Headset"
        filename = f"{meeting}.{mic}.wav"
        output = clips / f"{case['id']}.wav"
        if mic == "Mix-Headset":
            if filename not in sources:
                raise ValueError(f"Unpinned original WAV: {filename}")
            original = ROOT / "source_audio" / filename
            if digest(original) != sources[filename]["sha256"]:
                raise ValueError(f"Wrong source audio: {original}")
            frames, pcm_hash = source_data(original, case["start_s"], case["duration_s"], output)
            source_provenance = {"source_audio": original.relative_to(ROOT).as_posix(), "source_audio_url": sources[filename]["official_source_url"], "download_url": sources[filename]["download_url"], "mirror_revision": sources[filename]["mirror_revision"], "source_audio_sha256": sources[filename]["sha256"], "source_sample_count": frames}
        else:
            original = ROOT / far_field["local_pcm"]
            if far_field["filename"] != filename or far_field["start_s"] != case["start_s"] or far_field["duration_s"] != case["duration_s"] or digest(original) != far_field["pcm_sha256"]:
                raise ValueError("Wrong official distant-microphone byte-range source")
            pcm = original.read_bytes()
            if len(pcm) != case["duration_s"] * 16000 * 2 or far_field["byte_range"][1] - far_field["byte_range"][0] + 1 != len(pcm):
                raise ValueError("Invalid distant-microphone PCM extent")
            with wave.open(str(output), "wb") as target:
                target.setnchannels(1)
                target.setsampwidth(2)
                target.setframerate(16000)
                target.writeframes(pcm)
            frames, pcm_hash = far_field["source_sample_count"], far_field["pcm_sha256"]
            source_provenance = {"source_audio": original.relative_to(ROOT).as_posix(), "source_audio_url": far_field["source_url"], "source_byte_range": far_field["byte_range"], "source_audio_sha256": far_field["pcm_sha256"], "source_total_bytes": far_field["source_total_bytes"], "source_wav_header_sha256": far_field["original_wav_header_sha256"], "source_sample_count": frames}
        reference = refs / f"{case['id']}.rttm"
        reference.write_text(clipped_reference(meeting, case["id"], case["start_s"], case["duration_s"]), encoding="utf-8")
        uem = refs / f"{case['id']}.uem"
        uem.write_text(f"{case['id']} 1 0 {case['duration_s']}\n", encoding="utf-8")
        record = {"id": case["id"], "scenario": case["id"], "meeting": meeting, "original_offset_s": case["start_s"], "duration_s": case["duration_s"], "microphone": mic, "pair_with": "overlap_heavy" if mic != "Mix-Headset" else None, "audio": output.relative_to(ROOT).as_posix(), "reference_rttm": reference.relative_to(ROOT).as_posix(), "uem": uem.relative_to(ROOT).as_posix(), **source_provenance, "source_reference_url": by_meeting[meeting]["reference_url"], "source_reference_sha256": by_meeting[meeting]["reference_sha256"], "clip_pcm_sha256": pcm_hash, "clip_wav_sha256": digest(output), "clip_reference_sha256": digest(reference), "uem_sha256": digest(uem), "features": {k: v for k, v in case.items() if k not in ("id", "meeting", "start_s", "duration_s")}}
        manifest["cases"].append(record)
        print(case["id"], meeting, mic, case["start_s"], case["duration_s"], pcm_hash, flush=True)
    published = ROOT / "manifest.json"
    if published.exists() and json.loads(published.read_text(encoding="utf-8")) != manifest:
        raise ValueError("Pinned published manifest differs from available sources or derived clips")
    published.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
