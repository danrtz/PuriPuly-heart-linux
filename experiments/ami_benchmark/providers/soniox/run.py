"""Execute the seven published AMI windows with the four Soniox diarization arms.

One case/arm is immutable once written. Incomplete attempts never produce RTTM files.
Run from the repository root with the Windows application virtual environment.
"""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sys
import time
import wave

import keyring
import requests

ROOT = Path(__file__).resolve().parent
BENCH = ROOT.parents[1]
REPO = ROOT.parents[3]
sys.dont_write_bytecode = True
sys.path.insert(0, str(REPO / "experiments" / "soniox_diarization"))
from probe import RATE, live_arm, regions  # noqa: E402
from app_segments import app_segments  # noqa: E402

ARMS = ("continuous", "forced", "segmented", "async_full_file")
BASE = "https://api.soniox.com/v1"


def load_audio(case: dict) -> tuple[bytes, Path, str]:
    audio = BENCH / case["audio"]
    wav_sha = sha256(audio.read_bytes()).hexdigest()
    if wav_sha != case["clip_wav_sha256"]:
        raise ValueError(f"WAV SHA256 mismatch: {case['id']}")
    with wave.open(str(audio), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, 2, RATE, "NONE"):
            raise ValueError(f"Invalid source audio format: {case['id']}")
        pcm = source.readframes(source.getnframes())
    if sha256(pcm).hexdigest() != case["clip_pcm_sha256"] or len(pcm) != round(case["duration_s"] * RATE) * 2:
        raise ValueError(f"PCM digest/duration mismatch: {case['id']}")
    return pcm, audio, wav_sha


def async_arm(audio: Path, duration: float, key: str) -> dict:
    config = {"model": "stt-async-v5", "enable_speaker_diarization": True,
              "enable_language_identification": False, "language_hints": ["en"]}
    headers = {"Authorization": "Bearer " + key}
    lifecycle = {"status": None, "http_requests": 0}
    cleanup = {"transcription_deleted": False, "file_deleted": False, "errors": [],
               "unresolved_transcription": False, "unresolved_file": False}
    file_id = job_id = None
    tokens: list[dict] = []
    failure = None

    def request(method: str, path: str, **kwargs) -> dict:
        lifecycle["http_requests"] += 1
        response = requests.request(method, BASE + path, headers=headers, timeout=90, **kwargs)
        if not response.ok:
            raise RuntimeError(f"Soniox {method} HTTP {response.status_code}")
        return response.json() if response.content else {}

    try:
        with audio.open("rb") as handle:
            file_id = request("POST", "/files", files={"file": (audio.name, handle, "audio/wav")})["id"]
        job_id = request("POST", "/transcriptions", json={"file_id": file_id, **config})["id"]
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            state = request("GET", f"/transcriptions/{job_id}")
            lifecycle["status"] = state["status"]
            if state["status"] in ("completed", "error"):
                break
            time.sleep(3)
        if lifecycle["status"] != "completed":
            raise RuntimeError(f"Soniox async status={lifecycle['status']}")
        transcript = request("GET", f"/transcriptions/{job_id}/transcript")
        tokens = transcript["tokens"]
    except Exception as error:
        failure = f"{type(error).__name__}: {error}" if isinstance(error, RuntimeError) else type(error).__name__
    finally:
        if job_id is not None:
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


def mapped_intervals(tokens: list[dict], timeline: list[dict], duration: float) -> tuple[list[tuple[float, float, str]], dict]:
    """Intersect native word-time support with source-audio pieces, never padding.

    Null-speaker tokens remain diagnostic only. Same-speaker overlapping word supports
    are unioned, but touching/nonoverlapping words and distinct speakers remain separate.
    """
    if not timeline:
        raise ValueError("Empty provider timeline")
    previous = 0.0
    for piece in timeline:
        start, end = piece["provider_start_s"], piece["provider_end_s"]
        if not all(isinstance(value, (float, int)) and math.isfinite(value) for value in (start, end)) or abs(start - previous) > 1e-5 or end <= start:
            raise ValueError("Noncontiguous/invalid provider timeline")
        previous = end
        if piece["source_start_s"] is not None:
            a, b = piece["source_start_s"], piece["source_end_s"]
            if not all(isinstance(value, (float, int)) and math.isfinite(value) for value in (a, b)) or a < 0 or b > duration + 1e-6 or b <= a or abs((b - a) - (end - start)) > 1e-5:
                raise ValueError("Invalid source-timeline mapping")
        elif piece["source_end_s"] is not None:
            raise ValueError("Partially mapped padding")
    projected: list[tuple[float, float, str]] = []
    stats = {"native_tokens": len(tokens), "untimed_tokens": 0, "zero_duration_token_indices": [],
             "unattributed_tokens": 0, "unattributed_provider_intervals_ms": [],
             "padding_or_omitted_portions": 0, "mapped_token_pieces": 0,
             "out_of_support_token_indices": [], "wholly_out_of_support_tokens": 0,
             "straddling_support_tokens": 0, "out_of_support_total_ms": 0.0,
             "straddling_trimmed_ms": 0.0, "max_overrun_ms": 0.0}
    for token_index, token in enumerate(tokens):
        start_ms, end_ms = token.get("start_ms"), token.get("end_ms")
        if start_ms is None and end_ms is None:
            stats["untimed_tokens"] += 1
            continue
        if not all(isinstance(value, (float, int)) and math.isfinite(value) for value in (start_ms, end_ms)):
            raise ValueError("Invalid native token time")
        start, end = start_ms / 1000, end_ms / 1000
        if end < start:
            raise ValueError("Negative native token duration")
        if end == start:
            stats["zero_duration_token_indices"].append(token_index)
            continue  # provider gave no support; never invent a duration
        outside_s = max(0.0, min(end, 0.0) - start) + max(0.0, end - max(start, previous))
        within_s = max(0.0, min(end, previous) - max(start, 0.0))
        if outside_s:
            stats["out_of_support_token_indices"].append(token_index)
            stats["out_of_support_total_ms"] = round(stats["out_of_support_total_ms"] + outside_s * 1000, 6)
            stats["max_overrun_ms"] = round(max(stats["max_overrun_ms"], (end - previous) * 1000), 6)
            if within_s:
                stats["straddling_support_tokens"] += 1
                stats["straddling_trimmed_ms"] = round(stats["straddling_trimmed_ms"] + outside_s * 1000, 6)
            else:
                stats["wholly_out_of_support_tokens"] += 1
        speaker = token.get("speaker")
        if speaker is None or speaker == "":
            stats["unattributed_tokens"] += 1
            stats["unattributed_provider_intervals_ms"].append([start_ms, end_ms])
            continue
        if not isinstance(speaker, (str, int)) or any(c.isspace() for c in str(speaker)):
            raise ValueError("Invalid native speaker ID")
        speaker = str(speaker)
        covered = 0.0
        for piece in timeline:
            left, right = max(start, piece["provider_start_s"]), min(end, piece["provider_end_s"])
            if right - left < 1e-6:
                continue  # float accumulation can create a phantom crossing at an exact token boundary
            if piece["source_start_s"] is None:
                continue
            a = piece["source_start_s"] + left - piece["provider_start_s"]
            b = piece["source_start_s"] + right - piece["provider_start_s"]
            a, b = round(a, 6), round(b, 6)
            if a < -1e-6 or b > duration + 1e-6 or a >= b:
                raise ValueError("Projected native interval outside source")
            if b > duration:
                b = duration  # only float/sample-grid precision at case endpoint
            projected.append((a, b, speaker))
            covered += right - left
            stats["mapped_token_pieces"] += 1
        if covered < within_s - 1e-5:
            stats["padding_or_omitted_portions"] += 1
    projected.sort(key=lambda row: (row[2], row[0], row[1]))
    merged: list[tuple[float, float, str]] = []
    for start, end, speaker in projected:
        if merged and speaker == merged[-1][2] and start < merged[-1][1]:
            a, b, _ = merged[-1]
            merged[-1] = (a, max(b, end), speaker)
        else:
            merged.append((start, end, speaker))
    return sorted(merged), stats


def persist(case: dict, arm: str, result: dict, elapsed: float, wav_sha: str) -> bool:
    case_id = case["id"]
    result.update({"case_id": case_id, "source_pcm_sha256": case["clip_pcm_sha256"],
                   "source_wav_sha256": wav_sha, "wall_time_s": round(elapsed, 3),
                   "native_artifact_sha256": sha256(json.dumps({"tokens": result.get("tokens", []),
                       "messages": result.get("messages", [])}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()})
    if arm != "async_full_file":
        result["lifecycle"] = {"websocket_requests": result["websocket_requests"],
                               "finalize_requested": result["expected_finalizations"],
                               "fin_received": result["fin_count"],
                               "finished_received": any(message["finished"] for message in result["messages"])}
        result["completed"] = (result["fin_count"] == result["expected_finalizations"]
                               and result["lifecycle"]["finished_received"])
    else:
        result["completed"] = (result["lifecycle"]["status"] == "completed"
                               and result["cleanup"]["transcription_deleted"]
                               and result["cleanup"]["file_deleted"] and not result["error"])
    if result["completed"]:
        try:
            intervals, diagnostics = mapped_intervals(result["tokens"], result["timeline"], case["duration_s"])
            result["conversion"] = diagnostics
            rttm = "".join(f"SPEAKER {case_id} 1 {a:.6f} {b-a:.6f} <NA> <NA> {speaker} <NA> <NA>\n"
                           for a, b, speaker in intervals)
            result["predicted_speaker_ids"] = sorted({speaker for _, _, speaker in intervals})
            result["prediction_sha256"] = sha256(rttm.encode()).hexdigest()
        except Exception as error:
            result["completed"] = False
            result["error"] = f"Conversion {type(error).__name__}: {error}"
    output = ROOT / "results" / case_id / f"{arm}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result["completed"]:
        pred = ROOT / "predictions" / arm / f"{case_id}.rttm"
        pred.parent.mkdir(parents=True, exist_ok=True)
        pred.write_bytes(rttm.encode("utf-8"))
    return result["completed"]


async def execute(case: dict, arm: str, key: str) -> None:
    case_id = case["id"]
    output = ROOT / "results" / case_id / f"{arm}.json"
    if output.exists() or (ROOT / "predictions" / arm / f"{case_id}.rttm").exists():
        raise FileExistsError(f"Refusing to repeat existing result: {case_id}/{arm}")
    pcm, audio, wav_sha = load_audio(case)
    started = time.monotonic()
    try:
        if arm == "async_full_file":
            result = await asyncio.to_thread(async_arm, audio, case["duration_s"], key)
        else:
            if arm == "segmented":
                slices, diagnostics = await app_segments(pcm)
                if not slices:
                    raise RuntimeError("VAD emitted no speech segments")
            else:
                slices, diagnostics = regions(arm, case["duration_s"]), None
            result = await live_arm(arm, pcm, ["en"], key, slices)
            result["expected_finalizations"] = len(slices)
            if diagnostics is not None:
                result["segmentation"] = {"diagnostics": diagnostics, "segments": slices}
        complete = persist(case, arm, result, time.monotonic() - started, wav_sha)
    except Exception as error:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"case_id": case_id, "arm": arm, "completed": False,
            "source_pcm_sha256": case["clip_pcm_sha256"], "source_wav_sha256": wav_sha,
            "wall_time_s": round(time.monotonic() - started, 3), "error": type(error).__name__,
            "outstanding_unknowns": "Connection may have reached provider; no completed result or RTTM"}, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"Incomplete {case_id}/{arm}: {type(error).__name__}") from None
    if not complete:
        raise RuntimeError(f"Incomplete {case_id}/{arm}: inspect owned result JSON")
    print(f"completed={case_id}/{arm} sent_seconds={result['sent_seconds']} "
          f"tokens={len(result['tokens'])} finalizations={result.get('fin_count', '-')} "
          f"http_requests={result.get('http_requests', '-')} elapsed_s={result['wall_time_s']}", flush=True)

def convert_existing(case: dict, arm: str) -> None:
    """Reproject a verified provider-completed native artifact without another request."""
    import shutil

    case_id = case["id"]
    output = ROOT / "results" / case_id / f"{arm}.json"
    result = json.loads(output.read_text(encoding="utf-8"))
    already_complete = result.get("completed") is True
    saved = output.with_name(f"{arm}.pre_boundary.json" if already_complete else f"{arm}.initial.json")
    prediction = ROOT / "predictions" / arm / f"{case_id}.rttm"
    if saved.exists():
        raise FileExistsError(f"Existing repair artifact: {case_id}/{arm}")
    if already_complete:
        if not prediction.is_file() or sha256(prediction.read_text(encoding="utf-8").encode()).hexdigest() != result["prediction_sha256"]:
            raise ValueError(f"Previously completed RTTM digest mismatch: {case_id}/{arm}")
    elif prediction.exists() or not str(result.get("error", "")).startswith("Conversion "):
        raise ValueError(f"Only native conversion failures can be repaired: {case_id}/{arm}")
    _, _, wav_sha = load_audio(case)
    if (result.get("source_pcm_sha256") != case["clip_pcm_sha256"]
            or result.get("source_wav_sha256") != wav_sha):
        raise ValueError(f"Wrong source: {case_id}/{arm}")
    if arm == "async_full_file" and (result["lifecycle"]["status"] != "completed"
            or not result["cleanup"]["transcription_deleted"] or not result["cleanup"]["file_deleted"]):
        raise ValueError(f"Provider/cleanup was incomplete: {case_id}/{arm}")
    if arm != "async_full_file" and (result["lifecycle"]["websocket_requests"] != 1
            or result["lifecycle"]["finalize_requested"] != result["lifecycle"]["fin_received"]
            or not result["lifecycle"]["finished_received"]):
        raise ValueError(f"Realtime provider incomplete: {case_id}/{arm}")
    shutil.copyfile(output, saved)
    result["error"] = None
    result["conversion_repair_from"] = saved.relative_to(ROOT).as_posix()
    result["conversion_repair_source_sha256"] = sha256(saved.read_bytes()).hexdigest()
    if not persist(case, arm, result, result["wall_time_s"], wav_sha):
        raise RuntimeError(f"Conversion still incomplete: {case_id}/{arm}")
    print(f"converted_existing={case_id}/{arm} native_attempt_preserved={saved.name}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--arm", required=True, choices=ARMS)
    parser.add_argument("--convert-existing", action="store_true", help="Reproject previously saved native output; no provider request")
    args = parser.parse_args()
    manifest = json.loads((BENCH / "manifest.json").read_text(encoding="utf-8"))
    case = next((case for case in manifest["cases"] if case["id"] == args.case), None)
    if case is None:
        parser.error("Case must be a published manifest ID")
    if args.convert_existing:
        convert_existing(case, args.arm)
        return
    key = os.environ.get("SONIOX_API_KEY") or keyring.get_password("puripuly-heart", "soniox_api_key")
    if not key:
        raise RuntimeError("SONIOX_API_KEY/keyring credential unavailable")
    asyncio.run(execute(case, args.arm, key))


if __name__ == "__main__":
    main()
