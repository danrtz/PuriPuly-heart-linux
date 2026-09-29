# Nemotron additional-control inferences

## Result

Completed all eight requested inferences: `repeated` and `distinct`, each run once with `offline`, `low_latency`, `very_low_latency`, and `ultra_low_latency`. Evidence is the reviewed runner's native JSON output, including native segments, normalized segments, raw frame probabilities, unknown/overlap intervals, effective configuration, source hash, runtime, and timings. Output channels were not relabeled or forced exclusive. Two channels were active in every run; eight is model capacity, not a predicted speaker count.

The first inference command completed all eight arms, then returned exit status 1 because the wrapper's post-run check compared offline `30.400000000000002` exactly with `30.4`. I changed only that check to a `1e-9` tolerance and validated the already-saved eight outputs; **no inference was repeated**. The exact run and saved-output validation commands and their observed output are below.

## Provenance and method

Inputs are the unchanged, director-prepared 16-kHz mono PCM16 WAVs [`repeated.wav`](../audio/repeated.wav) and [`distinct.wav`](../audio/distinct.wav), described in [`fixtures.json`](../fixtures.json). The wrapper checks WAV format, duration, byte count, and the PCM SHA-256 before passing the waveform to the model:

| Fixture | Duration | PCM bytes | Source PCM SHA-256 |
| --- | ---: | ---: | --- |
| `repeated` | 22.280 s | 712,960 | `a498e5872ad0edb2ebe3fe38d811b09a824e43c6080c1ec5b74870008520c650` |
| `distinct` | 14.080 s | 450,560 | `d569edbca911b0db8e5b9239efe3fa5057b16e0763fc1d442a37dd6b303f0fa6` |

The wrapper reads only those waveforms and fixed verification metadata; it does not read the manifest's turns, labels, speaker identities, or Qwen outputs, and passes no reference count or labels to inference. It imports [`run.py`](newshortwrapper/run.py), reuses its `run_arm()`/`streaming_chunks()` behavior, and redirects the imported module's `ROOT` in memory to each owned case output directory. One eval-mode CPU model instance is shared across cases; a fresh `AutoProcessor` is loaded for each case, so each case's offline arm starts with its default non-streaming mode. Each of the three named streaming arms replays the processor's official chunks as fast as the CPU permits.

The checkpoint is `nvidia/Nemotron-3-Diarization` at revision `f667ed73aee57d40cc39428eb768b4fd87a0a29e`; the locally cached `model.safetensors` SHA-256 was verified as `c074d86335b3b794f8fa5edc25594558f128bdb3914d27806a3a5a2e44963cb6`. Runtime: WSL2 Linux `6.18.33.2`, Python `3.12.3`, PyTorch `2.14.0+cpu`, Transformers `5.18.0.dev0` from commit `da4bd0dca1b1a2a590b68daf30a15ac157a6998c`, CPU, eight Torch threads. The model, processor, and Transformers distribution were loaded from the existing local cache (`local_files_only=True`, `HF_HUB_OFFLINE=1`); no model download, environment change, GPU, ASR, oracle, or reclustering was used. Model load plus weight hashing took 2.778 s.

## Presets and measured compute

Effective parameters are `(spkcache_len, fifo_len, chunk_len, right_context, update_period)`; nominal delay is input buffering only, not observed live end-to-end latency.

| Preset | Effective parameters | Nominal delay |
| --- | --- | ---: |
| `offline` | `(264, 40, 340, 40, 300)` | 30.40 s |
| `low_latency` | `(264, 264, 9, 4, 222)` | 1.04 s |
| `very_low_latency` | `(264, 264, 6, 2, 222)` | 0.64 s |
| `ultra_low_latency` | `(264, 264, 3, 1, 222)` | 0.32 s |

Measured CPU compute covers the runner's per-arm preprocessing, model inference, and segment extraction after model load; it excludes live/realtime pacing. Streaming frame counts are one lower than offline on both fixtures.

| Fixture | Preset | Compute (s) | Streaming forwards | Frames | Native segments |
| --- | --- | ---: | ---: | ---: | ---: |
| `repeated` | `offline` | 1.198 | — | 2,228 | 6 |
| `repeated` | `low_latency` | 2.367 | 31 | 2,227 | 6 |
| `repeated` | `very_low_latency` | 3.616 | 47 | 2,227 | 7 |
| `repeated` | `ultra_low_latency` | 6.968 | 93 | 2,227 | 7 |
| `distinct` | `offline` | 0.099 | — | 1,408 | 4 |
| `distinct` | `low_latency` | 1.270 | 20 | 1,407 | 4 |
| `distinct` | `very_low_latency` | 1.850 | 29 | 1,407 | 4 |
| `distinct` | `ultra_low_latency` | 3.324 | 59 | 1,407 | 4 |

## Exact execution and observed output

Inference command:

```sh
wsl.exe --exec sh -lc 'D=/mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/diarization_comparison/additional_controls/nemotron; CACHE=/mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/diarization_comparison/nemotron; export HF_HOME="$CACHE/.cache/hf" HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false; "$CACHE/.venv/bin/python" "$D/newshortwrapper/run.py"'
```

Observed terminal output from that run (the wrapper's arm lines are stdout; Transformers also emitted the loading progress):

```text
Loading weights:   0%|          | 0/417 [00:00<?, ?it/s]
Loading weights:  22%|██▏       | 90/417 [00:00<00:00, 899.25it/s]
Loading weights:  43%|████▎     | 180/417 [00:00<00:00, 841.23it/s]
Loading weights:  64%|██████▎   | 265/417 [00:00<00:00, 811.51it/s]
Loading weights: 100%|██████████| 417/417 [00:00<00:00, 1132.27it/s]
loaded_model=nvidia/Nemotron-3-Diarization@f667ed73aee57d40cc39428eb768b4fd87a0a29e weights_sha256=c074d86335b3b794f8fa5edc25594558f128bdb3914d27806a3a5a2e44963cb6 load_and_hash_s=2.778 torch=2.14.0+cpu transformers=5.18.0.dev0 threads=8
arm=offline nominal_buffer_s=30.40 compute_s=1.198 forwards=None frames=2228 segments=6 active_speakers=2 bytes=417095
arm=low_latency nominal_buffer_s=1.04 compute_s=2.367 forwards=31 frames=2227 segments=6 active_speakers=2 bytes=417028
arm=very_low_latency nominal_buffer_s=0.64 compute_s=3.616 forwards=47 frames=2227 segments=7 active_speakers=2 bytes=417292
arm=ultra_low_latency nominal_buffer_s=0.32 compute_s=6.968 forwards=93 frames=2227 segments=7 active_speakers=2 bytes=417069
arm=offline nominal_buffer_s=30.40 compute_s=0.099 forwards=None frames=1408 segments=4 active_speakers=2 bytes=264474
arm=low_latency nominal_buffer_s=1.04 compute_s=1.270 forwards=20 frames=1407 segments=4 active_speakers=2 bytes=264079
arm=very_low_latency nominal_buffer_s=0.64 compute_s=1.850 forwards=29 frames=1407 segments=4 active_speakers=2 bytes=264082
arm=ultra_low_latency nominal_buffer_s=0.32 compute_s=3.324 forwards=59 frames=1407 segments=4 active_speakers=2 bytes=263877
```

After correcting the float comparison, saved-output validation was run without invoking inference:

```sh
wsl.exe --exec sh -lc 'D=/mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/diarization_comparison/additional_controls/nemotron; CACHE=/mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/diarization_comparison/nemotron; "$CACHE/.venv/bin/python" -B -c "import runpy; ns=runpy.run_path(\"$D/newshortwrapper/run.py\", run_name=\"saved_result_validation\"); ns[\"validate_outputs\"]()"'
```

It passed all eight source/model/configuration/timing/channel/probability/segment-bound/frame-count checks and printed the observed first and last native segments:

```text
validated case=repeated arm=offline frames=2228 segments=6 first={'Start': 0.3, 'End': 2.85, 'Speaker': 0} last={'Start': 18.81, 'End': 21.35, 'Speaker': 0}
validated case=repeated arm=low_latency frames=2227 segments=6 first={'Start': 0.31, 'End': 2.88, 'Speaker': 0} last={'Start': 18.81, 'End': 21.35, 'Speaker': 0}
validated case=repeated arm=very_low_latency frames=2227 segments=7 first={'Start': 0.32, 'End': 2.88, 'Speaker': 0} last={'Start': 18.81, 'End': 21.35, 'Speaker': 0}
validated case=repeated arm=ultra_low_latency frames=2227 segments=7 first={'Start': 0.32, 'End': 2.92, 'Speaker': 0} last={'Start': 18.81, 'End': 21.36, 'Speaker': 0}
validated case=distinct arm=offline frames=1408 segments=4 first={'Start': 0.31, 'End': 2.84, 'Speaker': 0} last={'Start': 10.76, 'End': 13.09, 'Speaker': 1}
validated case=distinct arm=low_latency frames=1407 segments=4 first={'Start': 0.31, 'End': 2.88, 'Speaker': 0} last={'Start': 10.76, 'End': 13.09, 'Speaker': 1}
validated case=distinct arm=very_low_latency frames=1407 segments=4 first={'Start': 0.32, 'End': 2.88, 'Speaker': 0} last={'Start': 10.76, 'End': 13.09, 'Speaker': 1}
validated case=distinct arm=ultra_low_latency frames=1407 segments=4 first={'Start': 0.32, 'End': 2.92, 'Speaker': 0} last={'Start': 10.76, 'End': 13.08, 'Speaker': 1}
```

## Result files and limits

| Fixture | Result files |
| --- | --- |
| `repeated` | [`offline.json`](evidence/repeated/offline.json), [`low_latency.json`](evidence/repeated/low_latency.json), [`very_low_latency.json`](evidence/repeated/very_low_latency.json), [`ultra_low_latency.json`](evidence/repeated/ultra_low_latency.json) |
| `distinct` | [`offline.json`](evidence/distinct/offline.json), [`low_latency.json`](evidence/distinct/low_latency.json), [`very_low_latency.json`](evidence/distinct/very_low_latency.json), [`ultra_low_latency.json`](evidence/distinct/ultra_low_latency.json) |

The delays are model buffer requirements, not measured live end-to-end latency: all local chunks were replayed as fast as the CPU allowed. The WAVs are short constructed sequences with inserted silence, not noisy live conversation. These raw diarization spans do not establish attribution correctness or vendor quality; speaker IDs are run-local, output may be overlapping or unknown, and no common scoring or accuracy claim is made here. The common evaluator can compare these native spans with the same fixed references without altering this evidence.
