"""Run the seven manifest AMI clips against independent Beijing LiveTranslate sessions.

The common scorer is deliberately not imported: references are read only after
inference, by experiments/ami_benchmark/score.py.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import socket
import ssl
import json
import math
from pathlib import Path
import sys
import time
import wave
import websockets
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
BENCHMARK = ROOT.parents[1]
QWEN_HELPER = ROOT.parents[2] / "diarization_comparison" / "qwen"
sys.path.insert(0, str(QWEN_HELPER))
from run import CHUNK_MS, MODEL_ID, RATE, SAMPLE_WIDTH, EventCollector, get_credentials, realtime_endpoint, redact  # noqa: E402


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_audio(case: dict) -> tuple[bytes, dict]:
    path = BENCHMARK / case["audio"]
    raw = path.read_bytes()
    wav_hash = digest(raw)
    if wav_hash != case["clip_wav_sha256"]:
        raise ValueError(f"WAV digest mismatch: {case['id']}")
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, SAMPLE_WIDTH, RATE, "NONE"):
            raise ValueError(f"Expected uncompressed mono PCM16 16000 Hz: {case['id']}")
        frames = source.getnframes()
        pcm = source.readframes(frames)
    if frames != case["duration_s"] * RATE or len(pcm) != frames * SAMPLE_WIDTH or digest(pcm) != case["clip_pcm_sha256"]:
        raise ValueError(f"PCM digest, length or duration mismatch: {case['id']}")
    return pcm, {"pcm_sha256": digest(pcm), "wav_sha256": wav_hash, "duration_s": frames / RATE,
                 "bytes": len(pcm), "format": "mono signed little-endian PCM16 16000 Hz"}


def select_tls_address(host: str) -> tuple[str, dict]:
    """Probe DNS edge TLS without opening a model session; keep original SNI."""
    name = urlsplit(realtime_endpoint(host, "beijing")).hostname
    addresses = list(dict.fromkeys(entry[4][0] for entry in socket.getaddrinfo(name, 443, type=socket.SOCK_STREAM)))
    failures = []
    for index, address in enumerate(addresses):
        try:
            with socket.create_connection((address, 443), timeout=6) as connection:
                connection.settimeout(8)
                with ssl.create_default_context().wrap_socket(connection, server_hostname=name):
                    pass
            return address, {"dns_address_count": len(addresses), "selected_address_index": index,
                             "tls_preflight_failures": failures,
                             "method": "Direct TLS to responsive DNS edge; configured hostname retained as SNI and HTTP Host"}
        except (OSError, TimeoutError) as exc:
            failures.append({"address_index": index, "error_type": type(exc).__name__})
    raise RuntimeError(f"No TLS-responsive Beijing DNS address among {len(addresses)} resolved addresses; failure types: {[x['error_type'] for x in failures]}")


async def run_live(region: str, pcm: bytes, secrets: tuple[str, ...], host: str, key: str, address: str) -> dict:
    """One fresh WebSocket, continuous paced audio, then finish; never reconnect.

    The earlier reviewed Qwen runner's protocol and event collector are reused.
    Opening handshake timeout is 90 s here after observed 30 s handshake failures;
    the socket close code/reason is preserved on failure.
    """
    result = {"connection_attempted": True, "connection_opened": False,
              "session_created_received": False, "session_updated_received": False,
              "session_finished_received": False, "effective_config": None, "events": [],
              "errors": [], "bytes_sent": 0, "sent_audio_s": 0.0,
              "audio_stream_wall_s": None, "post_audio_wait_s": None,
              "websocket_requests_attempted": 1, "websocket_sessions_opened": 0,
              "session_finished_utc": None}
    collector = receiver = None
    connection_start = time.monotonic()
    stream_start = audio_finished = None
    try:
        async with websockets.connect(realtime_endpoint(host, region),
                                      host=address, port=443, proxy=None,
                                      additional_headers={"Authorization": f"Bearer {key}"},
                                      open_timeout=90, close_timeout=10,
                                      ping_interval=20, ping_timeout=120,
                                      max_size=16 * 1024 * 1024) as socket:
            result["connection_opened"] = True
            result["websocket_sessions_opened"] = 1
            collector = EventCollector(time.monotonic())
            receiver = asyncio.create_task(collector.receive(socket, secrets))
            created = await collector.wait_for_type({"session.created", "error"}, 30)
            if created["native_event"]["type"] == "error":
                raise RuntimeError("server_rejected_initial_session")
            result["session_created_received"] = True
            await socket.send(json.dumps({"type": "session.update", "session": {
                "output_modalities": ["text"],
                "audio": {"input": {"turn_detection": {"type": "speaker_detection", "threshold": 0.5}}},
                "translation": {"language": "ko"}}}, separators=(",", ":")))
            updated = await collector.wait_for_type({"session.updated", "error"}, 30)
            if updated["native_event"]["type"] == "error":
                raise RuntimeError("server_rejected_session_configuration")
            result["session_updated_received"] = True
            result["effective_config"] = updated["native_event"].get("session")
            chunk_bytes = RATE * SAMPLE_WIDTH * CHUNK_MS // 1000
            stream_start = time.monotonic()
            for offset in range(0, len(pcm), chunk_bytes):
                delay = stream_start + offset / (RATE * SAMPLE_WIDTH) - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                await socket.send(json.dumps({"type": "input_audio_buffer.append",
                                              "audio": base64.b64encode(pcm[offset:offset + chunk_bytes]).decode("ascii")},
                                             separators=(",", ":")))
                result["bytes_sent"] += min(chunk_bytes, len(pcm) - offset)
                result["sent_audio_s"] = result["bytes_sent"] / (RATE * SAMPLE_WIDTH)
            delay = stream_start + len(pcm) / (RATE * SAMPLE_WIDTH) - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            audio_finished = time.monotonic()
            result["audio_stream_wall_s"] = audio_finished - stream_start
            await socket.send(json.dumps({"type": "session.finish"}, separators=(",", ":")))
            finished = await collector.wait_for_type({"session.finished", "error"}, 180)
            result["post_audio_wait_s"] = time.monotonic() - audio_finished
            if finished["native_event"]["type"] == "error":
                raise RuntimeError("server_reported_error_before_session_finished")
            result["session_finished_received"] = True
            result["session_finished_utc"] = utc_now()
            await asyncio.sleep(0.1)
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": redact(str(exc), secrets),
                 "elapsed_s": round(time.monotonic() - connection_start, 6)}
        if isinstance(exc, websockets.exceptions.ConnectionClosed):
            error["close_code"] = exc.code
            error["close_reason"] = redact(exc.reason, secrets)
        result["errors"].append(error)
        if stream_start is not None:
            result["audio_stream_wall_s"] = time.monotonic() - stream_start
        if audio_finished is not None and result["post_audio_wait_s"] is None:
            result["post_audio_wait_s"] = time.monotonic() - audio_finished
    finally:
        if collector is not None:
            result["events"] = collector.events
            if collector.receive_error is not None and result["errors"]:
                exc = collector.receive_error
                result["errors"][0]["receiver_error_type"] = type(exc).__name__
                result["errors"][0]["receiver_error_message"] = redact(str(exc), secrets)
                if isinstance(exc, websockets.exceptions.ConnectionClosed):
                    result["errors"][0]["receiver_close_code"] = exc.code
                    result["errors"][0]["receiver_close_reason"] = redact(exc.reason, secrets)
        if receiver is not None and not receiver.done():
            receiver.cancel()
            try:
                await receiver
            except asyncio.CancelledError:
                pass
    return result


def convert(events: list[dict], duration: float) -> tuple[list[dict], list[dict], dict]:
    """Pair boundaries by item_id; only integer speaker_id on speech_started identifies a speaker.

    Native offsets use milliseconds from this session's audio origin. Finite endpoints
    outside [0,duration] are clipped and logged; malformed or ambiguous items are
    excluded entirely. No gap/tail completion or turn-count speaker inference.
    """
    boundaries = defaultdict(lambda: {"start": [], "stop": []})
    issues = []
    for index, entry in enumerate(events):
        native = entry.get("native_event", {})
        kind = native.get("type") if isinstance(native, dict) else None
        if kind not in ("input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped"):
            continue
        item = native.get("item_id")
        if not isinstance(item, str) or not item:
            issues.append({"event_index": index, "issue": "missing_or_invalid_item_id", "event_type": kind})
            continue
        boundaries[item]["start" if kind.endswith("speech_started") else "stop"].append((index, native))
    attributed = []
    unattributed = []
    clipping = []
    native_starts = []
    native_ends = []
    wholly_outside = 0
    clipped_span_s = 0.0
    for item, pair in boundaries.items():
        starts, stops = pair["start"], pair["stop"]
        if len(starts) != 1 or len(stops) != 1:
            issues.append({"item_id": item, "issue": "unpaired_or_ambiguous_boundary", "speech_started_count": len(starts), "speech_stopped_count": len(stops), "event_indices": [x[0] for x in starts + stops]})
            continue
        start_index, start = starts[0]
        stop_index, stop = stops[0]
        if stop_index <= start_index:
            issues.append({"item_id": item, "issue": "nonmonotonic_boundary_event_order", "event_indices": [start_index, stop_index]})
            continue
        a, b = start.get("audio_start_ms"), stop.get("audio_end_ms")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (a, b)):
            issues.append({"item_id": item, "issue": "missing_or_nonfinite_native_offset", "event_indices": [start_index, stop_index]})
            continue
        original_a, original_b = a / 1000, b / 1000
        native_starts.append(original_a)
        native_ends.append(original_b)
        if original_b <= original_a:
            issues.append({"item_id": item, "issue": "nonpositive_native_interval", "start_s": original_a, "end_s": original_b})
            continue
        a = min(duration, max(0., original_a))
        b = min(duration, max(0., original_b))
        if (a, b) != (original_a, original_b):
            clipping.append({"item_id": item, "native_start_s": original_a, "native_end_s": original_b, "clipped_start_s": a, "clipped_end_s": b})
            clipped_span_s += (original_b - original_a) - max(0., b - a)
        if b <= a:
            wholly_outside += 1
            issues.append({"item_id": item, "issue": "outside_case_window", "start_s": original_a, "end_s": original_b})
            continue
        speaker = start.get("speaker_id")
        row = {"item_id": item, "start_s": a, "end_s": b, "native_start_s": original_a, "native_end_s": original_b,
               "native_speaker_id": speaker, "event_indices": [start_index, stop_index]}
        if type(speaker) is int and speaker >= 0:
            attributed.append(row)
        else:
            row["issue"] = "missing_or_invalid_integer_speaker_id"
            unattributed.append(row)
    attributed.sort(key=lambda x: (x["start_s"], x["end_s"], x["event_indices"][0]))
    return attributed, unattributed, {"boundary_issues": issues, "clipped_intervals": clipping,
                                      "offset_summary": {"native_min_start_s": min(native_starts, default=None),
                                                         "native_max_end_s": max(native_ends, default=None),
                                                         "clipped_interval_count": len(clipping),
                                                         "wholly_outside_interval_count": wholly_outside,
                                                         "clipped_span_s": round(clipped_span_s, 6)},
                                      "offset_policy": "Native audio milliseconds / 1000; intersect finite valid intervals with input [0, case_duration]; count and exclude wholly outside and zero-duration intervals; exclude malformed, ambiguous or unpaired intervals; preserve all bounded overlaps; no shift, inferred speech or speaker labels."}


def render_rttm(case_id: str, intervals: list[dict]) -> bytes:
    return "".join(
        f"SPEAKER {case_id} 1 {row['start_s']:.6f} {row['end_s'] - row['start_s']:.6f} <NA> <NA> {row['native_speaker_id']} <NA> <NA>\n"
        for row in intervals
    ).encode("utf-8")


def write_case(case: dict, audio: dict, run: dict, started_at: str, elapsed: float, secrets: tuple[str, ...]) -> dict:
    case_id = case["id"]
    events = run["events"]
    event_bytes = "".join(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n" for entry in events).encode("utf-8")
    events_path = ROOT / "events" / f"{case_id}.jsonl"
    events_path.write_bytes(event_bytes)
    attributed, unattributed, diagnostics = convert(events, case["duration_s"])
    types = Counter(entry.get("native_event", {}).get("type", "unknown") for entry in events)
    server_errors = [entry["native_event"] for entry in events if entry.get("native_event", {}).get("type") == "error"]
    response_statuses = [entry["native_event"].get("response", {}).get("status") for entry in events if entry.get("native_event", {}).get("type") == "response.done"]
    complete = (run["connection_opened"] and run["session_created_received"] and run["session_updated_received"]
                and run["session_finished_received"] and run["bytes_sent"] == audio["bytes"]
                and not run["errors"] and not server_errors and all(s == "completed" for s in response_statuses))
    prediction_path = ROOT / "predictions" / f"{case_id}.rttm"
    prediction_hash = None
    if complete:
        # No RTTM for failed calls: a genuinely completed no-speech session alone gets an empty RTTM.
        prediction_bytes = render_rttm(case_id, attributed)
        prediction_path.write_bytes(prediction_bytes)
        prediction_hash = digest(prediction_bytes)
    result = {
        "case_id": case_id, "status": "completed" if complete else "incomplete", "model": MODEL_ID,
        "region": "cn-beijing", "audio": audio,
        "network": run.get("network"),
        "requested_config": {"output_modalities": ["text"], "translation_language": "ko", "source_asr": "model default",
                             "turn_detection": {"type": "speaker_detection", "threshold": 0.5}, "chunk_ms": CHUNK_MS,
                             "speaker_hints_sent": False},
        "effective_config": run["effective_config"],
        "lifecycle": {k: run[k] for k in ("connection_attempted", "connection_opened", "session_created_received", "session_updated_received", "session_finished_received", "websocket_requests_attempted", "websocket_sessions_opened", "session_finished_utc")},
        "event_counts": dict(sorted(types.items())), "response_done_statuses": response_statuses,
        "errors": redact(run["errors"], secrets), "server_errors": server_errors,
        "attributed_intervals": attributed, "unattributed_intervals": unattributed, **diagnostics,
        "native_events": {"path": f"events/{case_id}.jsonl", "sha256": digest(event_bytes), "count": len(events)},
        "prediction": {"path": f"predictions/{case_id}.rttm", "sha256": prediction_hash, "rows": len(attributed) if complete else None},
        "timing": {"started_at_utc": started_at, "completed_at_utc": utc_now(), "wall_elapsed_s": round(elapsed, 6),
                   "audio_stream_wall_s": run["audio_stream_wall_s"], "post_audio_wait_s": run["post_audio_wait_s"],
                   "received_event_elapsed_s_from_connection": [entry["wall_elapsed_s_since_connection"] for entry in events]},
        "usage": {"submitted_audio_bytes": run["bytes_sent"], "submitted_audio_seconds": run["sent_audio_s"],
                  "provider_billed_audio_seconds": None, "billing_amount": None},
        "interpretation": "Audio offsets are source-local seconds, not event-reception wall time. Unattributed and unpaired items are omitted from RTTM, never assigned a synthetic speaker. Completion does not imply every native turn has a valid attribution. References were not opened during inference."
    }
    (ROOT / "results" / f"{case_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


async def execute(cases: list[dict], all_cases: list[dict], audio: dict[str, tuple[bytes, dict]], key: str, host: str) -> None:
    secrets = (key, host, realtime_endpoint(host, "beijing"))
    for case in cases:
        case_id = case["id"]
        if (ROOT / "results" / f"{case_id}.json").exists():
            raise RuntimeError(f"Existing result must not be overwritten or re-called: {case_id}")
        started = utc_now()
        started_mono = time.monotonic()
        pcm, meta = audio[case_id]
        address, network = select_tls_address(host)
        print(json.dumps({"case_id": case_id, "tls_preflight": network}, ensure_ascii=False), flush=True)
        run = await run_live("beijing", pcm, secrets, host, key, address)
        run["network"] = network
        result = write_case(case, meta, run, started, time.monotonic() - started_mono, secrets)
        write_provenance(all_cases)
        print(json.dumps({"case_id": case_id, "status": result["status"], "audio_seconds_sent": run["sent_audio_s"],
                          "session_finished": run["session_finished_received"], "attributed": len(result["attributed_intervals"]),
                          "unattributed": len(result["unattributed_intervals"]), "boundary_issues": len(result["boundary_issues"]),
                          "event_counts": result["event_counts"], "errors": result["errors"]}, ensure_ascii=False), flush=True)


def rebuild_predictions(cases: list[dict]) -> None:
    """Repair prediction serialization strictly from completed saved native events."""
    prepared = []
    for case in cases:
        case_id = case["id"]
        result_path = ROOT / "results" / f"{case_id}.json"
        if not result_path.exists():
            continue
        result = json.loads(result_path.read_bytes())
        if result["status"] != "completed":
            continue
        if (not result["lifecycle"]["session_finished_received"] or result["audio"]["pcm_sha256"] != case["clip_pcm_sha256"]
                or result["usage"]["submitted_audio_bytes"] != case["duration_s"] * RATE * SAMPLE_WIDTH):
            raise ValueError(f"Saved completion/input mismatch: {case_id}")
        event_path = ROOT / result["native_events"]["path"]
        event_bytes = event_path.read_bytes()
        if digest(event_bytes) != result["native_events"]["sha256"]:
            raise ValueError(f"Saved native events digest mismatch: {case_id}")
        events = [json.loads(line) for line in event_bytes.splitlines()]
        if len(events) != result["native_events"]["count"]:
            raise ValueError(f"Saved native events count mismatch: {case_id}")
        attributed, unattributed, diagnostics = convert(events, case["duration_s"])
        if (attributed != result["attributed_intervals"] or unattributed != result["unattributed_intervals"]
                or diagnostics["boundary_issues"] != result["boundary_issues"]
                or diagnostics["clipped_intervals"] != result["clipped_intervals"]):
            raise ValueError(f"Saved boundary conversion mismatch: {case_id}")
        prediction_bytes = render_rttm(case_id, attributed)
        result["prediction"]["sha256"] = digest(prediction_bytes)
        prepared.append((case_id, result_path, result, prediction_bytes))
    for case_id, result_path, result, prediction_bytes in prepared:
        (ROOT / "predictions" / f"{case_id}.rttm").write_bytes(prediction_bytes)
        result_path.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    write_provenance(cases)
    print(json.dumps({"rebuilt_from_saved_native_events": [case_id for case_id, _, _, _ in prepared],
                      "network_calls": 0}, ensure_ascii=False))


def write_provenance(cases: list[dict]) -> None:
    receipts = []
    missing = []
    for case in cases:
        case_id = case["id"]
        result_path = ROOT / "results" / f"{case_id}.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
        if result is None or result["status"] != "completed":
            missing.append(case_id)
            continue
        receipts.append({
            "id": case_id,
            "input_pcm_sha256": case["clip_pcm_sha256"],
            "prediction_rttm_sha256": result["prediction"]["sha256"],
            "completed": True,
            "native_result": f"results/{case_id}.json",
            "native_result_sha256": digest(result_path.read_bytes()),
        })
    (ROOT / "predictions" / "provenance.json").write_bytes(
        (json.dumps({"model": MODEL_ID, "mode": "realtime", "status": "completed" if not missing else "incomplete",
                     "missing_cases": missing, "cases": receipts}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )

def main() -> None:
    import asyncio
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", help="Run only selected manifest IDs (otherwise all seven)")
    parser.add_argument("--provenance-only", action="store_true", help="Rebuild receipts from saved results without a network call")
    parser.add_argument("--rebuild-predictions", action="store_true", help="Repair completed RTTMs and hashes from saved native events only")
    parser.add_argument("--check-transport", action="store_true", help="Probe Beijing DNS/TLS only; never open a model session")
    args = parser.parse_args()
    if sum(bool(option) for option in (args.check_transport, args.provenance_only, args.rebuild_predictions)) > 1 or args.case and (args.check_transport or args.provenance_only or args.rebuild_predictions):
        parser.error("Offline operations and case execution cannot be combined")
    manifest = json.loads((BENCHMARK / "manifest.json").read_text(encoding="utf-8"))
    cases = manifest["cases"]
    if len(cases) != 7 or len({case["id"] for case in cases}) != 7:
        raise ValueError("Expected seven unique AMI manifest cases")
    chosen = set(args.case or [case["id"] for case in cases])
    if chosen - {case["id"] for case in cases}:
        raise ValueError("Unknown case ID")
    # Verify every clip before opening any billable socket. Never read gold here.
    audio = {case["id"]: load_audio(case) for case in cases}
    if args.provenance_only:
        (ROOT / "predictions").mkdir(parents=True, exist_ok=True)
        write_provenance(cases)
        return
    if args.rebuild_predictions:
        rebuild_predictions(cases)
        return
    key, host, _ = get_credentials("beijing")
    if not key or not host:
        raise RuntimeError("Matching Beijing host and API key unavailable")
    realtime_endpoint(host, "beijing")
    if args.check_transport:
        _, network = select_tls_address(host)
        print(json.dumps({"beijing_tls_ready": True, **network}, ensure_ascii=False))
        return
    for folder in ("results", "events", "predictions"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    write_provenance(cases)
    asyncio.run(execute([case for case in cases if case["id"] in chosen], cases, audio, key, host))


if __name__ == "__main__":
    main()
