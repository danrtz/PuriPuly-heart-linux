from hashlib import sha256
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import time
import wave

import numpy as np

SCRIPT = Path(__file__).resolve()
OWNED_ROOT = SCRIPT.parents[1]
FIXTURE_ROOT = SCRIPT.parents[2] / "audio"
PRIOR_RUN = SCRIPT.parents[3] / "nemotron" / "run.py"
EVIDENCE = OWNED_ROOT / "evidence"
MODEL_ID = "nvidia/Nemotron-3-Diarization"
REVISION = "f667ed73aee57d40cc39428eb768b4fd87a0a29e"
WEIGHTS_SHA256 = "c074d86335b3b794f8fa5edc25594558f128bdb3914d27806a3a5a2e44963cb6"
CASES = {
    "repeated": ("a498e5872ad0edb2ebe3fe38d811b09a824e43c6080c1ec5b74870008520c650", 712960, 22.28),
    "distinct": ("d569edbca911b0db8e5b9239efe3fa5057b16e0763fc1d442a37dd6b303f0fa6", 450560, 14.08),
}
ARMS = ("offline", "low_latency", "very_low_latency", "ultra_low_latency")
NOMINAL_DELAYS = {"offline": 30.4, "low_latency": 1.04, "very_low_latency": 0.64, "ultra_low_latency": 0.32}
EXPECTED_CONFIGS = {
    "offline": {"spkcache_len": 264, "fifo_len": 40, "chunk_len": 340, "right_context": 40, "update_period": 300},
    "low_latency": {"spkcache_len": 264, "fifo_len": 264, "chunk_len": 9, "right_context": 4, "update_period": 222},
    "very_low_latency": {"spkcache_len": 264, "fifo_len": 264, "chunk_len": 6, "right_context": 2, "update_period": 222},
    "ultra_low_latency": {"spkcache_len": 264, "fifo_len": 264, "chunk_len": 3, "right_context": 1, "update_period": 222},
}

def load_runner():
    spec = importlib.util.spec_from_file_location("prior_nemotron_run", PRIOR_RUN)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import reviewed helper: {PRIOR_RUN}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_audio(case, expected_hash, expected_bytes, expected_duration):
    path = FIXTURE_ROOT / f"{case}.wav"
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError(f"Unexpected WAV format: {path}")
        pcm = source.readframes(source.getnframes())
    digest = sha256(pcm).hexdigest()
    if digest != expected_hash or len(pcm) != expected_bytes or len(pcm) / 32000 != expected_duration:
        raise ValueError(f"Prepared waveform verification failed: {case}")
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    return audio, digest


def validate_outputs():
    count = 0
    for case, (source_hash, expected_bytes, duration) in CASES.items():
        for arm in ARMS:
            path = EVIDENCE / case / f"{arm}.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            assert result["arm"] == arm and result["source_sha256"] == source_hash
            assert result["model"] == MODEL_ID and result["model_revision"] == REVISION
            assert result["model_weights_sha256"] == WEIGHTS_SHA256
            assert result["effective_config"] == EXPECTED_CONFIGS[arm]
            assert result["duration_s"] == duration and result["sample_count"] * 2 == expected_bytes
            assert abs(result["nominal_delay_s"] - NOMINAL_DELAYS[arm]) < 1e-9
            assert result["runtime"]["device"] == "cpu" and result["runtime"]["torch_num_threads"] == 8
            assert result["model_load_and_hash_s"] > 0
            timing = result["timing"]
            assert timing["preprocess_inference_postprocess_compute_s"] == result["measured_compute_s"]
            assert timing["wall_clock_live_latency_measured"] is False
            if arm == "offline":
                assert timing["streaming_model_forwards"] is None
            else:
                assert timing["streaming_model_forwards"] > 0
            assert result["output_frame_stride_s"] == 0.01
            probabilities = result["frame_probabilities"]
            assert len(probabilities) == result["num_output_frames"]
            assert abs(len(probabilities) - duration * 100) <= 1
            assert result["speaker_channels"] == 8
            assert all(len(frame) == 8 and all(0.0 <= value <= 1.0 for value in frame) for frame in probabilities)
            segments = result["native_segments"]
            for segment in segments:
                assert 0.0 <= segment["Start"] < segment["End"] <= duration + 0.01
            assert len(result["segments"]) == len(segments)
            assert result["segments"] == [
                {"start_s": segment["Start"], "end_s": segment["End"], "speaker": str(segment["Speaker"])}
                for segment in segments
            ]
            if segments:
                first = {key: segments[0][key] for key in ("Start", "End", "Speaker")}
                last = {key: segments[-1][key] for key in ("Start", "End", "Speaker")}
            else:
                first = last = None
            print(f"validated case={case} arm={arm} frames={len(probabilities)} segments={len(segments)} first={first} last={last}", flush=True)
            count += 1
    if count != len(CASES) * len(ARMS):
        raise AssertionError(f"Expected eight result files, found {count}")


def main():
    runner = load_runner()
    torch = runner.torch
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    load_started = time.perf_counter()
    processor_class = runner.AutoProcessor
    model = runner.AutoModelForAudioFrameClassification.from_pretrained(
        MODEL_ID, revision=REVISION, local_files_only=True
    ).eval().to("cpu")
    weights = runner.try_to_load_from_cache(MODEL_ID, "model.safetensors", revision=REVISION)
    if not isinstance(weights, str):
        raise RuntimeError("Cannot locate locally cached model.safetensors")
    digest = sha256()
    with Path(weights).open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != WEIGHTS_SHA256:
        raise ValueError("Cached Nemotron weights differ from the pinned reviewed checkpoint")
    dist = importlib.metadata.distribution("transformers")
    direct_url = dist.read_text("direct_url.json")
    runtime = {
        "os": platform.platform(),
        "device": "cpu",
        "torch": torch.__version__,
        "transformers": dist.version,
        "transformers_direct_url": json.loads(direct_url) if direct_url else None,
        "python": platform.python_version(),
        "torch_num_threads": torch.get_num_threads(),
    }
    load_s = time.perf_counter() - load_started
    print(f"loaded_model={MODEL_ID}@{REVISION} weights_sha256={WEIGHTS_SHA256} load_and_hash_s={load_s:.3f} torch={torch.__version__} transformers={dist.version} threads={torch.get_num_threads()}", flush=True)

    for case, (source_hash, expected_bytes, duration) in CASES.items():
        audio, actual_hash = load_audio(case, source_hash, expected_bytes, duration)
        if actual_hash != source_hash:
            raise AssertionError(f"Source hash changed while loading {case}")
        output_dir = EVIDENCE / case
        output_dir.mkdir(parents=True, exist_ok=True)
        runner.ROOT = output_dir
        metadata = {
            "model": MODEL_ID,
            "model_revision": REVISION,
            "model_weights_sha256": WEIGHTS_SHA256,
            "source_sha256": source_hash,
            "runtime": runtime,
            "model_load_and_hash_s": load_s,
        }
        processor = processor_class.from_pretrained(
            MODEL_ID, revision=REVISION, local_files_only=True
        )
        for arm in ARMS:
            runner.run_arm(arm, audio, model, processor, metadata)

    validate_outputs()


if __name__ == "__main__":
    main()
