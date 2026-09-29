# Soniox AMItest-derived seven-case execution

This task-local record covers the seven published `experiments/ami_benchmark/manifest.json` cases (six primary Mix-Headset clips plus the dependent Array1-01 microphone pair). All cases were consumed as real WAV audio, with WAV and 16-kHz mono PCM SHA-256 checked against the frozen manifest *before* each provider request. No annotation, reference RTTM, speaker count, or true speaker labels entered inference or prediction conversion. The `only_words` forced-aligned reference is used only by the unchanged offline scorer; provider-native word support and annotation support are not identical.

## Execution and projection

Runner: `experiments/ami_benchmark/providers/soniox/run.py --case CASE --arm ARM` (Windows main application venv Python). Each case/arm is a fresh request and fresh speaker-ID namespace; `stt-rt-v5` receives `en` hint, diarization on, endpoint detection off, raw 16-kHz PCM, and **one uninterrupted WS per case/RT arm**. Continuous sends entire clip then finalizes once; forced finalizes after every six seconds on the *same WS*; segmented replays the existing app-equivalent Silero VAD / ListenDelivery / SmartTurn segmenter, sending its owned source pieces and optional 200-ms padding before finalization on the *same WS*. Audio chunks are sent at source-real-time pacing. The segmentation probe uses source metadata without access to AMI labels and does not represent desktop capture. The `stt-async-v5` arm uploads each original whole WAV, polls for completed transcript, and deletes its transcription and uploaded file in `finally`; per-case cleanup and request counts are in the native result JSON. No service pricing was supplied; billable cost is unknown.

Native token milliseconds are intersected with each provider-to-source audio piece, preserving their own boundaries and different-ID overlap; removed silence and inserted padding are never assigned speaker time. A token split by a piece boundary is mapped once per actual audio intersection. Same-ID *overlapping* support is unioned, without filling gaps between tokens. Native zero-duration tokens cannot generate positive support and their indices are recorded; null-ID token intervals are omitted rather than named `<unknown>` and their provider-time intervals are recorded. No turn stretching, reference speech filling, or speaker re-ID across cases. `results/<case>/<arm>.json` contains native tokens, full source-piece timeline, config, duration, native artifact digest, conversion diagnostics, input digests, completion signals, durations and cleanup evidence. A failed conversion retains its initial native JSON rather than silently rerunning inference.

Provider timestamps that straddle sent-audio support are intersected with that support, and wholly out-of-support positive-duration tokens are omitted, with per-case counts, total excluded token-time, maximum overrun, and straddle counts in `conversion`. This applies no time shift: any in-window word timing error still affects DER. Official Soniox [manual-finalization documentation](https://soniox.com/docs/stt/rt/manual-finalization) specifies repeated `finalize` on one WebSocket and `<fin>` markers, but does **not** establish synthetic PCM/time advanced by a finalize; [the WebSocket API reference](https://soniox.com/docs/api-reference/stt/websocket-api) describes token milliseconds and processed-audio counters but no finalize-induced timeline correction. Accordingly native clocks remain literal, with any late timestamps reported rather than shifted to fit. Whether repeated finalization causes progressive drift cannot be established from these native word outputs alone; end overruns and their relationship to finalize counts are described below.

Receipts: `python experiments/ami_benchmark/providers/soniox/receipts.py` independently verifies input/digest, lifecycle, native token checksum and reconstructed full RTTM for all 28 pairs; writes seven-case `predictions/<arm>/provenance.json` with per-case native result paths and SHA-256. Score command for each arm, in WSL Ubuntu isolated pyannote 4 environment: `experiments/ami_benchmark/.venv/bin/python experiments/ami_benchmark/score.py --predictions experiments/ami_benchmark/providers/soniox/predictions/<arm> --output experiments/ami_benchmark/providers/soniox/scores/<arm>.json`. The standard scorer uses full-duration UEM, collar zero, overlap included, within-window optimal speaker permutation, and pools six nonduplicate primary cases separately from the far-field pair.

## Run outcomes

All **28/28 actual provider runs** completed: 7/7 native results and RTTMs for each of the four arms. Each realtime run has exactly one WS, a received `<fin>` for every requested finalization, and a finished response; 21/21 WS finished, 589/589 finalizations acknowledged. The long-context case remained one 600-s stream per realtime arm (continuous 1, forced 100, segmented 153 finalizations), never reset or stitched. All seven asynchronous transcriptions completed, and all seven owned transcription/file pairs were deleted in `finally` (no unresolved resource recorded). Across the 28 runs: 21 realtime WS sessions; 60 async HTTP requests, including cleanup; 5,520 s cumulative source-clip duration across four arms, with segmented transmitting 1,433.552 s rather than 1,380 s because of app-equivalent source-piece replay/padding. Sent realtime audio totals: continuous 1,380 s, forced 1,380 s, segmented 1,433.552 s. Sums of **per-run wall time**, not an elapsed-time or end-to-end-latency comparison: continuous 1,722.543 s, forced 1,772.489 s, segmented 4,127.617 s (includes VAD/SmartTurn offline replay at audio pace), async 136.012 s. Actual provider charge/currency price is unknown; realtime full-stream-duration billing is described in Soniox's manual-finalization documentation and wall-time is not an invoice.

Unchanged `score.py` was run once per completed arm using WSL Ubuntu's isolated `pyannote.metrics==4.0.0` environment; primary pooled reference speaker-time is 1,170.052 s, and the dependent far-field pair has 128.900 s.

| Arm | Six primary pooled DER | Six miss / false alarm / confusion (speaker-s) | Far-field pair DER | Pair miss / false alarm / confusion (speaker-s) | Six speaker-count accuracy |
|---|---:|---:|---:|---:|---:|
| continuous | 72.34% | 776.229 / 31.157 / 39.046 | 76.04% | 86.862 / 4.522 / 6.634 | 16.7% |
| forced | 89.21% | 857.982 / 81.590 / 104.252 | 88.99% | 95.412 / 8.812 / 10.480 | 16.7% |
| segmented | 86.66% | 846.577 / 74.917 / 92.464 | 89.64% | 95.759 / 8.395 / 11.396 | 16.7% |
| async_full_file | 72.65% | 787.520 / 29.848 / 32.709 | 81.84% | 87.948 / 4.768 / 12.771 | 33.3% |

### Saved-output support interpretation

Computed **only from the saved 28 native token lists and their case-local RTTMs**, with no additional inference or scoring change. Positive/zero counts refer to native timestamp duration before projection; all timed native tokens have finite bounds, and none are untimed. The final two columns are the **time union across known-speaker prediction intervals** after source mapping (distinct speakers overlapping in time counted once), not reference speaker-time or token-duration sums.

| Arm | Positive / zero / untimed native tokens | Positive span min / median / max (ms) | Exactly 60 ms | Known-speaker union, six primary / 1260 s | Known-speaker union, far-field / 120 s |
|---|---:|---:|---:|---:|---:|
| continuous | 7,859 / 29 / 0 | 60 / 60 / 60 | 7,859/7,859 (100%) | 424.980 s (33.73%) | 46.560 s (38.80%) |
| forced | 7,426 / 439 / 0 | 60 / 60 / 60 | 7,426/7,426 (100%) | 393.660 s (31.24%) | 42.300 s (35.25%) |
| segmented | 7,820 / 396 / 0 | 60 / 60 / 60 | 7,820/7,820 (100%) | 397.128 s (31.52%) | 41.500 s (34.58%) |
| async_full_file | 7,635 / 234 / 0 | 60 / 60 / 60 | 7,635/7,635 (100%) | 412.380 s (32.73%) | 45.720 s (38.10%) |

For continuous, **776.229/1,170.052 reference speaker-s is missed detection (66.34 DER percentage points)**, versus 31.157 false-alarm speaker-s (2.66 points) and 39.046 confusion speaker-s (3.34 points): together 72.34%. The 72.34% is therefore **not** “72% wrong voice IDs.” Native positive word spans are uniformly 60 ms here, while the predicted known-speaker union covers 424.980/1,260 s of primary clip time; these observed supports and reference speaker-time have different denominators (including annotated overlap). They document coverage but do **not** establish an ASR, clock, or alignment cause for the missed-detection component.

The table below records every case/arm's native output and projection diagnostics. `outside` means count of positive-duration native tokens with time beyond sent-audio support / excluded *token*-milliseconds / maximum end-time overrun milliseconds / number of boundary-straddling tokens; it is **not** scored reference speaker-time. `fin` is received/requested; `-` denotes async API completed, transcript fetched, both owned resources deleted. Source clip durations are those in the manifest, not necessarily segmented transmitted durations.

| Case | Arm | Native tokens | Fin | Sent s | Wall s | Outside count / token-ms / max-ms / straddles | DER |
|---|---|---:|---:|---:|---:|---:|---:|
| low_overlap | continuous | 662 | 1/1 | 120.000 | 151.685 | 0 / 0 / 0 / 0 | 65.80% |
| low_overlap | forced | 673 | 20/20 | 120.000 | 152.184 | 9 / 540 / 1920 / 0 | 74.31% |
| low_overlap | segmented | 725 | 32/32 | 132.700 | 370.469 | 8 / 480 / 1580 / 0 | 70.86% |
| low_overlap | async_full_file | 669 | - | 120.000 | 13.538 | 0 / 0 / 0 / 0 | 64.91% |
| rapid_turn_taking | continuous | 707 | 1/1 | 120.000 | 148.667 | 0 / 0 / 0 / 0 | 82.03% |
| rapid_turn_taking | forced | 718 | 20/20 | 120.000 | 153.788 | 14 / 840 / 1920 / 0 | 91.17% |
| rapid_turn_taking | segmented | 749 | 29/29 | 129.956 | 362.841 | 10 / 544 / 1204 / 1 | 88.35% |
| rapid_turn_taking | async_full_file | 686 | - | 120.000 | 17.508 | 0 / 0 / 0 / 0 | 87.08% |
| overlap_heavy | continuous | 791 | 1/1 | 120.000 | 147.976 | 0 / 0 / 0 / 0 | 81.54% |
| overlap_heavy | forced | 766 | 20/20 | 120.000 | 150.794 | 14 / 840 / 1920 / 0 | 91.54% |
| overlap_heavy | segmented | 790 | 32/32 | 125.392 | 363.011 | 10 / 600 / 1328 / 0 | 88.23% |
| overlap_heavy | async_full_file | 775 | - | 120.000 | 16.865 | 0 / 0 / 0 / 0 | 80.06% |
| long_return_gap | continuous | 732 | 1/1 | 180.000 | 226.218 | 0 / 0 / 0 / 0 | 69.14% |
| long_return_gap | forced | 761 | 30/30 | 180.000 | 233.269 | 30 / 1800 / 3120 / 0 | 84.25% |
| long_return_gap | segmented | 770 | 43/43 | 166.224 | 509.424 | 17 / 1020 / 2496 / 0 | 83.39% |
| long_return_gap | async_full_file | 751 | - | 180.000 | 20.706 | 0 / 0 / 0 / 0 | 68.56% |
| brief_interjections | continuous | 634 | 1/1 | 120.000 | 147.753 | 0 / 0 / 0 / 0 | 81.46% |
| brief_interjections | forced | 631 | 20/20 | 120.000 | 154.129 | 0 / 0 / 0 / 0 | 92.33% |
| brief_interjections | segmented | 657 | 32/32 | 129.728 | 369.151 | 0 / 0 / 0 / 0 | 93.30% |
| brief_interjections | async_full_file | 609 | - | 120.000 | 18.998 | 0 / 0 / 0 / 0 | 77.24% |
| long_context | continuous | 3581 | 1/1 | 600.000 | 748.442 | 0 / 0 / 0 / 0 | 67.61% |
| long_context | forced | 3560 | 100/100 | 600.000 | 772.163 | 81 / 4860 / 11520 / 0 | 91.40% |
| long_context | segmented | 3741 | 153/153 | 627.088 | 1795.058 | 64 / 3840 / 9152 / 0 | 88.13% |
| long_context | async_full_file | 3564 | - | 600.000 | 29.216 | 0 / 0 / 0 / 0 | 68.48% |
| far_field_pair | continuous | 781 | 1/1 | 120.000 | 151.802 | 0 / 0 / 0 / 0 | 76.04% |
| far_field_pair | forced | 756 | 20/20 | 120.000 | 156.162 | 12 / 720 / 1920 / 0 | 88.99% |
| far_field_pair | segmented | 784 | 31/31 | 122.464 | 357.663 | 11 / 660 / 1616 / 0 | 89.64% |
| far_field_pair | async_full_file | 815 | - | 120.000 | 19.181 | 0 / 0 / 0 / 0 | 81.84% |

No continuous or async positive-duration token extended outside transmitted support. Forced six-second runs show a **systematic progressive offset** relative to identical-text token matches in the independent continuous native transcripts (diagnostic only, not used for mapping): in three 120-s clips, median forced-minus-continuous token-start offset across [0–30), [30–60), [60–90), [90–120) s is approximately +0.24, +0.84, +1.44, +1.98–2.04 s. The five 20-finalization forced clips with speech near the endpoint each reach +1,920 ms maximum native overrun; 100-finalization long_context reaches +11,520 ms. This *looks* progressive with repeated finalization; Soniox's cited documentation does **not** establish a protocol-level audio-clock advance or amount of inserted synthetic PCM, and matching text across differently finalized model outputs is not a definitive clock calibration. No shift or reference-based repair was applied. Brief interjections has zero measured overrun despite 20 finalizations because there is no late positive-duration native token outside the sent support. App-segmented cases have their own omitted-silence, source replay and padding effects, and cannot be interpreted as the same clock as unsegmented audio.

Seven initial native results that passed provider completion but failed the first offline projection were preserved under `results/<case>/<arm>.initial.json` (three async zero-duration cases; low_overlap continuous/forced/segmented; rapid_turn_taking forced). Ten previously converted results were preserved under `.pre_boundary.json` while resolving timestamp-support diagnostics and Windows newline byte-digest mismatches. They are **auxiliary attempts, not additional inference runs**, not scorer inputs, and no inference was automatically repeated. `run.py --case CASE --arm ARM --convert-existing` repaired only owned completed native outputs and recorded their initial-artifact SHA-256. Final canonical native results and four provenance receipts, not those auxiliary files, feed the independent DER scorer. No credentials or source audio are stored in results.

## Verification commands

From repository root (the Windows application venv Python executable was used for the first two commands):

```text
<main-venv-python> experiments/ami_benchmark/providers/soniox/run.py --case CASE --arm ARM
<main-venv-python> experiments/ami_benchmark/providers/soniox/receipts.py
wsl.exe --cd <this-worktree-WSL-path> experiments/ami_benchmark/.venv/bin/python experiments/ami_benchmark/score.py --predictions experiments/ami_benchmark/providers/soniox/predictions/ARM --output experiments/ami_benchmark/providers/soniox/scores/ARM.json
```

The real runner command was invoked once for each of 28 distinct published `CASE`/`ARM` pairs. The final receipt invocation printed `verified=continuous cases=7`, `verified=forced cases=7`, `verified=segmented cases=7`, `verified=async_full_file cases=7`. Four actual unchanged scorer commands returned `pyannote_metrics_version=4.0.0`, each with six primary cases and one separate far-field pair. Boundary smoke checked native-to-source mapping across removed silence, padding, overlapping distinct IDs, null IDs, zero-length native tokens, partially outside and wholly outside support; native reconstruction checked against each of all 28 RTTMs. Per-case results, exact full-precision DER/components, receipt hashes, native-ID evidence, native timing diagnostics, recorded endpoint completion and async cleanup are in `scores/`, `predictions/`, and `results/`. These are word-token-support DER comparisons, **not** pure voice-recognition rankings or a complete AMI/test leaderboard.
