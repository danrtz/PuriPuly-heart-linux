# AMItest-derived scenario subset

Seven actual audio windows / case-local RTTMs / full-duration UEMs: six **primary, nonduplicated** 16-kHz mono Mix-Headset windows from six meetings plus a **dependent microphone pair** of the overlap window from single distant Array1-01. This is **not a full AMI/test benchmark score**. Each window starts a fresh inference session and a fresh local recording ID at time zero; speaker identity is evaluated *within* its window only. EN2002a/b/c/d are four meetings from the same EN2002 session, so speakers may recur across cases: the six windows are not six statistically independent participant groups. The 600-second long-context window is one contiguous, uninterrupted inference session, not concatenated turns. The far-field result is separate from the six-case aggregate because it shares exactly the same meeting/time/reference as `overlap_heavy`.

| Case | Meeting: source window (s) | Length (s) | Speakers | Annotated overlap (s) | Annotation-derived condition |
| --- | --- | ---: | ---: | ---: | --- |
| low_overlap | IS1009b: 440–560 | 120 | 3 | 0 | 0% overlap / 103.205 s speech |
| rapid_turn_taking | EN2002d: 1320–1440 | 120 | 4 | 38.316 | 85 distinct-speaker changes in 96 grouped turns |
| overlap_heavy | EN2002a: 1890–2010 | 120 | 4 | 30.801 | 33.97% of annotated speech has at least two speakers |
| long_return_gap | ES2004b: 150–330 | 180 | 4 | 3.393 | ES2004b.D speaks 21.034–25.764 and 169.742–175.282 s; 143.978-s return gap with 93.632 s of intervening other-speaker speech (3 speakers) |
| brief_interjections | EN2002b: 280–400 | 120 | 4 | 21.589 | 38 grouped turns <=0.7 s |
| long_context | EN2002c: 1970–2570 | 600 | 3 | 85.553 | 600 continuous seconds; 232 distinct-speaker changes |
| far_field_pair | EN2002a: 1890–2010 | 120 | 4 | 30.801 | same window as overlap_heavy; Array1-01 only |

Selection: `python3 select.py` reads **all 16** publisher `AMI/test` source RTTMs (inventory/hashes in `references/source_inventory.json`, meeting annotation spans and selected statistics in `selection.json`). Evaluate windows on a 10-second grid, excluding windows with fewer than three speakers or <40% annotated speech. Choose six distinct meetings sequentially by minimum overlap (<=3%), maximum distinct-speaker changes, maximum overlap fraction (>=12%), maximum **qualified** return gap (>=60 s), maximum grouped <=0.7 s turns (>=8), then maximum distinct-speaker changes over 600 s. A qualified return requires the same speaker's before/after turns >=1 s each, each entirely >1 s inside window, with >=20 s of intervening other-speaker annotations; the longest event with speaker/times/other-speech evidence is in `selection.json`. Tie-break by measured secondary feature, meeting ID, start time. For selection *only*, consecutive same-speaker RTTM intervals separated by <=0.6 s are grouped into turns. Speech and concurrent speech are computed directly from original intervals, never by bridging gaps. The reference RTTM is **never** grouped/smoothed. Selected case values and candidate counts are frozen in `selection.json` and source hashes in `manifest.json`. Scenario names are descriptive annotation features; rapid turns can also contain significant overlap and should not be treated as controlled factors. No predictions were used for selection.

## Reproduce locally

From repository root (Linux or WSL; `python3` and network access for downloading):

```sh
python3 experiments/ami_benchmark/fetch_references.py
python3 experiments/ami_benchmark/select.py
python3 experiments/ami_benchmark/fetch_audio.py
python3 experiments/ami_benchmark/fetch_far_field.py
python3 experiments/ami_benchmark/build.py
python3 experiments/ami_benchmark/crosscheck_audio.py
```

The first command obtains only 16 pinned textual RTTMs. `fetch_audio.py` downloads only the six selected full-length Mix-Headset WAVs from a [pinned CC BY 4.0 mirror](https://huggingface.co/datasets/ggfox00000/dia-AMICorpus-all) (full-file byte length and mirror LFS SHA-256 checked, official per-meeting URLs recorded). `fetch_far_field.py` downloads only the selected 120-s **Array1-01** PCM range from the [official source WAV](https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/EN2002a/audio/EN2002a.Array1-01.wav) using verified Content-Range responses; source WAV header/sample count/byte offsets and range hashes are recorded, and it does not download unrelated AMI files. Official full-WAV direct streaming repeatedly stalled, so the six complete headset recordings use the pinned mirror and the distant-mic case uses authenticated official byte-range requests. `crosscheck_audio.py` independently fetches the official WAV header and three nontrivial 8-KiB PCM blocks at deterministic start/middle/end portions of **each of the six primary windows**; it compares official format/full recording data length and all block bytes to the pinned complete mirror files. Exact offsets, URLs, expected/observed SHA-256 and pass/fail are in `official_audio_crosscheck.json`. Such **spot checks plus full mirror hash are not proof of full bitwise official WAV identity**. Originals/range PCM are ignored under `source_audio/`. `build.py` requires exact 16-kHz mono PCM s16le, complete source window and matching reference/source hashes, then extracts original sample indices without resampling, interpolation, VAD or silence deletion. Clips live in ignored `audio/`; locally present WAVs are required, not synthesized by scoring. `manifest.json` pins source/clip audio SHA-256, clip PCM SHA-256, source/cropped RTTM and UEM SHA-256 and portable relative paths. Repeat `build.py` to verify byte-for-byte deterministic artifacts; it refuses changed published manifests.

All reference files, source attribution and small selected labels are tracked; raw official audio and 16-kHz WAV clips are intentionally **not** tracked (download with commands above). Do not redistribute source audio or labels without complying with [attribution and CC BY 4.0 terms](ATTRIBUTION.md). Source RTTM uses third-party forced alignment of `only_words` annotations, not manually inspected transcript/video; errors and non-word vocalizations can affect measured DER. Provenance is at the exact source URL and revision, not assumed interchangeable with other AMI diarization splits.

## Score predictions

Create a directory containing exactly one `<case-id>.rttm` per published manifest case. Required RTTM `SPEAKER` lines have ten standard fields and case-local time 0..duration; `SPEAKER low_overlap 1 0.250 1.100 <NA> <NA> predicted_1 <NA> <NA>` is an example format only, **not a benchmark prediction**. Multiple speakers can share time and speaker ID strings need not match reference IDs. An explicitly empty file means a completed run reporting no speech; **a missing file, wrong recording ID, invalid interval, or out-of-bounds timestamp is an error**. Predictions must derive their own time support from the model: Soniox word-token support, Qwen utterance support, and Nemotron segment support differ. Do not fill unknown time from reference, stretch tokens to utterances, or manufacture dense frame labels. Native support and reference `only_words` timing must be considered when interpreting cross-provider DER. No audio, reference, labels or known speaker count are passed to the model.

Use a local isolated scorer environment (no credentials or model downloads):

```sh
python3 -m venv experiments/ami_benchmark/.venv
experiments/ami_benchmark/.venv/bin/pip install 'pyannote.metrics==4.0.0' 'typing_extensions==4.15.0'
experiments/ami_benchmark/.venv/bin/python experiments/ami_benchmark/score.py --predictions YOUR_OUTPUT_DIRECTORY --output YOUR_RESULTS.json
```

The standard `pyannote.metrics` diarization error rate computes optimal permutation/mapping, collar 0, **includes overlap**, and scores UEM [0,duration], including silence. Per-case miss, false alarm, speaker confusion, total speaker-time and DER are included; aggregate DER is pooled speaker-time, not averaged percentages. Speaker-count accuracy/MAE are supplemental. JSON `independent_six` means six **nonduplicated primary audio windows**, not independent speakers/participant groups; the paired-array aggregate is separate.

## Local CPU Nemotron check

With previously installed official pinned Nemotron Transformers runner and model weights under `experiments/diarization_comparison/nemotron/.venv` and `.cache/hf` (see its `report.md`):

```sh
HF_HOME=experiments/diarization_comparison/nemotron/.cache/hf HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false experiments/diarization_comparison/nemotron/.venv/bin/python experiments/ami_benchmark/run_nemotron.py
experiments/ami_benchmark/.venv/bin/python experiments/ami_benchmark/score.py --predictions experiments/ami_benchmark/predictions/nemotron_ultra_low_latency --output experiments/ami_benchmark/nemotron_ultra_low_latency_score.json
```

Runner uses the pinned NVIDIA checkpoint and official `ultra_low_latency` preset (0.32-s *nominal input buffer*, not measured live end-to-end latency), eight CPU threads, unaltered contiguous PCM and fresh speaker-cache per case. It exports native processor speaker intervals as case-local RTTM; source labels are evaluation-only. It records runtime, pinned weights, effective streaming config, input/prediction hashes, forward count and compute times in prediction provenance. This is an actual local sanity baseline, not a paid-provider or comprehensive leaderboard comparison.
