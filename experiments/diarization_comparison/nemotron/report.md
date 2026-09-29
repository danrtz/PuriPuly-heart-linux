# Nemotron 3 diarization: original six-speaker fixture, four official latency presets

## Outcome

The current NVIDIA [`nvidia/Nemotron-3-Diarization`](https://huggingface.co/nvidia/Nemotron-3-Diarization) checkpoint was run locally on the **unchanged original 51.730-second, six-human LibriSpeech fixture** for each of the four completely specified configurations in NVIDIA's [model card](https://huggingface.co/nvidia/Nemotron-3-Diarization/blob/f667ed73aee57d40cc39428eb768b4fd87a0a29e/README.md). All four runs emitted six distinct session-local speaker labels. This is **not** evidence that all six people were attributed correctly; compare the saved timestamped spans against the common fixed Soniox token anchors to quantify merges, splits, misses and ambiguity. This model's **eight output channels are capacity, not eight predicted speakers**. The separate older `diar_streaming_sortformer_4spk-v2.1` checkpoint was not used.

| Preset | Official effective parameters (`spkcache`, `FIFO`, `chunk`, `right`, `update`; 80-ms encoder frames) | Nominal input-buffer delay, excluding compute | Measured full-fixture CPU preprocess + inference + segment extraction | Forward calls | Frames / 10 ms | Emitted native speaker labels / segments |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `offline` | 264, 40, 340, 40, 300 | 30.40 s | 1.516 s | internal offline chunks | 5173 | 6 / 16 |
| `low_latency` | 264, 264, 9, 4, 222 | 1.04 s | 9.970 s | 72 | 5172 | 6 / 17 |
| `very_low_latency` | 264, 264, 6, 2, 222 | 0.64 s | 15.757 s | 108 | 5172 | 6 / 16 |
| `ultra_low_latency` | 264, 264, 3, 1, 222 | 0.32 s | 31.749 s | 216 | 5172 | 6 / 17 |

**Latency distinction:** all audio was available locally, and the streaming processor replayed consecutive chunks as quickly as this CPU allowed. The table's nominal delay is `(chunk_len + right_context) × 80 ms`, the model's required audio buffer, **not observed live end-to-end latency**. Compute times are full-clip wall-clock compute including feature extraction and processor segment conversion, after one-time model load, without network transfer or realtime pacing. In particular 31.749 s compute over 51.730 s of audio does not establish a real-world per-turn response time, scheduling/jitter, or live streaming performance. No arbitrary 80-ms tuning was run: NVIDIA mentions that capability, but publishes no complete 80-ms recommended parameter row. The 30.4-s offline-style row is the model's **default chunked offline forward**, not a one-shot 51.73-s encoder pass.

## Source and methodology

`prepare_audio.py` reads **only** `experiments/soniox_diarization/fixture.json` and the 12 already-cached original public FLAC clips, decodes each with FFmpeg to 16-kHz mono PCM s16le, appends exactly 0.500 s of silence after each clip, verifies SHA-256 `2eb1ab143c2a7dbaa7448c31b44dd8c517b85042e769f2da5d2ddaec14028762` over 827,680 samples / 1,655,360 PCM bytes, and writes an ignored local WAV. It neither reads nor passes source speaker labels or a known speaker count to the model. All the inference arms read that same WAV, verify its source PCM digest, and use a single checkpoint pinned to revision `f667ed73aee57d40cc39428eb768b4fd87a0a29e`. The `model.safetensors` SHA-256 was measured as `c074d86335b3b794f8fa5edc25594558f128bdb3914d27806a3a5a2e44963cb6` (396,954,592 bytes); model `config.json` and `processor_config.json` measured 1,458 and 623 bytes respectively. The checkpoint has eight channels, requiring no oracle speaker count.

[`run.py`](run.py) follows the [official Transformers offline and streaming usage](https://huggingface.co/docs/transformers/main/en/model_doc/nemotron3_diarization): full-waveform `processor(audio)` plus `model(**inputs)` for the 30.4-s default model config; for each named streaming mode, official processor-determined first/subsequent/EOF audio chunk boundaries, successive model calls carrying `speaker_cache`, and concatenation of scored frame logits. The official processor's `extract_speaker_dict` converts sigmoid probability > 0.5 per speaker into intervals. No forced exclusive speaker assignment: overlaps can produce overlapping segments and unassigned intervals remain present. Each JSON preserves the processor's native `Start`/`End`/`Speaker` segments, **all eight sigmoid probabilities at every scored 10-ms frame**, derived explicit unknown/overlap intervals, and common-evaluator `segments: [{start_s,end_s,speaker}]` with original-audio timestamps and stringified session-local native IDs. Probabilities and segments use the first input sample as time zero, with **no temporal offset** and no segmentation mapping. At the native threshold these particular runs had zero overlap intervals and 17/18 unknown intervals (offline/low/very-low/ultra-low respectively: 17/18/17/18). Native output has 5173 frames offline versus 5172 streaming: the streaming processor's final chunk yielded one fewer 10-ms frame; no speech was synthetically extended, and the final emitted speaker span ends at 50.77–50.78 s, during the fixture's final digital-silence tail.

Files: [`offline.json`](offline.json), [`low_latency.json`](low_latency.json), [`very_low_latency.json`](very_low_latency.json), [`ultra_low_latency.json`](ultra_low_latency.json). Top-level `source_sha256`, `model`, `model_revision`, `model_weights_sha256`, `effective_config`, `nominal_delay_s`, `measured_compute_s`, `segments`, `native_segments`, `frame_probabilities`, `unknown_intervals`, `overlap_intervals`, `timing` and `runtime` are recorded per preset. Do not substitute the number of distinct labels for a diarization error metric. The canonical prior Soniox raw evidence is the unchanged `experiments/soniox_diarization/{continuous,forced,segmented,async_full_file}.json`; Soniox [probe report](../../soniox_diarization/report.md) explains why session-local speaker numerals must never be directly equated across models or arms.

## Exact local execution and observed output

Windows x64 host, WSL Ubuntu 6.18.33.2 WSL2, Linux Python 3.12.3, PyTorch 2.14.0+cpu, Transformers 5.18.0.dev0 from Git commit `da4bd0dca1b1a2a590b68daf30a15ac157a6998c`, eight CPU threads. AMD Radeon RX 7900 XTX was **not used**; no NVIDIA GPU/ROCm device. The checkpoint and dependencies were installed only under ignored `.cache/` and `.venv/` in this experiment, not the repository's shared environment. Source FLAC was already cached from the previous Soniox run; no fixture upload occurred. NVIDIA's public model was downloaded from Hugging Face without credentials. Installation downloaded CPU PyTorch wheel (187.2 MiB according to uv), numpy (15.9 MiB), the Transformers Git distribution plus audio dependencies including librosa/llvmlite (57.1 MiB llvmlite), and the 396,954,592-byte pinned safetensors checkpoint. The precise total network transfer is **not measured** (wheel metadata, dependency downloads and possible hub retries are not accounted for).

Environment creation was executed with `uv` 0.9.17 in WSL and its cache rooted in this experiment. The Git `HEAD` installation resolved to the exact Transformers commit recorded above; pin that commit instead of `HEAD` on future repeats.

```sh
D=/mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/diarization_comparison/nemotron
export UV_CACHE_DIR="$D/.cache/uv"
uv venv --python python3.12 "$D/.venv"
uv pip install --python "$D/.venv/bin/python" torch --index-url https://download.pytorch.org/whl/cpu
uv pip install --python "$D/.venv/bin/python" 'git+https://github.com/huggingface/transformers.git@da4bd0dca1b1a2a590b68daf30a15ac157a6998c' numpy soundfile huggingface_hub
uv pip install --python "$D/.venv/bin/python" librosa
```

Run from the repository root in Windows shell (`D` is the exact existing Linux/WSL path to this experiment, obtained by `wslpath -u`):

```sh
wsl.exe --exec sh -lc 'D=/mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/diarization_comparison/nemotron; /usr/bin/python3 "$D/prepare_audio.py"'
wsl.exe --exec sh -lc 'D=/mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/diarization_comparison/nemotron; export HF_HOME="$D/.cache/hf" HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false; "$D/.venv/bin/python" "$D/run.py" --arm all'
```

Preparation printed `fixture_pcm_sha256=2eb1ab143c2a7dbaa7448c31b44dd8c517b85042e769f2da5d2ddaec14028762 sample_rate=16000 samples=827680 duration_s=51.730`. Successful inference printed `load_and_hash_s=15.066` and the above four arm measurements; JSON byte sizes (offline, low, very-low, ultra-low) were 965207, 967342, 966894 and 965939 respectively. First attempt failed while loading the processor because Git-source Transformers also required `librosa`; this was installed inside the isolated environment, then the unchanged command successfully executed **one genuine inference per preset**. No permanent tests were added for this investigation.

## Interpretation limits

This one artificial sequence alternates clean read English audiobooks by six people with inserted silences. It does not benchmark noisy multilingual VRChat conversations, adjacent turns of the same person, translated text, speaker enrollment, actual live display delay, or overall vendor quality. Nemotron is diarization-only and produces no lexical timestamps or translation; the common evaluation separately aligns these saved native spans to the same Soniox lexical-token anchors and original six-speaker fixture truth. Any token outside its speaker interval, including unknown or overlapping results, must retain its ambiguity; do not silently manufacture speaker labels. This report intentionally does not claim DER or superiority against Soniox before common scoring.
