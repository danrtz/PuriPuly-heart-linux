from __future__ import annotations

from hashlib import sha256
import io
import json
import os
from pathlib import Path
import time
import wave

import keyring
import requests

from probe import ROOT, RATE, fixture, metrics

BASE = "https://api.soniox.com/v1"


def main() -> None:
    manifest = json.loads((ROOT / "fixture.json").read_text(encoding="utf-8"))
    pcm, turns, provenance = fixture(manifest)
    key = os.environ.get("SONIOX_API_KEY") or keyring.get_password("puripuly-heart", "soniox_api_key")
    if not key:
        raise RuntimeError("SONIOX_API_KEY/keyring credential unavailable")
    headers = {"Authorization": "Bearer " + key}
    wave_bytes = io.BytesIO()
    with wave.open(wave_bytes, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(pcm)
    requests_made = 0
    file_id = None
    transcription_id = None
    status = None

    def send(method: str, path: str, **kwargs) -> dict:
        nonlocal requests_made
        response = requests.request(method, BASE + path, headers=headers, timeout=30, **kwargs)
        requests_made += 1
        if not response.ok:
            raise RuntimeError(f"Soniox {method} {path} HTTP {response.status_code}: {response.text[:700]}")
        return response.json() if response.content else {}

    try:
        uploaded = send("POST", "/files", files={"file": ("librispeech-six-speakers.wav", wave_bytes.getvalue(), "audio/wav")})
        file_id = uploaded["id"]
        request = {"file_id": file_id, "model": "stt-async-v5", "enable_speaker_diarization": True, "enable_language_identification": False, "language_hints": manifest["language_hints"]}
        transcription = send("POST", "/transcriptions", json=request)
        transcription_id = transcription["id"]
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = send("GET", f"/transcriptions/{transcription_id}")
            status = state["status"]
            print(f"async_status={status}", flush=True)
            if status in ("completed", "error"):
                break
            time.sleep(2)
        if status != "completed":
            raise RuntimeError(f"Soniox async status={status}")
        transcript = send("GET", f"/transcriptions/{transcription_id}/transcript")
        tokens = [{k: token.get(k) for k in ("text", "speaker", "start_ms", "end_ms")} for token in transcript["tokens"]]
        duration = len(pcm) / (RATE * 2)
        result = {
            "arm": "async_full_file",
            "model": "stt-async-v5",
            "config": {k: v for k, v in request.items() if k != "file_id"},
            "duration_s": duration,
            "timeline": [{"provider_start_s": 0, "provider_end_s": duration, "source_start_s": 0, "source_end_s": duration}],
            "tokens": tokens,
            "metrics": None,
            "fixture": {"dataset": manifest["dataset"], "license": manifest["license"], "source_sha256": sha256(pcm).hexdigest(), "turns": turns, "clips": provenance},
        }
        result["metrics"] = metrics(result, turns)
        (ROOT / "async_full_file.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"completed=async_full_file final_tokens={len(tokens)} metrics={json.dumps(result['metrics'], ensure_ascii=False)}", flush=True)
    finally:
        if transcription_id is not None and status in ("completed", "error"):
            send("DELETE", f"/transcriptions/{transcription_id}")
        if file_id is not None and (transcription_id is None or status in ("completed", "error")):
            send("DELETE", f"/files/{file_id}")
        print(f"async_http_requests={requests_made} uploaded_source_seconds={len(pcm) / (RATE * 2):.3f}", flush=True)


if __name__ == "__main__":
    main()
