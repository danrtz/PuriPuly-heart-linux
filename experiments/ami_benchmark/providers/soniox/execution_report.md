# Soniox AMItest-derived seven-case execution

**Current primary measurement is the SDK speaker-grouped remeasurement below.** The original execution/projection and score tables in the following sections document the **historical token-pulse baseline only**, archived verbatim under `token_pulse_baseline/`; they are not the current canonical hypothesis. The original 28 complete provider results were not changed or rerun, and their embedded `conversion`, `prediction_sha256` and `predicted_speaker_ids` remain historical metadata, not current SDK projection receipts.

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

During the **original token-pulse run**, the runner was invoked once for each of 28 distinct published `CASE`/`ARM` pairs. The historical receipt invocation verified seven cases per arm, and four historical scorer commands returned `pyannote_metrics_version=4.0.0` with six primary cases and one separately scored far-field pair. The former boundary smoke checked token-level mapping, zero-length and null-ID tokens; old token-union per-case RTTMs, receipts and scores are now exclusively preserved in `token_pulse_baseline/`, with native API evidence and original projection metadata in `results/`. These pulse results are **not** current output-segment DER, pure voice-recognition rankings, or a complete AMI/test leaderboard.

## Offline repair: official SDK speaker-grouped output (current)

The declared Soniox hypothesis is the **actual** `segmentTranscript(tokens, { group_by: ['speaker'] })` exported by pinned `@soniox/node@2.3.0`, source commit `8661b750e6cbd0a2c382f6b79c7c198e29c4a2b0`. The isolated dependency is reproducible with `npm ci --no-audit --no-fund` in `providers/soniox/sdk/`, using `sdk/package-lock.json` (npm tarball integrity `sha512-WGDxaUFzet/NXoLYj5kw/JPAvFFWwce+iwhBNfWupNpXubXR5ijpUO6Qt5xnVYmpqnDtG57t8TIfKaFprL6y3g==`, MIT). `sdk/segments.mjs` invokes that function directly; SHA-256 `bb530cec977d249e825fab2076fc4f9e99386ab8b947c074d736f7f8a2455b4a`. Both final RT token lists and async token lists use the same speaker-only option. This SDK speaker-run envelope is **not** provider-native VAD or proof of continuous acoustic speech: it starts at the run's first defined token start and ends at its last defined token end, retaining arbitrarily long intervening silence, order, distinct-speaker overlap, and unattributed runs. Neither reference times/counts nor extra VAD, endpoint/`<fin>` splitting, language splitting, timestamp sorting, silence/gap thresholds, global speaker merging, synthetic support, or clock adjustment enter conversion.

Group first **on provider time**, then intersect each grouped interval with the saved source-piece timeline; removed source audio and inserted padding are never assigned speaker time. No negative/inverted/nonfinite SDK interval is repaired; a zero/untimed group generates no positive interval, and groups lacking an attributed speaker do not acquire an artificial label. `sdk_output/<arm>/<case>.json` records each SDK group with original token-index membership, text/time/speaker/language, projected source intervals and detailed projection diagnostics. `predictions/<arm>/<case>.rttm` and `scores/<arm>.json` now contain only current SDK-segment results. `predictions/<arm>/provenance.json` retains `model`, `mode` and the seven existing `cases` receipt fields (`id`, `input_pcm_sha256`, `prediction_rttm_sha256`, `completed`, `native_result`, `native_result_sha256`), adds `hypothesis.method=soniox_sdk_speaker_segments`, `hypothesis.group_by=['speaker']`, package/version/source/integrity/bridge digest, `post_group_gap_filling=false`, `clock_correction=false`, and per-case `sdk_output`, `sdk_output_sha256`, `sdk_groups`, `projection_diagnostics`. The verifier reruns the real SDK grouping against immutable native tokens, checks source/lifecycle/hash and compares every SDK artifact and reconstructed RTTM. The old raw embedded pulse-projection hash is intentionally **not** a verification target.

Historical `token_pulse_baseline/predictions/<arm>/` contains all 28 old RTTMs plus four original provenance files; `token_pulse_baseline/scores/<arm>.json` contains the four exact old score JSONs. The archive `sha256.json` enumerates all 36 originals. SHA-256 of the original canonical native result files equals each corresponding old provenance receipt for **28/28** before and after migration. The dependent far-field pair is separate, not pooled with the six primary windows. All four scores below are real reruns of the unchanged `score.py` in the WSL pyannote.metrics 4.0.0 environment: full-duration UEM, zero collar, overlap included, optimal per-case speaker mapping. DER is output-segment diarization error, **not** a pure voice-ID accuracy rate; SDK-bridged silence incurs false alarm. The forced and segmented arms retain their previously observed time drift, including forced +11.52 s at 600 s; no authority to correct the clock was assumed.

| Arm | Six DER old→SDK | Six miss old→SDK (s) | Six false alarm old→SDK (s) | Six confusion old→SDK (s) | Six known-speaker support union old→SDK (s / 1260 s) | Paired DER old→SDK | Paired support union old→SDK (s / 120 s) | SDK groups, all seven; largest bridged token gap |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| continuous | 72.34%→48.27% | 776.229→276.091 | 31.157→203.559 | 39.046→85.154 | 424.980→1097.520 | 76.04%→61.44% | 46.560→101.820 | 484; 9.060 s |
| forced | 89.21%→70.28% | 857.982→330.085 | 81.590→246.213 | 104.252→246.055 | 393.660→1086.180 | 88.99%→80.88% | 42.300→97.020 | 470; 9.180 s |
| segmented | 86.66%→68.15% | 846.577→314.356 | 74.917→255.076 | 92.464→227.966 | 397.128→1058.916 | 89.64%→80.17% | 41.500→89.836 | 480; 4.380 s |
| async_full_file | 72.65%→48.27% | 787.520→290.322 | 29.848→203.270 | 32.709→71.231 | 412.380→1083.000 | 81.84%→69.49% | 45.720→98.340 | 505; 8.880 s |

SDK support is longer than pulse support by 672.540 / 692.520 / 661.788 / 670.620 s across the respective six-case arms. Across seven windows, sums of positive within-run token gaps are 727.800 / 757.860 / 793.620 / 723.240 s respectively; these are *token-gap sums*, not additional net union support (overlap, mapping and padding change the latter). The increased prediction support reduces misses but increases false alarms, and confusion rises in every pooled arm; the lower DER is **not** an isolated improvement in speaker identity. The following case rows give original→SDK DER, component speaker-seconds (miss/false-alarm/confusion) and predicted speaker counts. The reference speaker-time and reference speaker counts are unchanged and recorded in both corresponding full score JSONs.

| Case | Arm | DER % old→SDK | Miss old→SDK | False alarm old→SDK | Confusion old→SDK | Predicted speakers old→SDK |
|---|---|---:|---:|---:|---:|---:|
| low_overlap | continuous | 65.80→15.39 | 65.786→0.534 | 2.121→15.349 | 0→0 | 2→2 |
| rapid_turn_taking | continuous | 82.03→64.54 | 107.476→62.568 | 3.456→12.608 | 9.051→19.220 | 2→2 |
| overlap_heavy | continuous | 81.54→70.90 | 85.659→46.603 | 3.979→15.803 | 15.472→28.990 | 2→2 |
| long_return_gap | continuous | 69.14→44.57 | 83.328→5.055 | 2.547→50.274 | 0.050→0.063 | 3→3 |
| brief_interjections | continuous | 81.46→62.60 | 83.013→34.229 | 3.452→16.768 | 9.327→22.627 | 3→3 |
| long_context | continuous | 67.61→42.58 | 350.967→127.102 | 15.602→92.757 | 5.146→14.254 | 3→3 |
| far_field_pair | continuous | 76.04→61.44 | 86.862→45.558 | 4.522→18.478 | 6.634→15.159 | 3→3 |
| low_overlap | forced | 74.31→17.53 | 70.875→0.900 | 5.590→16.675 | 0.222→0.516 | 2→2 |
| rapid_turn_taking | forced | 91.17→78.31 | 114.539→71.208 | 7.399→16.988 | 11.405→26.337 | 2→2 |
| overlap_heavy | forced | 91.54→82.46 | 94.676→55.043 | 8.676→22.083 | 14.639→29.169 | 2→2 |
| long_return_gap | forced | 84.25→51.59 | 93.031→6.721 | 9.370→50.800 | 2.301→6.591 | 3→3 |
| brief_interjections | forced | 92.33→80.31 | 88.947→39.841 | 7.106→19.860 | 12.532→34.749 | 3→3 |
| long_context | forced | 91.40→77.28 | 395.914→156.372 | 43.449→119.807 | 63.153→148.693 | 3→3 |
| far_field_pair | forced | 88.99→80.88 | 95.412→56.630 | 8.812→24.750 | 10.480→22.879 | 3→3 |
| low_overlap | segmented | 70.86→25.31 | 68.545→1.260 | 4.268→24.295 | 0.322→0.564 | 2→2 |
| rapid_turn_taking | segmented | 88.35→76.96 | 112.720→69.722 | 6.396→18.610 | 10.102→24.235 | 2→2 |
| overlap_heavy | segmented | 88.23→77.23 | 94.713→50.803 | 8.445→24.823 | 10.566→23.918 | 3→3 |
| long_return_gap | segmented | 83.39→41.43 | 92.514→6.485 | 9.265→40.068 | 1.865→4.939 | 3→3 |
| brief_interjections | segmented | 93.30→84.90 | 89.176→34.480 | 7.163→24.979 | 13.379→40.389 | 3→3 |
| long_context | segmented | 88.13→74.18 | 388.909→151.606 | 39.380→122.301 | 56.230→133.921 | 3→3 |
| far_field_pair | segmented | 89.64→80.17 | 95.759→57.719 | 8.395→21.983 | 11.396→23.639 | 3→3 |
| low_overlap | async_full_file | 64.91→15.52 | 65.087→0.723 | 1.902→15.298 | 0→0 | 2→2 |
| rapid_turn_taking | async_full_file | 87.08→72.90 | 109.536→65.878 | 3.176→10.158 | 14.653→30.581 | 3→3 |
| overlap_heavy | async_full_file | 80.06→68.15 | 87.612→46.158 | 4.492→17.698 | 11.093→23.994 | 3→3 |
| long_return_gap | async_full_file | 68.56→45.16 | 82.270→5.363 | 2.629→50.402 | 0.309→0.362 | 3→3 |
| brief_interjections | async_full_file | 77.24→49.67 | 85.444→39.282 | 3.243→13.901 | 2.150→5.234 | 4→4 |
| long_context | async_full_file | 68.48→43.61 | 357.571→132.918 | 14.406→95.813 | 4.504→11.060 | 3→3 |
| far_field_pair | async_full_file | 81.84→69.49 | 87.948→47.698 | 4.768→17.138 | 12.771→24.742 | 3→3 |

Executed locally without API keys, uploads or additional Soniox requests: Windows main-venv `python experiments/ami_benchmark/providers/soniox/run.py --convert-all` converted all **28/28** complete native results; `python experiments/ami_benchmark/providers/soniox/receipts.py` printed seven verified cases for each of four arms; four separate WSL `experiments/ami_benchmark/.venv/bin/python experiments/ami_benchmark/score.py --predictions experiments/ami_benchmark/providers/soniox/predictions/ARM --output experiments/ami_benchmark/providers/soniox/scores/ARM.json` scored all seven cases per arm (pyannote.metrics 4.0.0). The focused smoke invoked the same official SDK function for A→B→A, null vs absent speaker, zero/untimed token, language transition, bridged silence, last token end rather than max end, overlapping speakers; it then exercised compaction, padding and source-piece crossing, including a speaker overlap. Historical scores remain at `token_pulse_baseline/scores/`; the two sets must not be interchanged.

Independent checkpoint review caught a live-path regression from the SDK migration: the `wave` import had been removed while `load_audio` still used it. The import is restored. The actual loader now reads the frozen `low_overlap` WAV as 3,840,000 PCM bytes / 120.0 s and passes its manifest WAV/PCM digest checks. The saved-output CLI `--case low_overlap --arm continuous --convert-existing` again returned `sdk_segments_verified`. The live CLI branch `--case low_overlap --arm async_full_file`, with a noncredential sentinel, reached its existing-result refusal before audio/model requests. This verifies the repaired loader and both local CLI routes, not a new provider inference; no additional Soniox request was made. The saved-output measurements above were unaffected by the missing import.
