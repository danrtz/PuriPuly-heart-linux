# AMItest-derived scenario subset: completed construction and CPU sanity run

## Delivered

Analyzed all 16 pinned `AMI/test` RTTMs; selected six natural, contiguous, **primary nonduplicated** windows from six different meetings plus one dependent exact same-window far-field microphone pair. Seven real 16-kHz mono PCM WAV clips, case-local forced-aligned RTTMs and full-duration UEMs were built locally. Six headset source recordings were downloaded from the SHA-pinned CC BY 4.0 full-WAV mirror; the original AMI Array1-01 source was retrieved by 469 individually verified HTTP 206 byte ranges of just the selected 120-s PCM window. Source RTTM/publisher revision, original source URL, mirror LFS/file SHA-256, original distant WAV header/byte range, source and selected clip PCM hashes are frozen in inventories and `manifest.json`. Local audio/source caches and cropped WAVs are ignored; reproducible commands and licensing/limitations are in [README.md](README.md) and [ATTRIBUTION.md](ATTRIBUTION.md). This is a **selected AMItest-derived scenario subset, not full AMI/test evaluation**.

Selection is source-annotation-only and deterministic: 10-s grid, six different meetings, >40% annotated speech, >=3 speakers; case-specific annotation ranks/thresholds and 0.6-s same-speaker turn-grouping **only for selection**, not label transformation. `selection.json` records all-16 inventory statistics, candidate counts and case features. The long-return event is **not silence or a clipped speaker's first/last appearance**: ES2004b.D speaks at local 21.034–25.764 s and returns at 169.742–175.282 s, a 143.978-s gap containing 93.632 s of other-speaker speech by three participants. Window UEM [0,duration] includes all original silences and all overlapping speakers. Long-context is one uninterrupted 600-s input with one speaker cache, not assembled speech and not reset within the case. Primary windows each reset cache/identity; identities across different windows/meetings are **not** evaluated. EN2002a/b/c/d share one session and participants may recur: separate nonduplicated audio inputs do **not** imply statistically independent participant groups. Three- and four-speaker examples both occur.

## Reproduction and verification executed

Commands executed from repository root under WSL Ubuntu:

```sh
python3 experiments/ami_benchmark/fetch_references.py
python3 experiments/ami_benchmark/select.py
python3 experiments/ami_benchmark/fetch_audio.py
python3 experiments/ami_benchmark/fetch_far_field.py
python3 experiments/ami_benchmark/build.py
python3 experiments/ami_benchmark/crosscheck_audio.py
HF_HOME=experiments/diarization_comparison/nemotron/.cache/hf HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false experiments/diarization_comparison/nemotron/.venv/bin/python experiments/ami_benchmark/run_nemotron.py
experiments/ami_benchmark/.venv/bin/python experiments/ami_benchmark/score.py --predictions experiments/ami_benchmark/predictions/nemotron_ultra_low_latency --output experiments/ami_benchmark/nemotron_ultra_low_latency_score.json
```

Isolated scorer dependency: `pyannote.metrics==4.0.0` and `typing_extensions==4.15.0` (the former's wheel used typing extensions but did not install it transitively). No repo lock or shared environment changed. A focused disposable script verified all 7 WAV headers and exact PCM source slices, hashes and full bounds; roundtrip exact cropped RTTMs and UEM; renamed reference labels yield DER=0 under optimal mapping; all-empty completed RTTM yields 100% missed speech; a merged-speaker hypothesis produces positive confusion; deliberate missing file, unknown case, wrong recording ID and out-of-bounds span fail; synthetic overlapped speaker-time 1.4 s for one second wall time yields missed 0.4 s when the second concurrent speaker is omitted. Re-running selector and builder after inference reproduced **byte-identical 23 selection/manifest/WAV/RTTM/UEM artifacts**. No permanent tests or paid/cloud provider inference.

Official entire WAV streaming from groups.inf.ed.ac.uk twice stalled/timed out after ~80–230 KB despite a valid listing/header; direct 4 MB range requests also stalled. Resolution: six complete WAVs from SHA-pinned [alternate mirror](https://huggingface.co/datasets/ggfox00000/dia-AMICorpus-all/tree/a249db53de253a3a0a864c93a51d613159dfec7c), with full-file SHA-256 verified against mirror LFS metadata, and the required distant microphone PCM fetched in independently authenticated 8-KB byte ranges from the [official Array1-01 WAV](https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/EN2002a/audio/EN2002a.Array1-01.wav). No full corpus or other distant recordings fetched. `far_field_inventory.json` records original WAV size 68,566,744 B, 34,283,350 samples, PCM offset 44, requested byte indices 60,480,044–64,320,043, and selected original PCM SHA-256 `331839fb6b0d91d253b0f2a985d1d71ce444bb5904a1ac9d2b1d9220e4ac82c3`.

Official-vs-mirror Mix-Headset provenance was additionally checked **before freeze**, without model rerun: `crosscheck_audio.py` fetched authenticated HTTP 206 WAV prefix [0,4095] and three independently selected nontrivial 8-KiB PCM ranges (highest local PCM RMS among deterministic start/middle/end 11-s bands) from **each of all six** official source WAVs. All six original headers had identical first-4096-byte SHA-256 to their corresponding mirror files, matched 16-kHz mono PCM format, complete file length, data offset and data length; **all 18 original PCM blocks matched mirror bytes exactly**, with lowest checked RMS 376.909 s16 units. Exact URLs, original/mirror byte offsets, per-block expected/observed SHA-256, RMS and results: [`official_audio_crosscheck.json`](official_audio_crosscheck.json). The source's complete SHA-256 was checked against pinned **mirror** LFS metadata, not an official full-file digest; bounded original PCM spot checks **do not prove full bitwise equivalence of every official sample**. Same pinned local audio/labels and unchanged model/scorer evidence remain applicable.

## Observed local Nemotron CPU baseline

Real audio input and inference for **all seven** cases, pinned `nvidia/Nemotron-3-Diarization@f667ed73aee57d40cc39428eb768b4fd87a0a29e`, weights SHA-256 `c074d86335b3b794f8fa5edc25594558f128bdb3914d27806a3a5a2e44963cb6`, official Transformers `ultra_low_latency` preset. Eight CPU threads, Python 3.12.3, torch 2.14.0+cpu, Transformers 5.18.0.dev0 in WSL2; effective cache/FIFO/chunk/right/update = 264/264/3/1/222 (80-ms units), **nominal audio input buffer 0.32 s, not live end-to-end latency**. Fresh cache at each case, 600-s case uninterrupted; seven compute times (s) 82.596, 79.238, 78.865, 126.294, 79.482, 446.031, 78.702 (sum 971.208 s excluding initial 6.330-s model load); model forwards 500, 500, 500, 750, 500, 2500, 500 respectively. Native processor segments converted directly to validated RTTMs. Full per-case input PCM / output RTTM SHA-256 hashes, forward count and effective config: [`predictions/nemotron_ultra_low_latency/provenance.json`](predictions/nemotron_ultra_low_latency/provenance.json).

Standard `pyannote.metrics` DER, collar 0, overlap **included**, entire clip UEM including silence, optimal speaker mapping. Components/denominator are seconds of speaker-time; round percentages for display only, [exact scored JSON](nemotron_ultra_low_latency_score.json):

| Case | DER | Miss (s) | False alarm (s) | Confusion (s) | Ref/pred active speakers |
| --- | ---: | ---: | ---: | ---: | ---: |
| low_overlap | 1.37% | 0.448 | 0.923 | 0.040 | 3/2 |
| rapid_turn_taking | 23.09% | 17.938 | 7.418 | 8.413 | 4/4 |
| overlap_heavy | 15.85% | 12.958 | 5.628 | 1.850 | 4/4 |
| long_return_gap | 3.69% | 2.097 | 2.406 | 0.089 | 4/3 |
| brief_interjections | 31.18% | 12.521 | 9.360 | 14.791 | 4/4 |
| long_context | 12.63% | 37.525 | 26.320 | 5.616 | 3/3 |
| **Six primary nonduplicated windows (pooled)** | **14.22%** | **83.487** | **52.055** | **30.799** | speaker-count accuracy 4/6 |
| far_field_pair (dependent, separate) | 18.74% | 14.546 | 6.006 | 3.600 | 4/4 |

Pooled primary-six speaker-time denominator = 1170.052 s, far-field duplicate denominator = 128.900 s (not included in primary aggregate). The JSON key `independent_six` means independent **recording inputs**, not independent speaker cohorts. The 3-vs-2/4-vs-3 count disagreements show why DER alone is insufficient: a rare reference speaker can be missed with low time-weighted DER. Do not use model speaker literal IDs as ground truth IDs or pretend a dominant whole-clip speaker label is DER.

## Interpretation limits

The [annotation publisher](https://github.com/nttcslab-sp/diar-forced-alignment/blob/9527b7c64846fb38316a610f32e9d3466bd6d8b7/README.md) used forced-aligned `only_words`, not vocal sounds; possible alignment, transcription and out-of-vocabulary errors remain. This benchmark uses the publisher's *test split labels* and one selected window per six meetings, not all 16 meetings or a standard full-test score. The [pinned Nemotron card](https://huggingface.co/nvidia/Nemotron-3-Diarization/blob/f667ed73aee57d40cc39428eb768b4fd87a0a29e/README.md) lists AMI **train and development** (not AMI test) in training and AMI individual headsets train/development as another training source; this is not a claim that every future model/vendor is AMI-unseen. Soniox and Qwen training provenance is unknown here. No paid-provider leaderboard was run; provider-native token/utterance/segment time-support mismatch must be disclosed in any later comparison, never patched with gold labels or silence interpolation. Streaming nominal buffer time is not a measured live meeting latency.
