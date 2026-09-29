import asyncio
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "qwen"))
from run import MODEL_ID, RATE, SAMPLE_WIDTH, build_segments, get_credentials, run_live

SOURCES = ROOT.parents[1] / "soniox_diarization" / "clips"
CLIPS = {"A": "1089-134686-0001", "B": "1995-1826-0003"}
ORDER = "AABBAA"


def main():
    distinct = sys.argv[1:] == ["--distinct"]
    if sys.argv[1:] and not distinct:
        raise SystemExit("Only --distinct is supported")
    clips = ({"A1": "1089-134686-0001", "B1": "1995-1826-0003",
              "A2": "1089-134686-0003", "B2": "1995-1826-0004"} if distinct else CLIPS)
    order = ("A1", "B1", "A2", "B2") if distinct else tuple(ORDER)
    events_path = "events_distinct.jsonl" if distinct else "events.jsonl"
    result_path = "result_distinct.json" if distinct else "result.json"
    samples = {}
    for label, name in clips.items():
        samples[label] = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(SOURCES / name),
             "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"],
            capture_output=True, check=True,
        ).stdout
    silence = bytes(RATE * SAMPLE_WIDTH // 2)
    pcm = bytearray()
    intervals = []
    for label in order:
        start = len(pcm) / (RATE * SAMPLE_WIDTH)
        pcm.extend(samples[label])
        end = len(pcm) / (RATE * SAMPLE_WIDTH)
        intervals.append({"label": label, "source_clip": clips[label], "start_s": start, "end_s": end,
                          "copy_sha256": sha256(samples[label]).hexdigest(), "copy_bytes": len(samples[label])})
        pcm.extend(silence)
    key, host, available = get_credentials("beijing")
    if not key or not host:
        raise RuntimeError("Beijing API key or host unavailable")
    run = asyncio.run(run_live("beijing", bytes(pcm), (key, host), host, key))
    events = run.pop("events")
    segments, details, overlaps = build_segments(events)
    native = [entry["native_event"] for entry in events]
    speaker_fields = []
    for event in native:
        def visit(obj, path):
            if isinstance(obj, dict):
                for k, value in obj.items():
                    field = f"{path}.{k}" if path else k
                    if any(word in k.lower() for word in ("speaker", "identity", "person")):
                        speaker_fields.append({"event_type": event.get("type"), "field": field, "value": value})
                    else:
                        visit(value, field)
            elif isinstance(obj, list):
                for n, value in enumerate(obj):
                    visit(value, f"{path}[{n}]")
        visit(event, "")
    summary = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_requested": MODEL_ID,
        "input": {"order": list(order) if distinct else ORDER, "intervals": intervals, "silence_after_every_clip_s": 0.5,
                  "format": "mono PCM16 LE 16000Hz", "chunk_ms": 50,
                  "duration_s": len(pcm) / (RATE * SAMPLE_WIDTH), "pcm_bytes": len(pcm),
                  "pcm_sha256": sha256(pcm).hexdigest(),
                  **({} if distinct else {"identical_copy_proof": {
                      label: len({i["copy_sha256"] for i in intervals if i["label"] == label}) == 1 for label in CLIPS}})},
        "requested_session_update": {"output_modalities": ["text"],
                                     "audio": {"input": {"turn_detection": {"type": "speaker_detection", "threshold": 0.5}}},
                                     "translation": {"language": "ko"}},
        "effective_config": run["effective_config"],
        "run": run,
        "event_counts": dict(sorted(Counter(e.get("type") for e in native).items())),
        "native_event_count": len(native),
        "native_speaker_related_fields": speaker_fields,
        "native_starts": [{k: v for k, v in e.items() if k != "type"} for e in native if e.get("type") == "input_audio_buffer.speech_started"],
        "segments": segments,
        "segment_details": details,
        "overlaps": overlaps,
        "source_transcripts": [e for e in native if e.get("type") == "conversation.item.input_audio_transcription.completed"],
        "response_done_statuses": [e.get("response", {}).get("status") for e in native if e.get("type") == "response.done"],
        "session_finish_events": [e for e in native if e.get("type") == "session.finished"],
        "server_errors": [e for e in native if e.get("type") == "error"],
        "events_path": events_path,
    }
    with (ROOT / events_path).open("w", encoding="utf-8") as output:
        for entry in events:
            output.write(json.dumps(entry, ensure_ascii=False) + "\n")
    (ROOT / result_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"duration_s": summary["input"]["duration_s"], "pcm_bytes": len(pcm),
                      "session_finished": run["session_finished_received"], "events": len(native),
                      "speaker_ids": [s["speaker"] for s in segments], "errors": run["errors"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
