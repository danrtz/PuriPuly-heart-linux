import hashlib
import io
import json
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, urlopen

from fetch_audio import HOST
from fetch_references import ROOT


def main():
    case = next(item for item in json.loads((ROOT / "selection.json").read_text(encoding="utf-8"))["cases"] if item["id"] == "overlap_heavy")
    meeting = case["meeting"]
    url = f"{HOST}/{meeting}/audio/{meeting}.Array1-01.wav"
    directory = ROOT / "source_audio"
    directory.mkdir(exist_ok=True)
    header_path = directory / f"{meeting}.Array1-01.header.part"
    pcm_path = directory / f"{meeting}.Array1-01.window.pcm"
    inventory_path = ROOT / "far_field_inventory.json"
    if inventory_path.exists() and pcm_path.exists():
        record = json.loads(inventory_path.read_text(encoding="utf-8"))
        if record["source_url"] == url and record["start_s"] == case["start_s"] and record["duration_s"] == case["duration_s"] and hashlib.sha256(pcm_path.read_bytes()).hexdigest() == record["pcm_sha256"]:
            print("Verified cached distant source range", record["pcm_sha256"], flush=True)
            return
    def get_range(first, last):
        error = None
        for attempt in range(5):
            try:
                with urlopen(Request(url, headers={"Range": f"bytes={first}-{last}"}), timeout=35) as response:
                    expected = f"bytes {first}-{last}/"
                    if response.status != 206 or not response.headers.get("Content-Range", "").startswith(expected):
                        raise ValueError(f"Wrong official ranged response: {response.status} {dict(response.headers)}")
                    total = int(response.headers["Content-Range"].split("/")[-1])
                    data = response.read()
                if len(data) != last - first + 1:
                    raise ValueError(f"Truncated source byte range {first}-{last}: {len(data)}")
                return first, data, total
            except (OSError, ValueError) as exc:
                error = exc
                time.sleep(min(attempt + 1, 4))
        raise RuntimeError(f"Official AMI range request {first}-{last} failed after five attempts") from error
    _, header, full_size = get_range(0, 4095)
    header_path.write_bytes(header)
    with wave.open(io.BytesIO(header), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError("Official Array1-01 is not mono 16-kHz s16le PCM")
        frames = audio.getnframes()
    offset = 12
    while offset + 8 <= len(header):
        size = int.from_bytes(header[offset + 4:offset + 8], "little")
        if header[offset:offset + 4] == b"data":
            data_offset = offset + 8
            if size != frames * 2 or data_offset + size != full_size:
                raise ValueError("Unexpected non-PCM suffix or short official WAV")
            break
        offset += 8 + size + (size % 2)
    else:
        raise ValueError("Official WAV header did not include PCM data chunk")
    first = data_offset + case["start_s"] * 16000 * 2
    last = first + case["duration_s"] * 16000 * 2 - 1
    if last >= full_size:
        raise ValueError("Selected far-field window beyond recording")
    pending = pcm_path.with_suffix(".pcm.part")
    with pending.open("wb") as output:
        output.truncate(last - first + 1)
    slices = [(offset, min(offset + 8191, last)) for offset in range(first, last + 1, 8192)]
    with ThreadPoolExecutor(max_workers=32) as pool, pending.open("r+b") as output:
        futures = [pool.submit(get_range, a, b) for a, b in slices]
        for index, completed in enumerate(as_completed(futures), 1):
            offset, data, received_size = completed.result()
            if received_size != full_size:
                raise ValueError("Official WAV size differed between byte-range requests")
            output.seek(offset - first)
            output.write(data)
            if index % 64 == 0 or index == len(slices):
                print("Verified official distant ranges", index, "/", len(slices), flush=True)
    pending.replace(pcm_path)
    record = {"filename": f"{meeting}.Array1-01.wav", "source_url": url, "source_total_bytes": full_size, "source_sample_count": frames, "original_wav_header_sha256": hashlib.sha256(header_path.read_bytes()).hexdigest(), "original_wav_data_offset": data_offset, "start_s": case["start_s"], "duration_s": case["duration_s"], "byte_range": [first, last], "pcm_sha256": hashlib.sha256(pcm_path.read_bytes()).hexdigest(), "local_pcm": pcm_path.relative_to(ROOT).as_posix()}
    inventory_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    header_path.unlink()
    print("Verified official distant-mic PCM range", record, flush=True)


if __name__ == "__main__":
    main()
