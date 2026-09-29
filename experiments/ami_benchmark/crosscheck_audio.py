import hashlib
import io
import json
import math
import struct
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

from fetch_references import ROOT

BLOCK_FRAMES = 4096
BANDS = ("start", "middle", "end")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_range(url, first, last):
    error = None
    for attempt in range(5):
        try:
            with urlopen(Request(url, headers={"Range": f"bytes={first}-{last}"}), timeout=35) as response:
                if response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {first}-{last}/"):
                    raise ValueError(f"Incorrect official Content-Range: {response.status} {dict(response.headers)}")
                total = int(response.headers["Content-Range"].split("/")[-1])
                data = response.read()
            if len(data) != last - first + 1:
                raise ValueError(f"Truncated official range {first}-{last}: {len(data)} bytes")
            return data, total
        except (OSError, ValueError) as exc:
            error = exc
            time.sleep(min(attempt + 1, 4))
    raise RuntimeError(f"Failed to verify official range {url} {first}-{last}") from error


def wav_header(prefix, total_bytes):
    if prefix[:4] != b"RIFF" or prefix[8:12] != b"WAVE" or int.from_bytes(prefix[4:8], "little") + 8 != total_bytes:
        raise ValueError("Invalid RIFF/WAVE header or original total bytes")
    with wave.open(io.BytesIO(prefix), "rb") as source:
        params = (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype())
        frames = source.getnframes()
    if params != (1, 2, 16000, "NONE"):
        raise ValueError(f"Unexpected audio format: {params}")
    position = 12
    while position + 8 <= len(prefix):
        size = int.from_bytes(prefix[position + 4:position + 8], "little")
        if prefix[position:position + 4] == b"data":
            data_offset = position + 8
            if size != frames * 2 or data_offset + size > total_bytes:
                raise ValueError("WAV PCM chunk length inconsistent with header")
            return {"channels": params[0], "sample_width_bytes": params[1], "sample_rate_hz": params[2], "sample_count": frames, "data_offset_bytes": data_offset, "data_bytes": size}
        position += 8 + size + size % 2
    raise ValueError("WAV data chunk not found in first 4096 bytes")


def selected_blocks(path, offset_s, duration_s):
    limits = {"start": range(0, min(11, duration_s)), "middle": range(duration_s // 2 - 5, duration_s // 2 + 6), "end": range(duration_s - 11, duration_s)}
    blocks = []
    with wave.open(str(path), "rb") as source:
        for band in BANDS:
            best = None
            for second in limits[band]:
                source.setpos((offset_s + second) * 16000)
                data = source.readframes(BLOCK_FRAMES)
                if len(data) != BLOCK_FRAMES * 2:
                    raise ValueError(f"Selected {band} block beyond source WAV: {path}")
                samples = struct.unpack(f"<{BLOCK_FRAMES}h", data)
                energy = sum(sample * sample for sample in samples)
                if best is None or energy > best[0]:
                    best = (energy, second, data)
            energy, second, data = best
            if math.sqrt(energy / BLOCK_FRAMES) < 250:
                raise ValueError(f"No nontrivial source PCM in {band} band: {path}")
            blocks.append((band, second, data, round(math.sqrt(energy / BLOCK_FRAMES), 3)))
    return blocks


def main():
    inventory = json.loads((ROOT / "source_audio_inventory.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    cases = {case["meeting"]: case for case in manifest["cases"] if case["microphone"] == "Mix-Headset"}
    if len(inventory) != 6 or len(cases) != 6:
        raise ValueError("Expected six distinct Mix-Headset meeting sources")
    report = {"method": "Official HTTP 206 Content-Range; first 4096 WAV bytes then 4096-frame PCM blocks selected independently from maximum-energy second in start/middle/end 11-second bands of each published window; mirror entire-file SHA pinned separately; only spot checks, not entire official file equality", "sources": []}
    for entry in inventory:
        meeting = entry["filename"].split(".")[0]
        case = cases[meeting]
        mirror_path = ROOT / "source_audio" / entry["filename"]
        with mirror_path.open("rb") as file:
            mirror_sha = hashlib.file_digest(file, "sha256").hexdigest()
        if mirror_sha != entry["sha256"] or mirror_sha != case["source_audio_sha256"] or mirror_path.stat().st_size != entry["bytes"]:
            raise ValueError(f"Pinned mirror source changed: {mirror_path}")
        with mirror_path.open("rb") as file:
            mirror_prefix = file.read(4096)
        mirrored = wav_header(mirror_prefix, entry["bytes"])
        official_prefix, official_total = read_range(entry["official_source_url"], 0, 4095)
        official = wav_header(official_prefix, official_total)
        header_matches = official == mirrored and official_total == entry["bytes"]
        record = {"meeting": meeting, "case": case["id"], "official_url": entry["official_source_url"], "mirror_url": entry["download_url"], "mirror_revision": entry["mirror_revision"], "mirror_full_wav_sha256": mirror_sha, "official_total_bytes": official_total, "mirror_total_bytes": entry["bytes"], "header_range": [0, 4095], "official_prefix_sha256": digest(official_prefix), "mirror_prefix_sha256": digest(mirror_prefix), "official_format": official, "mirror_format": mirrored, "header_format_and_full_data_length_match": header_matches, "blocks": []}
        report["sources"].append(record)
        if not header_matches:
            (ROOT / "official_audio_crosscheck.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            raise ValueError(f"Official/mirror header or original length mismatch: {meeting}")
        windows = selected_blocks(mirror_path, case["original_offset_s"], case["duration_s"])
        jobs = [(band, second, data, rms, official["data_offset_bytes"] + (case["original_offset_s"] + second) * 32000) for band, second, data, rms in windows]
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(read_range, entry["official_source_url"], first, first + len(data) - 1) for _, _, data, _, first in jobs]
            for (band, second, expected, rms, first), future in zip(jobs, futures):
                observed, total = future.result()
                matched = total == official_total and observed == expected
                block = {"band": band, "local_offset_s": second, "duration_s": BLOCK_FRAMES / 16000, "mirror_pcm_rms_s16": rms, "official_byte_range": [first, first + len(expected) - 1], "mirror_byte_range": [mirrored["data_offset_bytes"] + (case["original_offset_s"] + second) * 32000, mirrored["data_offset_bytes"] + (case["original_offset_s"] + second) * 32000 + len(expected) - 1], "expected_mirror_pcm_sha256": digest(expected), "observed_official_pcm_sha256": digest(observed), "matched": matched}
                record["blocks"].append(block)
                if not matched:
                    (ROOT / "official_audio_crosscheck.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                    raise ValueError(f"Official/mirror PCM mismatch: {meeting} {band}")
        print(meeting, "official header/length and three nontrivial PCM blocks match", flush=True)
    (ROOT / "official_audio_crosscheck.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS six original WAV formats and eighteen official-versus-mirror PCM blocks", flush=True)


if __name__ == "__main__":
    main()
