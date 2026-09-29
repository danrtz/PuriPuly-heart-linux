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
import subprocess
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


def sdk_segments(tokens: list[dict]) -> list[dict]:
    bridge = ROOT / "sdk" / "segments.mjs"
    completed = subprocess.run(["node", str(bridge)], input=json.dumps(tokens, ensure_ascii=False),
                               text=True, encoding="utf-8", capture_output=True, check=True)
    return json.loads(completed.stdout)


def mapped_intervals(segments: list[dict], timeline: list[dict], duration: float) -> tuple[list[tuple[float, float, str]], dict]:
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
    stats = {"sdk_groups": len(segments), "untimed_groups": [], "zero_duration_groups": [],
             "unattributed_groups": [], "padding_or_omitted_groups": [],
             "out_of_support_groups": [], "wholly_out_of_support_groups": [],
             "out_of_support_total_ms": 0.0, "mapped_source_pieces": 0,
             "bridged_positive_gap_ms": 0.0, "max_bridged_gap_ms": 0.0}
    for index, segment in enumerate(segments):
        prior_end = None
        for token in segment["tokens"]:
            start_ms, end_ms = token.get("start_ms"), token.get("end_ms")
            if (isinstance(start_ms, (int, float)) and isinstance(end_ms, (int, float))
                    and math.isfinite(start_ms) and math.isfinite(end_ms)):
                if prior_end is not None:
                    gap = max(0, start_ms - prior_end)
                    stats["bridged_positive_gap_ms"] += gap
                    stats["max_bridged_gap_ms"] = max(stats["max_bridged_gap_ms"], gap)
                prior_end = end_ms
        start_ms, end_ms = segment.get("start_ms"), segment.get("end_ms")
        if start_ms is None or end_ms is None:
            stats["untimed_groups"].append(index)
            continue
        if not all(isinstance(value, (float, int)) and math.isfinite(value) for value in (start_ms, end_ms)):
            raise ValueError(f"Invalid SDK segment time: {index}")
        start, end = start_ms / 1000, end_ms / 1000
        if end < start:
            raise ValueError(f"Inverted SDK segment time: {index}")
        if end == start:
            stats["zero_duration_groups"].append(index)
            continue
        outside = max(0.0, min(end, 0.0) - start) + max(0.0, end - max(start, previous))
        within = max(0.0, min(end, previous) - max(start, 0.0))
        if outside:
            stats["out_of_support_groups"].append(index)
            stats["out_of_support_total_ms"] += outside * 1000
            if not within:
                stats["wholly_out_of_support_groups"].append(index)
        speaker = segment.get("speaker")
        if speaker is None or speaker == "":
            stats["unattributed_groups"].append(index)
            continue
        if not isinstance(speaker, (str, int)) or any(c.isspace() for c in str(speaker)):
            raise ValueError(f"Invalid SDK speaker ID: {index}")
        covered = 0.0
        for piece in timeline:
            left, right = max(start, piece["provider_start_s"]), min(end, piece["provider_end_s"])
            if right - left < 1e-6:
                continue
            if piece["source_start_s"] is None:
                continue
            a = round(piece["source_start_s"] + left - piece["provider_start_s"], 6)
            b = round(piece["source_start_s"] + right - piece["provider_start_s"], 6)
            if a < -1e-6 or b > duration + 1e-6 or a >= b:
                raise ValueError("Projected SDK segment outside source")
            projected.append((a, min(b, duration), str(speaker)))
            covered += right - left
            stats["mapped_source_pieces"] += 1
        if covered < within - 1e-5:
            stats["padding_or_omitted_groups"].append(index)
    return sorted(projected), stats


def conversion(result: dict, duration: float) -> tuple[str, dict]:
    segments = sdk_segments(result["tokens"])
    intervals, diagnostics = mapped_intervals(segments, result["timeline"], duration)
    groups = []
    offset = 0
    for segment in segments:
        count = len(segment["tokens"])
        groups.append({**{key: value for key, value in segment.items() if key != "tokens"},
                       "token_start_index": offset, "token_end_index": offset + count})
        offset += count
    if offset != len(result["tokens"]):
        raise ValueError("SDK groups do not account for every native token")
    case_id = result["case_id"]
    rttm = "".join(f"SPEAKER {case_id} 1 {a:.6f} {b-a:.6f} <NA> <NA> {speaker} <NA> <NA>\n"
                   for a, b, speaker in intervals)
    artifact = {"native_artifact_sha256": result["native_artifact_sha256"],
                "sdk_segments": groups, "projected_intervals": intervals,
                "projection_diagnostics": diagnostics}
    return rttm, artifact


def write_conversion(case: dict, arm: str, result: dict) -> None:
    case_id = case["id"]
    rttm, artifact = conversion(result, case["duration_s"])
    derived = ROOT / "sdk_output" / arm / f"{case_id}.json"
    pred = ROOT / "predictions" / arm / f"{case_id}.rttm"
    derived.parent.mkdir(parents=True, exist_ok=True)
    pred.parent.mkdir(parents=True, exist_ok=True)
    derived.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pred.write_bytes(rttm.encode("utf-8"))


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
            write_conversion(case, arm, result)
        except Exception as error:
            result["completed"] = False
            result["error"] = f"Conversion {type(error).__name__}: {error}"
    output = ROOT / "results" / case_id / f"{arm}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    case_id = case["id"]
    result_path = ROOT / "results" / case_id / f"{arm}.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("completed") is not True or result.get("case_id") != case_id or result.get("arm") != arm:
        raise ValueError(f"Native result not completed: {case_id}/{arm}")
    if result["source_pcm_sha256"] != case["clip_pcm_sha256"] or result["source_wav_sha256"] != case["clip_wav_sha256"]:
        raise ValueError(f"Wrong source: {case_id}/{arm}")
    if result["native_artifact_sha256"] != sha256(json.dumps({"tokens": result["tokens"],
            "messages": result.get("messages", [])}, ensure_ascii=False, sort_keys=True).encode()).hexdigest():
        raise ValueError(f"Native tokens changed: {case_id}/{arm}")
    if arm == "async_full_file" and (result["lifecycle"]["status"] != "completed"
            or not result["cleanup"]["transcription_deleted"] or not result["cleanup"]["file_deleted"] or result["error"]):
        raise ValueError(f"Provider/cleanup incomplete: {case_id}/{arm}")
    if arm != "async_full_file" and (result["lifecycle"]["websocket_requests"] != 1
            or result["lifecycle"]["finalize_requested"] != result["lifecycle"]["fin_received"]
            or not result["lifecycle"]["finished_received"]):
        raise ValueError(f"Realtime provider incomplete: {case_id}/{arm}")
    write_conversion(case, arm, result)
    print(f"converted_existing={case_id}/{arm} sdk_segments_verified", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case")
    parser.add_argument("--arm", choices=ARMS)
    parser.add_argument("--convert-existing", action="store_true", help="Reproject saved native output; no provider request")
    parser.add_argument("--convert-all", action="store_true", help="Reproject all 28 saved native outputs; no provider request")
    args = parser.parse_args()
    manifest = json.loads((BENCH / "manifest.json").read_text(encoding="utf-8"))
    if args.convert_all:
        if args.case or args.arm or args.convert_existing:
            parser.error("--convert-all cannot be combined with case/arm or --convert-existing")
        for arm in ARMS:
            for case in manifest["cases"]:
                convert_existing(case, arm)
        return
    if not args.case or not args.arm:
        parser.error("--case and --arm are required unless --convert-all")
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
