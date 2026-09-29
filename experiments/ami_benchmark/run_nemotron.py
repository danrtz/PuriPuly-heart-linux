import argparse
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
import wave

import numpy as np
import torch
from huggingface_hub import try_to_load_from_cache
from transformers import AutoModelForAudioFrameClassification, AutoProcessor

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "diarization_comparison" / "nemotron"))
from run import MODEL_ID, REVISION, streaming_chunks


def main():
    parser = argparse.ArgumentParser(description="Run the pinned CPU Nemotron 3 official ultra-low-latency preset on all seven AMI scenarios")
    parser.add_argument("--predictions", type=Path, default=ROOT / "predictions" / "nemotron_ultra_low_latency")
    args = parser.parse_args()
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    args.predictions.mkdir(parents=True, exist_ok=True)
    load_start = time.perf_counter()
    processor = AutoProcessor.from_pretrained(MODEL_ID, revision=REVISION)
    processor.set_streaming_mode("ultra_low_latency")
    model = AutoModelForAudioFrameClassification.from_pretrained(MODEL_ID, revision=REVISION).eval().to("cpu")
    weight_file = try_to_load_from_cache(MODEL_ID, "model.safetensors", revision=REVISION)
    if not isinstance(weight_file, str):
        raise RuntimeError("Pinned checkpoint not cached")
    weight_hash = sha256(Path(weight_file).read_bytes()).hexdigest()
    chunks, right = processor.streaming_modes["ultra_low_latency"]
    provenance = {"model": MODEL_ID, "revision": REVISION, "weights_sha256": weight_hash, "mode": "ultra_low_latency", "effective_config": {"speaker_cache_length": model.config.streaming_config.speaker_cache_length, "fifo_length": model.config.streaming_config.fifo_length, "chunk_length": chunks, "right_context": right, "speaker_cache_update_period": model.config.streaming_config.speaker_cache_update_period}, "nominal_input_buffer_s": processor.streaming_latency_ms / 1000, "live_e2e_latency_measured": False, "model_load_s": round(time.perf_counter() - load_start, 3), "runtime": {"os": platform.platform(), "device": "cpu", "python": platform.python_version(), "torch": torch.__version__, "transformers": importlib.metadata.version("transformers"), "torch_num_threads": torch.get_num_threads()}, "cases": []}
    for case in manifest["cases"]:
        path = ROOT / case["audio"]
        with wave.open(str(path), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) != (1, 2, 16000, case["duration_s"] * 16000):
                raise ValueError(f"Invalid input WAV: {path}")
            pcm = wav.readframes(wav.getnframes())
        if sha256(pcm).hexdigest() != case["clip_pcm_sha256"]:
            raise ValueError(f"Input PCM digest mismatch: {path}")
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        begin = time.perf_counter()
        speaker_cache = None
        pieces = []
        with torch.inference_mode():
            for inputs in streaming_chunks(processor, audio):
                result = model(**inputs.to("cpu", dtype=model.dtype), speaker_cache=speaker_cache)
                pieces.append(result.logits)
                speaker_cache = result.speaker_cache
            native = processor.extract_speaker_dict(torch.cat(pieces, dim=1), None)[0]
        elapsed = time.perf_counter() - begin
        rows = []
        for segment in native:
            first, end = float(segment["Start"]), float(segment["End"])
            if first < 0 or end > case["duration_s"] + 0.02:
                raise ValueError(f"Model span beyond clip: {case['id']} {segment}")
            first, end = max(0, first), min(case["duration_s"], end)
            if first < end:
                rows.append(f"SPEAKER {case['id']} 1 {first:.3f} {end - first:.3f} <NA> <NA> {segment['Speaker']} <NA> <NA>")
        (args.predictions / f"{case['id']}.rttm").write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
        record = {"id": case["id"], "input_pcm_sha256": case["clip_pcm_sha256"], "compute_s": round(elapsed, 3), "model_forwards": len(pieces), "native_segments": len(native), "written_segments": len(rows), "prediction_rttm_sha256": sha256((args.predictions / f"{case['id']}.rttm").read_bytes()).hexdigest()}
        provenance["cases"].append(record)
        print(json.dumps(record), flush=True)
    (args.predictions / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
