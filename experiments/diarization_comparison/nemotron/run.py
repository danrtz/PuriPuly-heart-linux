import argparse
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import time
import wave

import numpy as np
import torch
from huggingface_hub import try_to_load_from_cache
from transformers import AutoModelForAudioFrameClassification, AutoProcessor

ROOT = Path(__file__).resolve().parent
MODEL_ID = "nvidia/Nemotron-3-Diarization"
REVISION = "f667ed73aee57d40cc39428eb768b4fd87a0a29e"
PCM_SHA256 = "2eb1ab143c2a7dbaa7448c31b44dd8c517b85042e769f2da5d2ddaec14028762"
STREAM_MODES = ("low_latency", "very_low_latency", "ultra_low_latency")


def original_audio() -> np.ndarray:
    with wave.open(str(ROOT / "fixture.wav"), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError("Fixture must be 16-kHz mono s16le")
        pcm = audio.readframes(audio.getnframes())
    if sha256(pcm).hexdigest() != PCM_SHA256:
        raise ValueError("Fixture differs from Soniox source samples")
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def streaming_chunks(processor, audio):
    yield processor(audio[:processor.num_samples_first_audio_chunk], sampling_rate=16000, is_streaming=True, is_first_audio_chunk=True)
    mel_frame_idx = processor.num_mel_frames_per_step
    start_idx = processor.audio_chunk_start(mel_frame_idx)
    while (end_idx := start_idx + processor.num_samples_per_audio_chunk) <= audio.shape[0]:
        yield processor(audio[start_idx:end_idx], sampling_rate=16000, is_streaming=True, is_first_audio_chunk=False)
        mel_frame_idx += processor.num_mel_frames_per_step
        start_idx = processor.audio_chunk_start(mel_frame_idx)
    yield processor(audio[start_idx:], sampling_rate=16000, is_streaming=True, is_first_audio_chunk=False, is_last_audio_chunk=True)


def frame_intervals(frame_flags):
    flags = np.asarray(frame_flags, dtype=np.int8)
    changes = np.diff(np.pad(flags, (1, 1)))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    return [{"start_s": round(int(a) / 100, 2), "end_s": round(int(b) / 100, 2)} for a, b in zip(starts, ends)]


def run_arm(arm, audio, model, processor, metadata):
    if arm != "offline":
        processor.set_streaming_mode(arm)
    started = time.perf_counter()
    with torch.inference_mode():
        if arm == "offline":
            inputs = processor(audio, sampling_rate=16000).to("cpu", dtype=model.dtype)
            logits = model(**inputs).logits
            mask = inputs.attention_mask
            num_chunks = None
        else:
            speaker_cache = None
            output_chunks = []
            for inputs in streaming_chunks(processor, audio):
                outputs = model(**inputs.to("cpu", dtype=model.dtype), speaker_cache=speaker_cache)
                output_chunks.append(outputs.logits)
                speaker_cache = outputs.speaker_cache
            logits = torch.cat(output_chunks, dim=1)
            mask = None
            num_chunks = len(output_chunks)
        segments = processor.extract_speaker_dict(logits, mask)[0]
        probability = logits.sigmoid().cpu().numpy()[0]
        if mask is not None:
            probability = probability[:int(mask.sum())]
    compute_s = time.perf_counter() - started
    active = probability > 0.5
    speaker_spans = [{"start_s": row["Start"], "end_s": row["End"], "speaker": str(row["Speaker"])} for row in segments]
    if arm == "offline":
        config = {"spkcache_len": model.config.streaming_config.speaker_cache_length, "fifo_len": model.config.fifo_length, "chunk_len": model.config.chunk_length, "right_context": model.config.chunk_right_context, "update_period": model.config.speaker_cache_update_period}
        latency_s = (model.config.chunk_length + model.config.chunk_right_context) * 0.08
    else:
        chunk_len, right_context = processor.streaming_modes[arm]
        config = {"spkcache_len": model.config.streaming_config.speaker_cache_length, "fifo_len": model.config.streaming_config.fifo_length, "chunk_len": chunk_len, "right_context": right_context, "update_period": model.config.streaming_config.speaker_cache_update_period}
        latency_s = processor.streaming_latency_ms / 1000
    result = {**metadata, "arm": arm, "effective_config": config, "nominal_delay_s": latency_s, "measured_compute_s": compute_s, "timing": {"preprocess_inference_postprocess_compute_s": compute_s, "wall_clock_live_latency_measured": False, "streaming_model_forwards": num_chunks}, "sample_count": len(audio), "duration_s": len(audio) / 16000, "output_frame_stride_s": 0.01, "num_output_frames": len(probability), "speaker_channels": int(probability.shape[1]), "decision_threshold": 0.5, "native_segments": segments, "segments": speaker_spans, "unknown_intervals": frame_intervals(~active.any(axis=1)), "overlap_intervals": frame_intervals(active.sum(axis=1) > 1), "frame_probabilities": probability.tolist()}
    output = ROOT / f"{arm}.json"
    output.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"arm={arm} nominal_buffer_s={latency_s:.2f} compute_s={compute_s:.3f} forwards={num_chunks} frames={len(probability)} segments={len(segments)} active_speakers={int(active.any(axis=0).sum())} bytes={output.stat().st_size}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=("all", "offline", *STREAM_MODES), default="all")
    args = parser.parse_args()
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    audio = original_audio()
    print(f"fixture_pcm_sha256={PCM_SHA256} duration_s={len(audio) / 16000:.3f} samples={len(audio)}", flush=True)
    load_started = time.perf_counter()
    processor = AutoProcessor.from_pretrained(MODEL_ID, revision=REVISION)
    model = AutoModelForAudioFrameClassification.from_pretrained(MODEL_ID, revision=REVISION).eval().to("cpu")
    weights = try_to_load_from_cache(MODEL_ID, "model.safetensors", revision=REVISION)
    if not isinstance(weights, str):
        raise RuntimeError("Cannot locate downloaded model.safetensors")
    weight_hash = sha256()
    with Path(weights).open("rb") as source:
        while chunk := source.read(1024 * 1024):
            weight_hash.update(chunk)
    weight_hash = weight_hash.hexdigest()
    dist = importlib.metadata.distribution("transformers")
    direct_url = dist.read_text("direct_url.json")
    metadata = {"model": MODEL_ID, "model_revision": REVISION, "model_weights_sha256": weight_hash, "source_sha256": PCM_SHA256, "runtime": {"os": platform.platform(), "device": "cpu", "torch": torch.__version__, "transformers": dist.version, "transformers_direct_url": json.loads(direct_url) if direct_url else None, "python": platform.python_version(), "torch_num_threads": torch.get_num_threads()}, "model_load_and_hash_s": time.perf_counter() - load_started}
    print(f"loaded_model={MODEL_ID}@{REVISION} weights_sha256={weight_hash} load_and_hash_s={metadata['model_load_and_hash_s']:.3f} torch={torch.__version__} transformers={dist.version} threads={torch.get_num_threads()}", flush=True)
    arms = ("offline", *STREAM_MODES) if args.arm == "all" else (args.arm,)
    for arm in arms:
        run_arm(arm, audio, model, processor, metadata)


if __name__ == "__main__":
    main()
