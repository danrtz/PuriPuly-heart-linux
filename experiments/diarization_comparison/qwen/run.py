from __future__ import annotations

import argparse
import asyncio
import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import time
import wave
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import keyring
import websockets

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT.parent / "nemotron" / "fixture.wav"
MODEL_ID = "qwen3.8-livetranslate-flash-realtime"
SOURCE_SHA256 = "2eb1ab143c2a7dbaa7448c31b44dd8c517b85042e769f2da5d2ddaec14028762"
RATE = 16000
SAMPLE_WIDTH = 2
CHUNK_MS = 50
REGIONS = {
    "beijing": {
        "endpoint_region": "cn-beijing",
        "key_name": "alibaba_api_key_beijing",
        "key_env": "ALIBABA_API_KEY_BEIJING",
        "host_env": "ALIBABA_API_HOST_BEIJING",
    },
    "singapore": {
        "endpoint_region": "ap-southeast-1",
        "key_name": "alibaba_api_key_singapore",
        "key_env": "ALIBABA_API_KEY_SINGAPORE",
        "host_env": "ALIBABA_API_HOST_SINGAPORE",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fixture_audio(path: Path) -> tuple[bytes, float, str]:
    with wave.open(str(path), "rb") as source:
        shape = (source.getnchannels(), source.getsampwidth(), source.getframerate())
        if shape != (1, SAMPLE_WIDTH, RATE):
            raise ValueError("Fixture must be mono PCM16 at 16 kHz")
        pcm = source.readframes(source.getnframes())
        duration_s = source.getnframes() / RATE

    actual = sha256(pcm).hexdigest()
    if actual != SOURCE_SHA256:
        raise ValueError(f"Fixture SHA-256 mismatch: {actual}")
    return pcm, duration_s, actual


def local_env_values(region: str) -> dict[str, str]:
    config = REGIONS[region]
    path = Path.home() / "Documents" / "dev" / "puripuly_heart" / ".env.local"
    wanted = {config["key_env"], config["host_env"], "DASHSCOPE_API_KEY"}
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        entry = entry.removeprefix("export ").strip()
        name, separator, value = entry.partition("=")
        name = name.strip()
        if not separator or name not in wanted:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[name] = value
    return values


def get_credentials(region: str) -> tuple[str | None, str | None, bool]:
    config = REGIONS[region]
    local_values = local_env_values(region)
    api_key = os.environ.get(config["key_env"]) or local_values.get(config["key_env"])
    if not api_key:
        api_key = keyring.get_password("puripuly-heart", config["key_name"])
    if not api_key:
        api_key = os.environ.get("DASHSCOPE_API_KEY") or local_values.get("DASHSCOPE_API_KEY")
    host = os.environ.get(config["host_env"]) or local_values.get(config["host_env"])
    return api_key or None, host or None, bool(api_key)


def redact(value, secrets: tuple[str, ...]):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, secrets) for key, item in value.items()}
    return value

def realtime_endpoint(host: str, region: str) -> str:
    config = REGIONS[region]
    candidate = host.strip()
    if "://" not in candidate:
        candidate = "wss://" + candidate
    try:
        parts = urlsplit(candidate)
        hostname = parts.hostname
        suffix = f".{config['endpoint_region']}.maas.aliyuncs.com"
        if (
            parts.scheme not in ("wss", "https")
            or hostname is None
            or not (hostname.lower().endswith(suffix) or hostname.lower() == suffix[1:])
            or parts.username is not None
            or parts.password is not None
            or parts.port not in (None, 443)
        ):
            raise ValueError
        path = parts.path.rstrip("/")
        endpoint_path = "/api-ws/v1/realtime"
        if path.endswith(endpoint_path):
            pass
        elif path.endswith("/api-ws/v1"):
            path += "/realtime"
        elif path in ("", "/"):
            path = endpoint_path
        else:
            raise ValueError
        query = [(name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True) if name != "model"]
        query.append(("model", MODEL_ID))
        return urlunsplit(("wss", parts.netloc, path, urlencode(query), ""))
    except ValueError:
        raise ValueError("provided_host_not_supported_for_official_realtime_endpoint") from None



def build_segments(events: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    boundaries: dict[str, dict[str, list[dict]]] = defaultdict(lambda: {"starts": [], "stops": []})
    for index, entry in enumerate(events):
        native = entry.get("native_event")
        if not isinstance(native, dict):
            continue
        event_type = native.get("type")
        if event_type not in ("input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped"):
            continue
        item_id = native.get("item_id")
        item_key = str(item_id) if item_id is not None else f"__unkeyed_{index}"
        collection = "starts" if event_type.endswith("speech_started") else "stops"
        boundaries[item_key][collection].append(native)

    segments = []
    details = []
    for item_key, grouped in boundaries.items():
        starts = grouped["starts"]
        stops = grouped["stops"]
        start_ms = starts[0].get("audio_start_ms") if len(starts) == 1 else None
        end_ms = stops[0].get("audio_end_ms") if len(stops) == 1 else None
        speakers = {str(event["speaker_id"]) for event in starts if event.get("speaker_id") is not None}
        speaker = next(iter(speakers)) if len(speakers) == 1 and len(starts) == 1 else None
        issues = []
        if item_key.startswith("__unkeyed_"):
            issues.append("missing_item_id")
        if len(starts) == 0:
            issues.append("missing_speech_started")
        elif len(starts) > 1:
            issues.append("multiple_speech_started_events_ambiguous")
        if len(stops) == 0:
            issues.append("unfinished_missing_speech_stopped")
        elif len(stops) > 1:
            issues.append("multiple_speech_stopped_events_ambiguous")
        if len(starts) == 1 and start_ms is None:
            issues.append("missing_audio_start_ms")
        if len(stops) == 1 and end_ms is None:
            issues.append("missing_audio_end_ms")
        if len(starts) == 1 and not speakers:
            issues.append("missing_speaker_attribution")
        if len(speakers) > 1:
            issues.append("conflicting_speaker_attribution")
        start_s = start_ms / 1000 if isinstance(start_ms, (int, float)) else None
        end_s = end_ms / 1000 if isinstance(end_ms, (int, float)) else None
        if start_s is not None and end_s is not None and end_s < start_s:
            issues.append("end_precedes_start")
            start_s = None
            end_s = None
        segments.append({"start_s": start_s, "end_s": end_s, "speaker": speaker})
        details.append({
            "item_id": None if item_key.startswith("__unkeyed_") else item_key,
            "status": "bounded" if not issues else "ambiguous_or_unfinished",
            "issues": issues,
            "speech_started_event_count": len(starts),
            "speech_stopped_event_count": len(stops),
        })

    overlap_pairs = []
    for left in range(len(segments)):
        a = segments[left]
        if a["start_s"] is None or a["end_s"] is None:
            continue
        for right in range(left + 1, len(segments)):
            b = segments[right]
            if b["start_s"] is None or b["end_s"] is None:
                continue
            if a["start_s"] < b["end_s"] and b["start_s"] < a["end_s"]:
                overlap_pairs.append({"segment_indices": [left, right], "item_ids": [details[left]["item_id"], details[right]["item_id"]]})
    return segments, details, overlap_pairs


class EventCollector:
    def __init__(self, connected_at: float):
        self.connected_at = connected_at
        self.events: list[dict] = []
        self.changed = asyncio.Event()
        self.closed = False
        self.receive_error: Exception | None = None

    async def receive(self, socket, secrets: tuple[str, ...]) -> None:
        try:
            async for message in socket:
                received_mono = time.monotonic()
                received_utc = utc_now()
                try:
                    native_event = json.loads(message)
                    if not isinstance(native_event, dict):
                        native_event = {"_non_object_event": native_event}
                except json.JSONDecodeError:
                    native_event = {"_unparsed_message": message}
                self.events.append({
                    "received_at_utc": received_utc,
                    "wall_elapsed_s_since_connection": round(received_mono - self.connected_at, 6),
                    "native_event": redact(native_event, secrets),
                })
                self.changed.set()
        except Exception as exc:
            self.receive_error = exc
        finally:
            self.closed = True
            self.changed.set()

    async def wait_for_type(self, event_types: set[str], timeout_s: float) -> dict:
        async def wait_loop() -> dict:
            while True:
                for entry in self.events:
                    native = entry.get("native_event")
                    if isinstance(native, dict) and native.get("type") in event_types:
                        return entry
                if self.closed:
                    if self.receive_error is not None:
                        raise RuntimeError(type(self.receive_error).__name__) from None
                    raise RuntimeError("websocket_closed_before_expected_event")
                self.changed.clear()
                await self.changed.wait()
        return await asyncio.wait_for(wait_loop(), timeout=timeout_s)


async def run_live(region: str, pcm: bytes, secrets: tuple[str, ...], host_url: str, api_key: str) -> dict:
    endpoint = realtime_endpoint(host_url, region)
    result = {
        "connection_attempted": True,
        "connection_opened": False,
        "session_created_received": False,
        "session_updated_received": False,
        "session_finished_received": False,
        "effective_config": None,
        "events": [],
        "errors": [],
        "bytes_sent": 0,
        "sent_audio_s": 0.0,
        "audio_stream_wall_s": None,
        "post_audio_wait_s": None,
        "websocket_requests_attempted": 1,
        "websocket_sessions_opened": 0,
        "session_finished_utc": None,
    }
    collector = None
    receiver = None
    first_connection_mono = time.monotonic()
    stream_start = None
    audio_finished_mono = None
    try:
        async with websockets.connect(
            endpoint,
            additional_headers={"Authorization": f"Bearer {api_key}"},
            open_timeout=30,
            close_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            max_size=16 * 1024 * 1024,
        ) as socket:
            connected_mono = time.monotonic()
            result["connection_opened"] = True
            result["websocket_sessions_opened"] = 1
            collector = EventCollector(connected_mono)
            receiver = asyncio.create_task(collector.receive(socket, secrets))
            initial = await collector.wait_for_type({"session.created", "error"}, 30)
            if initial["native_event"].get("type") == "error":
                raise RuntimeError("server_rejected_initial_session")
            result["session_created_received"] = True
            await socket.send(json.dumps({
                "type": "session.update",
                "session": {
                    "output_modalities": ["text"],
                    "audio": {"input": {"turn_detection": {"type": "speaker_detection", "threshold": 0.5}}},
                    "translation": {"language": "ko"},
                },
            }, separators=(",", ":")))
            configured = await collector.wait_for_type({"session.updated", "error"}, 30)
            if configured["native_event"].get("type") == "error":
                raise RuntimeError("server_rejected_session_configuration")
            result["session_updated_received"] = True
            result["effective_config"] = configured["native_event"].get("session")

            chunk_bytes = RATE * SAMPLE_WIDTH * CHUNK_MS // 1000
            stream_start = time.monotonic()
            bytes_sent = 0
            for offset in range(0, len(pcm), chunk_bytes):
                chunk = pcm[offset:offset + chunk_bytes]
                due = stream_start + offset / (RATE * SAMPLE_WIDTH)
                delay = due - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                await socket.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(chunk).decode("ascii"),
                }, separators=(",", ":")))
                bytes_sent += len(chunk)
                result["bytes_sent"] = bytes_sent
                result["sent_audio_s"] = bytes_sent / (RATE * SAMPLE_WIDTH)
            audio_end_due = stream_start + len(pcm) / (RATE * SAMPLE_WIDTH)
            tail_delay = audio_end_due - time.monotonic()
            if tail_delay > 0:
                await asyncio.sleep(tail_delay)
            audio_finished_mono = time.monotonic()
            result["bytes_sent"] = bytes_sent
            result["sent_audio_s"] = bytes_sent / (RATE * SAMPLE_WIDTH)
            result["audio_stream_wall_s"] = audio_finished_mono - stream_start
            await socket.send(json.dumps({"type": "session.finish"}, separators=(",", ":")))
            finished = await collector.wait_for_type({"session.finished", "error"}, 180)
            result["post_audio_wait_s"] = time.monotonic() - audio_finished_mono
            if finished["native_event"].get("type") == "error":
                raise RuntimeError("server_reported_error_before_session_finished")
            result["session_finished_received"] = True
            result["session_finished_utc"] = utc_now()
            await asyncio.sleep(0.1)
            result["events"] = collector.events
    except Exception as exc:
        elapsed = time.monotonic() - first_connection_mono
        if stream_start is not None:
            result["audio_stream_wall_s"] = time.monotonic() - stream_start
        if audio_finished_mono is not None and result["post_audio_wait_s"] is None:
            result["post_audio_wait_s"] = time.monotonic() - audio_finished_mono
        result["errors"].append({
            "type": type(exc).__name__,
            "message": redact(str(exc), secrets),
            "elapsed_s": round(elapsed, 6),
        })
        if collector is not None:
            result["events"] = collector.events
    finally:
        if receiver is not None and not receiver.done():
            receiver.cancel()
            try:
                await receiver
            except asyncio.CancelledError:
                pass
    return result


def safe_event_counts(events: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(
        entry.get("native_event", {}).get("type", "unknown")
        for entry in events
        if isinstance(entry.get("native_event"), dict)
    ).items()))


def make_result(region: str, fixture_path: Path, source_sha: str | None, duration_s: float | None, requested_config: dict, run: dict | None, errors: list[dict], started_at: str, started_mono: float) -> dict:
    events = run["events"] if run else []
    segments, segment_details, overlaps = build_segments(events)
    event_counts = safe_event_counts(events)
    boundary_end_ms = [
        entry["native_event"].get("audio_end_ms")
        for entry in events
        if isinstance(entry.get("native_event"), dict)
        and entry["native_event"].get("type") == "input_audio_buffer.speech_stopped"
        and isinstance(entry["native_event"].get("audio_end_ms"), (int, float))
    ]
    provider_audio_s = max(boundary_end_ms, default=0) / 1000
    ended = bool(run and run.get("session_finished_received"))
    responses_done = [
        entry["native_event"].get("response", {}).get("status")
        for entry in events
        if isinstance(entry.get("native_event"), dict) and entry["native_event"].get("type") == "response.done"
    ]
    unmatched = [
        {"segment_index": index, "item_id": segment_details[index]["item_id"], "start_s": segment["start_s"], "end_s": segment["end_s"], "issues": segment_details[index]["issues"]}
        for index, segment in enumerate(segments)
        if segment_details[index]["issues"]
    ]
    if not events and duration_s is not None:
        unknown_intervals = [{"start_s": 0.0, "end_s": duration_s, "reason": "No live provider events; source audio was not processed"}]
    elif not boundary_end_ms and duration_s is not None:
        unknown_intervals = [{"start_s": 0.0, "end_s": duration_s, "reason": "No provider speech-boundary audio offsets were observed"}]
    elif not ended and duration_s is not None:
        tail_start_s = min(provider_audio_s, duration_s)
        unknown_intervals = [{
            "start_s": tail_start_s,
            "end_s": duration_s,
            "reason": "session.finished was not observed; final input/response completion is unconfirmed",
        }] if tail_start_s < duration_s else []
    else:
        unknown_intervals = []
    audio_bytes = run["bytes_sent"] if run else 0
    sent_audio_s = run["sent_audio_s"] if run else 0.0
    opened = bool(run and run["connection_opened"])
    elapsed = time.monotonic() - started_mono
    response_done_count = len(responses_done)
    requested_configured = bool(run and run.get("session_updated_received"))
    evaluated = bool(run and run["bytes_sent"] > 0)
    status = "completed" if ended and requested_configured and not errors else "partial" if evaluated else "not_evaluated"
    timing = {
        "nominal_latency_s": None,
        "nominal_delay_s": None,
        "documented_model_latency_claim_s": 2.3,
        "documented_model_latency_claim_note": "Alibaba Model Studio describes latency as low as 2.3 seconds; this is not measured for this run.",
        "measured_runtime_s": round(elapsed, 6),
        "wall_clock_runtime_s": round(elapsed, 6),
        "sent_audio_s": round(sent_audio_s, 6),
        "provider_audio_s": round(provider_audio_s, 6),
        "provider_audio_max_boundary_offset_s": round(provider_audio_s, 6),
        "provider_audio_s_note": "Maximum observed speech_stopped audio_end_ms offset from stream start; never a wall-clock reception delay or assumed full-stream duration.",
        "audio_stream_wall_s": round(run["audio_stream_wall_s"], 6) if run and run["audio_stream_wall_s"] is not None else None,
        "post_audio_wait_s": round(run["post_audio_wait_s"], 6) if run and run["post_audio_wait_s"] is not None else None,
        "event_reception_elapsed_s": [entry["wall_elapsed_s_since_connection"] for entry in events],
        "timing_basis": "Provider audio offsets remain in native speech_started/speech_stopped events; reception timestamps and elapsed wall time are recorded separately.",
    }
    return {
        "status": status,
        "evaluation_status": "evaluated" if evaluated else "not_evaluated",
        "model": MODEL_ID,
        "region": {"name": region, "endpoint_region": REGIONS[region]["endpoint_region"]},
        "endpoint_template": f"wss://[provided-{region}-host]/api-ws/v1/realtime?model={MODEL_ID}",
        "endpoint_host_source": f"{REGIONS[region]['host_env']} from local env (value omitted)",
        "source_sha256": source_sha,
        "source_audio": {
            "path": str(fixture_path.relative_to(ROOT.parent)).replace("\\", "/") if fixture_path.is_relative_to(ROOT.parent) else "external fixture path omitted",
            "duration_s": duration_s,
            "format": {"channels": 1, "sample_rate_hz": RATE, "sample_format": "signed PCM16 little-endian"},
        },
        "requested_config": requested_config,
        "effective_config": run.get("effective_config") if run else None,
        "effective_config_confirmed_by_server": bool(run and run["session_updated_received"]),
        "documented_max_speaker_count": None,
        "documented_max_speaker_count_note": "Official documentation does not state a maximum speaker count.",
        "segments": segments if evaluated else None,
        "segment_details": segment_details if evaluated else None,
        "overlap_pairs": overlaps if evaluated else None,
        "unknown_coverage": unknown_intervals,
        "coverage": {
            "evaluated": evaluated,
            "provider_speech_boundary_count": event_counts.get("input_audio_buffer.speech_started", 0) if evaluated else None,
            "bounded_segment_count": sum(detail["status"] == "bounded" for detail in segment_details) if evaluated else None,
            "unbounded_or_ambiguous_segments": unmatched if evaluated else None,
            "missing_speaker_attribution_count": sum("missing_speaker_attribution" in detail["issues"] for detail in segment_details) if evaluated else None,
            "overlap_pair_count": len(overlaps) if evaluated else None,
            "source_audio_processed": bool(run and run["bytes_sent"] > 0),
            "session_finished": ended,
        },
        "completion": {
            "session_created_received": bool(run and run["session_created_received"]),
            "session_updated_received": bool(run and run["session_updated_received"]),
            "session_finished_received": ended,
            "response_done_count": response_done_count,
            "response_done_statuses": responses_done,
            "all_observed_responses_completed": bool(responses_done) and all(status == "completed" for status in responses_done),
        },
        "event_counts": event_counts,
        "timing": timing,
        "usage": {
            "websocket_requests_attempted": run["websocket_requests_attempted"] if run else 0,
            "websocket_sessions_opened": run["websocket_sessions_opened"] if run else 0,
            "submitted_audio_bytes": audio_bytes,
            "submitted_audio_seconds": round(sent_audio_s, 6),
            "provider_billed_audio_seconds": None,
            "billing_amount": None,
            "billing_amount_known": False,
        },
        "run": {
            "command": f"python run.py --region {region}",
            "started_at_utc": started_at,
            "wall_clock_runtime_s": round(elapsed, 6),
            "websocket_connection_attempted": bool(run and run["connection_attempted"]),
            "websocket_connection_opened": opened,
            "audio_bytes_sent": audio_bytes,
            "audio_seconds_sent": round(sent_audio_s, 6),
            "session_finished_at_utc": run.get("session_finished_utc") if run else None,
        },
        "errors": errors,
        "events_path": "events.jsonl",
        "native_event_count": len(events),
    }


def write_artifacts(result: dict) -> None:
    events = result.pop("_native_events", [])
    with (ROOT / "events.jsonl").open("w", encoding="utf-8", newline="\n") as output:
        for event in events:
            output.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    with (ROOT / "result.json").open("w", encoding="utf-8", newline="\n") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write("\n")


async def main_async(region: str, fixture_path: Path) -> dict:
    started_mono = time.monotonic()
    started_at = utc_now()
    requested_config = {
        "output_modalities": ["text"],
        "target_language": "ko",
        "source_asr": "always enabled by model; no override sent",
        "input_audio": {"format": "mono PCM16 little-endian", "sample_rate_hz": RATE, "chunk_duration_ms": CHUNK_MS},
        "turn_detection": {"type": "speaker_detection", "threshold": 0.5},
        "speaker_count_hint": None,
        "speaker_descriptions": None,
    }
    source_sha = None
    duration_s = None
    pcm = b""
    errors = []
    run = None
    try:
        pcm, duration_s, source_sha = fixture_audio(fixture_path)
    except Exception as exc:
        errors.append({"type": "fixture_error", "message": str(exc)})
    api_key, host_url, api_key_available = get_credentials(region)
    secrets = tuple(secret for secret in (api_key, host_url) if secret)
    if not errors and api_key is None:
        errors.append({"type": "missing_prerequisite", "code": "missing_region_api_key", "message": "No region-specific API key found in environment, local env file, or puripuly-heart keyring."})
    if not errors and host_url is None:
        errors.append({"type": "missing_prerequisite", "code": "missing_region_api_host", "message": f"No {REGIONS[region]['host_env']} is available in the process environment or local env file."})
    if not errors and api_key is not None and host_url is not None:
        run = await run_live(region, pcm, secrets, host_url, api_key)
        errors.extend(run["errors"])
    result = make_result(region, fixture_path, source_sha, duration_s, requested_config, run, errors, started_at, started_mono)
    result["_native_events"] = run["events"] if run is not None else []
    result["run"]["api_key_available"] = api_key_available
    result["run"]["api_host_available"] = bool(host_url)
    write_artifacts(result)
    return json.loads((ROOT / "result.json").read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", choices=tuple(REGIONS), default=os.environ.get("QWEN_LIVETRANSLATE_REGION", "beijing"))
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    args = parser.parse_args()
    result = asyncio.run(main_async(args.region, args.fixture.resolve()))
    print(json.dumps({
        "status": result["status"],
        "model": result["model"],
        "region": result["region"]["name"],
        "source_sha256": result["source_sha256"],
        "native_event_count": result["native_event_count"],
        "websocket_requests_attempted": result["usage"]["websocket_requests_attempted"],
        "audio_seconds_sent": result["usage"]["submitted_audio_seconds"],
        "session_finished_received": result["completion"]["session_finished_received"],
        "error_codes": [error.get("code") for error in result["errors"]],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
