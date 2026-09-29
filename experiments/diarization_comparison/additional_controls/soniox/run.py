"""Run one Soniox arm against one immutable additional-control fixture."""

from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
import wave

import keyring
import requests

ROOT = Path(__file__).resolve().parent
CONTROLS = ROOT.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(CONTROLS.parents[1] / "soniox_diarization"))
from probe import RATE, live_arm, regions  # noqa: E402
from app_segments import app_segments  # noqa: E402

BASE = "https://api.soniox.com/v1"
ARMS = ("continuous", "forced", "segmented", "async_full_file")


def fixture(name: str) -> tuple[dict, bytes, Path]:
    metadata = json.loads((CONTROLS / "fixtures.json").read_text(encoding="utf-8"))["cases"][name]
    audio = CONTROLS / metadata["audio"]
    with wave.open(str(audio), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, 2, RATE, "NONE"):
            raise ValueError(f"Unexpected WAV format: {name}")
        pcm = source.readframes(source.getnframes())
    if (sha256(pcm).hexdigest(), len(pcm), len(pcm) / (RATE * 2)) != (
        metadata["source_sha256"], metadata["pcm_bytes"], metadata["duration_s"]
    ):
        raise ValueError(f"Fixture PCM does not match manifest: {name}")
    return metadata, pcm, audio


def async_arm(pcm: bytes, audio: Path, key: str) -> dict:
    duration = len(pcm) / (RATE * 2)
    headers = {"Authorization": "Bearer " + key}
    config = {"model": "stt-async-v5", "enable_speaker_diarization": True,
              "enable_language_identification": False, "language_hints": ["en"]}
    lifecycle: dict = {"status": None, "http_requests": 0}
    cleanup: dict = {"transcription_deleted": False, "file_deleted": False,
                     "unresolved_transcription": False, "unresolved_file": False,
                     "errors": []}
    file_id = None
    job_id = None
    tokens = []
    failure = None

    def request(method: str, path: str, **kwargs) -> dict:
        lifecycle["http_requests"] += 1
        response = requests.request(method, BASE + path, headers=headers, timeout=30, **kwargs)
        if not response.ok:
            raise RuntimeError(f"Soniox {method} HTTP {response.status_code}")
        return response.json() if response.content else {}

    try:
        with audio.open("rb") as handle:
            file_id = request("POST", "/files", files={"file": (audio.name, handle, "audio/wav")})["id"]
        job_id = request("POST", "/transcriptions", json={"file_id": file_id, **config})["id"]
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = request("GET", f"/transcriptions/{job_id}")
            lifecycle["status"] = state["status"]
            if state["status"] in ("completed", "error"):
                break
            time.sleep(2)
        if lifecycle["status"] != "completed":
            raise RuntimeError(f"Soniox async status={lifecycle['status']}")
        transcript = request("GET", f"/transcriptions/{job_id}/transcript")
        tokens = [{k: token.get(k) for k in ("text", "speaker", "start_ms", "end_ms")}
                  for token in transcript["tokens"]]
    except Exception as error:
        failure = f"{type(error).__name__}: {error}" if isinstance(error, RuntimeError) else type(error).__name__
    finally:
        if job_id is not None and lifecycle["status"] in ("completed", "error"):
            try:
                request("DELETE", f"/transcriptions/{job_id}")
                cleanup["transcription_deleted"] = True
            except Exception as error:
                cleanup["errors"].append(f"transcription: {type(error).__name__}")
        if file_id is not None and (job_id is None or cleanup["transcription_deleted"]):
            try:
                request("DELETE", f"/files/{file_id}")
                cleanup["file_deleted"] = True
            except Exception as error:
                cleanup["errors"].append(f"file: {type(error).__name__}")
        cleanup["unresolved_transcription"] = job_id is not None and not cleanup["transcription_deleted"]
        cleanup["unresolved_file"] = file_id is not None and not cleanup["file_deleted"]

    return {"arm": "async_full_file", "model": "stt-async-v5", "config": config,
            "duration_s": duration, "sent_seconds": duration, "http_requests": lifecycle["http_requests"],
            "timeline": [{"provider_start_s": 0, "provider_end_s": duration,
                          "source_start_s": 0, "source_end_s": duration}],
            "tokens": tokens, "lifecycle": lifecycle, "cleanup": cleanup, "error": failure}


async def run(name: str, arm: str) -> None:
    metadata, pcm, audio = fixture(name)
    key = os.environ.get("SONIOX_API_KEY") or keyring.get_password("puripuly-heart", "soniox_api_key")
    if not key:
        raise RuntimeError("SONIOX_API_KEY/keyring credential unavailable")
    output = ROOT / name / f"{arm}.json"
    if output.exists():
        raise FileExistsError(f"Refusing to repeat an existing run: {output}")
    if arm == "async_full_file":
        result = await asyncio.to_thread(async_arm, pcm, audio, key)
    else:
        if arm == "segmented":
            slices, diagnostics = await app_segments(pcm)
            if not slices:
                raise RuntimeError("VAD emitted no speech segments")
        else:
            slices = regions(arm, metadata["duration_s"])
            diagnostics = None
        result = await live_arm(arm, pcm, ["en"], key, slices)
        result["lifecycle"] = {
            "websocket_requests": result["websocket_requests"],
            "finalize_requested": len(slices), "fin_received": result["fin_count"],
            "finished_received": any(message["finished"] for message in result["messages"]),
        }
        if diagnostics is not None:
            result["segmentation"] = {"diagnostics": diagnostics, "segments": slices}
        if result["fin_count"] != len(slices) or not result["lifecycle"]["finished_received"]:
            result["error"] = "Incomplete finalization or stream completion"
    result["source_sha256"] = metadata["source_sha256"]
    result["completed"] = (
        result["lifecycle"]["status"] == "completed"
        and result["cleanup"]["transcription_deleted"]
        and result["cleanup"]["file_deleted"]
        and not result.get("error")
        if arm == "async_full_file" else
        result["fin_count"] == len(slices)
        and result["lifecycle"]["finished_received"]
        and not result.get("error")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not result["completed"]:
        raise RuntimeError(f"Run incomplete: {name}/{arm}: {result.get('error') or result.get('cleanup')}")
    print(f"completed={name}/{arm} sent_seconds={result['sent_seconds']} tokens={len(result['tokens'])} "
          f"lifecycle={json.dumps(result['lifecycle'])}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=("repeated", "distinct"))
    parser.add_argument("arm", choices=ARMS)
    args = parser.parse_args()
    asyncio.run(run(args.case, args.arm))
