from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from puripuly_heart.config.resolved import vad_exit_threshold
from puripuly_heart.core.audio.format import AudioCaptureSpan
from puripuly_heart.core.audio.listen_delivery import ListenDeliveryController
from puripuly_heart.core.audio.ownership import AudioSegmentSettingsSnapshot, PeerAudioSegmentLedger
from puripuly_heart.core.audio.smart_turn import SmartTurnInferenceOwner, SMART_TURN_COMPLETE_THRESHOLD
from puripuly_heart.core.vad.bundled import bundled_silero_vad_onnx_path
from puripuly_heart.core.vad.gating import SpeechChunk, SpeechEnd, SpeechStart, create_peer_vad_gating
from puripuly_heart.core.vad.silero import SileroVadOnnx

RATE = 16000


async def app_segments(pcm: bytes) -> tuple[list[dict], dict]:
    vad = create_peer_vad_gating(
        SileroVadOnnx(bundled_silero_vad_onnx_path()),
        sample_rate_hz=RATE,
        ring_buffer_ms=500,
        speech_threshold=0.3,
        hangover_ms=500,
    )
    settings = AudioSegmentSettingsSnapshot(
        provider_id="soniox",
        provider_signature=("stt-rt-v5",),
        runtime_signature=("probe",),
        source_mode="manual",
        source_language="zh-CN",
        expected_languages=("zh-CN", "ja"),
        target_sample_rate_hz=RATE,
        vad_speech_threshold=0.3,
        vad_exit_threshold=vad_exit_threshold(0.3),
        vad_hangover_ms=500,
        vad_pre_roll_ms=500,
        delivery_profile_effective="on",
        delivery_availability="ready",
        delivery_threshold=SMART_TURN_COMPLETE_THRESHOLD,
    )
    ledger = PeerAudioSegmentLedger(activation_generation=1, settings=settings)
    source_clock = [0.0]
    smart = SmartTurnInferenceOwner(clock=lambda: source_clock[0])
    segments: list[dict] = []
    active: dict | None = None

    async def emit(owned) -> None:
        nonlocal active
        event = owned.event
        if isinstance(event, SpeechStart):
            active = {"pieces": [], "reason": None, "genuine_onset": event.genuine_onset, "observed_trailing_silence_ms": None}
            for span in (*event.pre_roll_capture, *event.chunk_capture):
                active["pieces"].append((span.source_start_sample / RATE, span.source_end_sample / RATE))
        elif isinstance(event, SpeechChunk):
            if active is None:
                raise RuntimeError("chunk without active turn")
            for span in event.chunk_capture:
                active["pieces"].append((span.source_start_sample / RATE, span.source_end_sample / RATE))
        elif isinstance(event, SpeechEnd):
            if active is None:
                raise RuntimeError("end without active turn")
            active["reason"] = event.reason
            active["observed_trailing_silence_ms"] = event.trailing_silence_ms
            content_ms = owned.segment.content_sample_count * 1000 / RATE
            active["content_ms"] = content_ms
            active["padding_ms"] = 200 if event.reason == "delivery_deadline" or (event.reason == "delivery_pause" and 4000 <= content_ms < 7000) else 0
            segments.append(active)
            active = None

    controller = ListenDeliveryController(
        vad=vad,
        ledger=ledger,
        emit=emit,
        monotonic_clock=lambda: source_clock[0],
        smart_turn_owner=smart,
    )
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    size = vad.chunk_samples
    for index, start in enumerate(range(0, len(samples) - size + 1, size)):
        end = start + size
        source_clock[0] = end / RATE
        chunk = samples[start:end]
        capture = AudioCaptureSpan(
            capture_epoch=0,
            callback_sequence=index,
            source_sample_rate_hz=RATE,
            source_start_sample=start,
            source_end_sample=end,
            source_start_monotonic_s=start / RATE,
            source_end_monotonic_s=end / RATE,
            normalized_sample_rate_hz=RATE,
            normalized_start_sample=start,
            normalized_end_sample=end,
        )
        for event in vad.process_owned_chunk(chunk, (capture,)):
            await controller.handle_vad_event(event)
        await controller.observe_acoustic_chunk(speech_observed=vad.last_observation_was_speech, capture=(capture,))
        await asyncio.sleep(size / RATE)
    end = vad.seal_active(reason="source_eof")
    if end is not None:
        await controller.handle_vad_event(end)
    snapshot = smart.snapshot
    await controller.close()
    await smart.close()
    return segments, {"vad_model": "silero-v6.2.1", "smart_turn_availability": snapshot.availability, "smart_turn_inferences": snapshot.inference_count, "smart_turn_busy_skips": snapshot.busy_skip_count, "dropped_eof_samples": len(samples) % size}
