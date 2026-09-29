# AMI scenario subset: native-output provider comparison

Status: **incomplete**. Newly completed case/arm runs: **34/35**. The seven prior Nemotron ultra-low-latency CPU inferences are reused without new model calls. A missing case has no score, is not an empty completed prediction, and prevents that arm's complete benchmark aggregate. The far-field case repeats the overlap case's content through a different microphone and is excluded from the six-primary-case aggregate.

**Interpretation:** these are standard DER scores of each provider's native timestamped output, not a controlled ranking of speaker-identity recognition alone. Soniox exposes word-token spans, Qwen speech-event spans, and Nemotron diarization segments. Their speech-time support differs. No reference-based gap filling, token stretching, or dominant-speaker reduction is applied. Read miss, false alarm, confusion and speaker counts together.

The standard scoring protocol is unchanged: pyannote.metrics 4.0.0, collar 0, overlapping speech included, complete clip UEM and optimal speaker-label mapping per case. `score_case` exposes the existing per-case calculation for explicitly incomplete evidence without relaxing the seven-case `score.py` CLI. Complete-arm scores must match their retained score artifacts; input, native-result and prediction digests are checked against provenance.

Native intervals are intersected with actual mapped source-audio support and the fixed clip UEM. Entirely out-of-audio spans are omitted and boundary-straddling spans are clipped, with original outputs and conversion diagnostics retained. This does not shift timestamps to fit the reference: native in-window timestamp errors remain scored errors. Unconfirmed event tails are not completed using the reference.

## Six primary windows: pooled speaker-time errors

All error columns are percentages of scored reference speaker-time. DER = Miss + FA + Confusion; individual displayed values are rounded.

| Provider / arm | DER % | Miss % | FA % | Confusion % | Speaker-count accuracy | Count MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Soniox / continuous | 72.34 | 66.34 | 2.66 | 3.34 | 16.67% | 1.167 |
| Soniox / forced | 89.21 | 73.33 | 6.97 | 8.91 | 16.67% | 1.167 |
| Soniox / segmented | 86.66 | 72.35 | 6.40 | 7.90 | 16.67% | 1.000 |
| Soniox / async_full_file | 72.65 | 67.31 | 2.55 | 2.80 | 33.33% | 0.667 |
| Qwen / realtime | INCOMPLETE | — | — | — | — | — |
| Nemotron / ultra_low_latency | 14.22 | 7.14 | 4.45 | 2.63 | 66.67% | 0.333 |

## Soniox native time-support diagnostics

Counts below come from all seven saved native outputs per arm, before source/UEM projection. A short token pulse is not a continuous speech region. High missed-speech DER under this literal-support protocol does not mean the same percentage of words or speaker identities is wrong.

| Arm | Native token widths in ms: count |
| --- | --- |
| continuous | 0: 29, 60: 7859 |
| forced | 0: 439, 60: 7426 |
| segmented | 0: 396, 60: 7820 |
| async_full_file | 0: 234, 60: 7635 |

## Per-case DER (%)

| Case | Soniox / continuous | Soniox / forced | Soniox / segmented | Soniox / async_full_file | Qwen / realtime | Nemotron / ultra_low_latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| low_overlap | 65.80 | 74.31 | 70.86 | 64.91 | 16.56 | 1.37 |
| rapid_turn_taking | 82.03 | 91.17 | 88.35 | 87.08 | 84.40 | 23.09 |
| overlap_heavy | 81.54 | 91.54 | 88.23 | 80.06 | 83.46 | 15.85 |
| long_return_gap | 69.14 | 84.25 | 83.39 | 68.56 | 34.98 | 3.69 |
| brief_interjections | 81.46 | 92.33 | 93.30 | 77.24 | NOT COMPLETED | 31.18 |
| long_context | 67.61 | 91.40 | 88.13 | 68.48 | 85.68 | 12.63 |
| far_field_pair | 76.04 | 88.99 | 89.64 | 81.84 | 79.81 | 18.74 |

## Reference / predicted speaker counts

| Case | Reference | Soniox / continuous | Soniox / forced | Soniox / segmented | Soniox / async_full_file | Qwen / realtime | Nemotron / ultra_low_latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| low_overlap | 3 | 2 | 2 | 2 | 2 | 2 | 2 |
| rapid_turn_taking | 4 | 2 | 2 | 2 | 3 | 12 | 4 |
| overlap_heavy | 4 | 2 | 2 | 3 | 3 | 17 | 4 |
| long_return_gap | 4 | 3 | 3 | 3 | 3 | 3 | 3 |
| brief_interjections | 4 | 3 | 3 | 3 | 4 | NOT COMPLETED | 4 |
| long_context | 3 | 3 | 3 | 3 | 3 | 18 | 3 |
| far_field_pair | 4 | 3 | 3 | 3 | 3 | 11 | 4 |

## Execution evidence and limits

- [Soniox execution and conversion](providers/soniox/execution_report.md): continuous RT, fixed-six-second finalize RT, actual app-equivalent VAD/SmartTurn segmentation RT, and full-file async. Segmented provider time is mapped back to original source time; padding is not speech evidence.
- [Qwen execution and conversion](providers/qwen/execution_report.md): native speech-start speaker IDs correlated with native stop events; item IDs are not speaker IDs.
- [Retained Nemotron execution](report.md): official ultra-low-latency preset, nominal 0.32-second input buffer. Unpaced CPU compute time is not live end-to-end latency.
- Each case starts fresh state; the 600-second case retains one continuous session/cache. Speaker identity is not compared across cases. Six primary windows are nonduplicated audio, not independent participants; several meetings can share participants.
- This is an annotation-selected AMI test subset, not the full AMI test score, ASR/translation accuracy, a statistically independent population estimate, or evidence about six-plus speakers and VRChat. The forced-aligned reference covers words, not all vocal sounds; boundaries and missing annotations can affect DER.
- No oracle speaker counts or reference timings are supplied to inference. Unattributed output is reported by each provider but never invented as an optimally mappable reference speaker. Native output gaps remain gaps; a completed run is not necessarily a complete speech transcription.
- Benchmark waveforms, references, scoring semantics and previous Nemotron evidence remain unchanged. No production UI, configuration or application behavior changes.

Rebuild this comparison offline with `experiments/ami_benchmark/.venv/bin/python experiments/ami_benchmark/compare_providers.py` under Linux/WSL. It makes no provider/model calls and normally requires all 35 new completed runs plus seven retained predictions. `--allow-incomplete` explicitly permits declared incomplete Qwen receipts, reports only completed per-case values, and withholds Qwen aggregate scores. It does not satisfy the outstanding inference requirement.

**Outstanding:** Qwen / realtime: brief_interjections. See the provider execution report for the preserved failure and transport evidence; no full comparison completion is claimed.
