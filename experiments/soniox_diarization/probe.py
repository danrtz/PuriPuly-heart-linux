from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import urllib.request

import keyring
import websockets

ROOT = Path(__file__).resolve().parent
RATE = 16000
STEP = RATE // 20
URL = "wss://stt-rt.soniox.com/transcribe-websocket"


def fixture(manifest: dict) -> tuple[bytes, list[dict], list[dict]]:
    audio = bytearray()
    turns = []
    provenance = []
    cache = ROOT / "clips"
    cache.mkdir(exist_ok=True)
    silence = bytes(round(manifest["silence_between_clips_s"] * RATE) * 2)
    for item in manifest["clips"]:
        source = cache / item["utt_id"]
        url = manifest["mirror"].rstrip("/") + "/resolve/main/audio/" + item["path"]
        if not source.exists():
            with urllib.request.urlopen(url, timeout=30) as response:
                source.write_bytes(response.read())
        digest = sha256(source.read_bytes()).hexdigest()
        decoded = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(source), "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"],
            capture_output=True,
            check=True,
        ).stdout
        start = len(audio) / (RATE * 2)
        audio.extend(decoded)
        end = len(audio) / (RATE * 2)
        turns.append({"speaker": item["speaker"], "start_s": start, "end_s": end, "utt_id": item["utt_id"]})
        provenance.append({"url": url, "sha256": digest, "bytes": source.stat().st_size})
        audio.extend(silence)
    print(f"fixture_sha256={sha256(audio).hexdigest()} source_seconds={len(audio) / (RATE * 2):.3f} turns={json.dumps(turns)}", flush=True)
    return bytes(audio), turns, provenance


def regions(arm: str, duration_s: float) -> list[dict]:
    if arm == "continuous":
        return [{"pieces": [(0.0, duration_s)], "reason": "stream_end", "padding_ms": 0}]
    if arm != "forced":
        raise ValueError(arm)
    width = 6.0
    cuts = [0.0]
    while cuts[-1] + width < duration_s:
        cuts.append(cuts[-1] + width)
    cuts.append(duration_s)
    return [{"pieces": [(a, b)], "reason": "fixed_six_seconds", "padding_ms": 0} for a, b in zip(cuts, cuts[1:])]


async def live_arm(arm: str, pcm: bytes, hints: list[str], api_key: str, slices: list[dict]) -> dict:
    duration = len(pcm) / (RATE * 2)
    config = {
        "api_key": api_key,
        "model": "stt-rt-v5",
        "audio_format": "pcm_s16le",
        "sample_rate": RATE,
        "num_channels": 1,
        "enable_endpoint_detection": False,
        "enable_language_identification": False,
        "enable_speaker_diarization": True,
    }
    if hints:
        config["language_hints"] = hints
    tokens: list[dict] = []
    messages: list[dict] = []
    fin_count = 0
    sent_seconds = 0.0
    timeline: list[dict] = []
    async with websockets.connect(URL, ping_interval=None, open_timeout=12) as ws:
        await ws.send(json.dumps(config))

        async def drain(until_fin: bool) -> None:
            nonlocal fin_count
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=22)
                message = json.loads(raw)
                if any(k in message for k in ("error", "error_code", "error_type")):
                    raise RuntimeError("Soniox response error: " + json.dumps(message))
                message_tokens = message.get("tokens") or []
                saw_fin = False
                for token in message_tokens:
                    if not token.get("is_final"):
                        continue
                    if token.get("text") == "<fin>":
                        fin_count += 1
                        saw_fin = True
                    elif token.get("text") != "<end>":
                        tokens.append({"text": token.get("text"), "speaker": token.get("speaker"), "start_ms": token.get("start_ms"), "end_ms": token.get("end_ms"), "request_id": message.get("request_id")})
                messages.append({"request_id": message.get("request_id"), "finished": message.get("finished"), "final_count": sum(bool(t.get("is_final")) for t in message_tokens), "fin": saw_fin})
                if saw_fin and until_fin:
                    return
                if message.get("finished"):
                    return

        receiver = asyncio.create_task(drain(False))
        try:
            for index, segment in enumerate(slices):
                if receiver.done():
                    await receiver
                    raise RuntimeError("Soniox stream ended before audio was sent")
                for a, b in segment["pieces"]:
                    chunk = pcm[round(a * RATE) * 2:round(b * RATE) * 2]
                    timeline.append({"provider_start_s": sent_seconds, "provider_end_s": sent_seconds + len(chunk) / (RATE * 2), "source_start_s": a, "source_end_s": b, "boundary": index != 0})
                    for start in range(0, len(chunk), STEP * 2):
                        await ws.send(chunk[start:start + STEP * 2])
                        await asyncio.sleep(min(STEP * 2, len(chunk) - start) / (RATE * 2))
                    sent_seconds += len(chunk) / (RATE * 2)
                if arm != "continuous":
                    if segment["padding_ms"]:
                        padding = bytes(RATE * 2 * segment["padding_ms"] // 1000)
                        await ws.send(padding)
                        sent_seconds += len(padding) / (RATE * 2)
                        timeline.append({"provider_start_s": sent_seconds - len(padding) / (RATE * 2), "provider_end_s": sent_seconds, "source_start_s": None, "source_end_s": None, "boundary": False})
                    await ws.send(json.dumps({"type": "finalize"}))
                    target = index + 1
                    while fin_count < target:
                        await asyncio.sleep(0.02)
                        if receiver.done():
                            await receiver
                            raise RuntimeError("Soniox stream ended before finalize response")
            if arm == "continuous":
                await ws.send(json.dumps({"type": "finalize"}))
                while fin_count < 1:
                    await asyncio.sleep(0.02)
                    if receiver.done():
                        await receiver
                        raise RuntimeError("Soniox stream ended before finalize response")
            await ws.send("")
            await asyncio.wait_for(receiver, timeout=25)
        finally:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
    return {"arm": arm, "model": "stt-rt-v5", "config": {k: v for k, v in config.items() if k != "api_key"}, "duration_s": duration, "sent_seconds": round(sent_seconds, 3), "websocket_requests": 1, "fin_count": fin_count, "segments": [{k: v for k, v in segment.items() if k != "pieces"} | {"pieces": len(segment["pieces"])} for segment in slices], "timeline": timeline, "tokens": tokens, "messages": messages}


def metrics(result: dict, truth: list[dict]) -> dict:
    by_truth: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, list[str]] = defaultdict(list)
    skipped = Counter()
    for token in result["tokens"]:
        text = str(token["text"] or "")
        if not any(c.isalnum() for c in text):
            skipped["nonlexical"] += 1
            continue
        start, end = token["start_ms"], token["end_ms"]
        if not isinstance(start, (float, int)) or not isinstance(end, (float, int)):
            skipped["untimed"] += 1
            continue
        center = (start + end) / 2000
        mapped = [part for part in result["timeline"] if part["provider_start_s"] <= center < part["provider_end_s"]]
        if len(mapped) != 1 or mapped[0]["source_start_s"] is None:
            skipped["outside_source"] += 1
            continue
        source_time = mapped[0]["source_start_s"] + center - mapped[0]["provider_start_s"]
        labeled = [turn for turn in truth if turn["start_s"] <= source_time < turn["end_s"]]
        if len(labeled) != 1:
            skipped["unlabeled_or_overlap"] += 1
            continue
        label = labeled[0]["speaker"]
        speaker = token["speaker"]
        if speaker is None or isinstance(speaker, bool):
            skipped["missing_speaker"] += 1
            continue
        speaker = str(speaker)
        by_truth[label][speaker] += 1
        if len(examples[label]) < 12:
            examples[label].append(f"{text.strip()}:{speaker}@{source_time:.2f}")
    labels = sorted(by_truth)
    identified = sum(sum(counts.values()) for counts in by_truth.values())
    same_total = same_split = cross_total = cross_merge = 0
    for i, label in enumerate(labels):
        row = by_truth[label]
        n = sum(row.values())
        same_total += n * (n - 1) // 2
        same_split += (n * (n - 1) - sum(value * (value - 1) for value in row.values())) // 2
        for other in labels[i + 1:]:
            cross_total += n * sum(by_truth[other].values())
            cross_merge += sum(value * by_truth[other][speaker] for speaker, value in row.items())
    return {"identified_labeled_lexical_tokens": identified, "labels_observed": labels, "speaker_ids": sorted({id for row in by_truth.values() for id in row}), "confusion": {label: dict(by_truth[label]) for label in labels}, "same_speaker_split_pairs": same_split, "same_speaker_pairs": same_total, "different_speaker_merge_pairs": cross_merge, "different_speaker_pairs": cross_total, "excluded_tokens": dict(skipped), "examples": dict(examples)}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=("continuous", "forced", "segmented", "all"), default="all")
    parser.add_argument("--segments-only", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "fixture.json").read_text(encoding="utf-8"))
    pcm, turns, provenance = fixture(manifest)
    if args.segments_only or args.arm in ("all", "segmented"):
        from app_segments import app_segments
        app_slices, app_diagnostics = await app_segments(pcm)
        (ROOT / "segments.json").write_text(json.dumps({"segments": app_slices, "diagnostics": app_diagnostics}, indent=2) + "\n", encoding="utf-8")
        print(f"app_segments={len(app_slices)} diagnostics={json.dumps(app_diagnostics)} sizes={json.dumps([{'reason': s['reason'], 'content_ms': s['content_ms'], 'padding_ms': s['padding_ms'], 'pieces': len(s['pieces'])} for s in app_slices])}", flush=True)
        if args.segments_only:
            return
    else:
        app_slices = []
    key = os.environ.get("SONIOX_API_KEY") or keyring.get_password("puripuly-heart", "soniox_api_key")
    if not key:
        raise RuntimeError("SONIOX_API_KEY/keyring credential unavailable")
    for arm in ("continuous", "forced", "segmented") if args.arm == "all" else (args.arm,):
        print(f"starting={arm} source_seconds={len(pcm) / RATE / 2:.3f}", flush=True)
        result = await live_arm(arm, pcm, manifest.get("language_hints", []), key, app_slices if arm == "segmented" else regions(arm, len(pcm) / RATE / 2))
        result["metrics"] = metrics(result, turns)
        result["fixture"] = {"dataset": manifest["dataset"], "license": manifest["license"], "source_sha256": sha256(pcm).hexdigest(), "turns": turns, "clips": provenance}
        (ROOT / f"{arm}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"completed={arm} sent_seconds={result['sent_seconds']} fin_count={result['fin_count']} final_tokens={len(result['tokens'])} metrics={json.dumps(result['metrics'], ensure_ascii=False)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
