# AMI scenario subset: corrected output-segment comparison

Status: **incomplete**. Available completed cloud case/arm runs: **34/35**, plus seven retained Nemotron CPU runs. This comparison is rebuilt from saved outputs without provider calls. A missing case has no score and prevents that arm's complete benchmark aggregate. The paired far-field microphone case is excluded from the six-primary-case aggregate.

**Corrected protocol:** Soniox hypotheses now come from the official `@soniox/node@2.3.0` `segmentTranscript(tokens, {group_by: ['speaker']})` function, not a union of 60-ms token pulses. Speaker runs are grouped in provider time before mapping to original audio. Qwen native utterances and Nemotron native activity intervals are unchanged. This is end-to-end DER of these declared system outputs, not pure voice-identity or word accuracy.

The SDK uses each run's first defined start and last defined end; it can bridge silence between same-speaker tokens. Such time remains in the hypothesis and can count as false alarm. No extra VAD, gap threshold, reference-based fill, endpoint split, timestamp correction or score-driven tuning is added. The earlier token-pulse interpretation and provisional general provider ranking are superseded, not rescued by a disclaimer.

The standard scoring protocol is unchanged: pyannote.metrics 4.0.0, collar 0, overlapping speech included, complete clip UEM and optimal speaker-label mapping per case. `score_case` exposes the existing per-case calculation for explicitly incomplete evidence without relaxing the seven-case `score.py` CLI. Complete-arm scores must match their retained score artifacts; input, native-result and prediction digests are checked against provenance.

Native intervals are intersected with actual mapped source-audio support and the fixed clip UEM. Entirely out-of-audio spans are omitted and boundary-straddling spans are clipped, with original outputs and conversion diagnostics retained. This does not shift timestamps to fit the reference: native in-window timestamp errors remain scored errors. Unconfirmed event tails are not completed using the reference.

## Six primary windows: pooled speaker-time errors

All error columns are percentages of scored reference speaker-time. DER = Miss + FA + Confusion; individual displayed values are rounded.

| Provider / arm | DER % | Miss % | FA % | Confusion % | Speaker-count accuracy | Count MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Soniox / continuous | 48.27 | 23.60 | 17.40 | 7.28 | 16.67% | 1.167 |
| Soniox / forced | 70.28 | 28.21 | 21.04 | 21.03 | 16.67% | 1.167 |
| Soniox / segmented | 68.15 | 26.87 | 21.80 | 19.48 | 16.67% | 1.000 |
| Soniox / async_full_file | 48.27 | 24.81 | 17.37 | 6.09 | 33.33% | 0.667 |
| Qwen / realtime | INCOMPLETE | — | — | — | — | — |
| Nemotron / ultra_low_latency | 14.22 | 7.14 | 4.45 | 2.63 | 66.67% | 0.333 |

## Soniox before/after: representation repair, not new inference

Old token-pulse scores are retained only as a diagnostic baseline, not primary diarization scores. All columns are percentages of reference speaker-time over six primary windows. Both miss and false alarm are shown because SDK grouping can trade one for the other.

| Arm | Old pulse DER | SDK segment DER | Old miss | SDK miss | Old FA | SDK FA |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| continuous | 72.34 | 48.27 | 66.34 | 23.60 | 2.66 | 17.40 |
| forced | 89.21 | 70.28 | 73.33 | 28.21 | 6.97 | 21.04 |
| segmented | 86.66 | 68.15 | 72.35 | 26.87 | 6.40 | 21.80 |
| async_full_file | 72.65 | 48.27 | 67.31 | 24.81 | 2.55 | 17.37 |

## Retained native-token diagnostics (not scored intervals)

These are the original token widths before SDK grouping, preserved to explain the previous coverage mismatch. The scored Soniox intervals are now the SDK envelopes, not these individual pulses.

| Arm | Native token widths in ms: count |
| --- | --- |
| continuous | 0: 29, 60: 7859 |
| forced | 0: 439, 60: 7426 |
| segmented | 0: 396, 60: 7820 |
| async_full_file | 0: 234, 60: 7635 |

## Per-case DER (%)

| Case | Soniox / continuous | Soniox / forced | Soniox / segmented | Soniox / async_full_file | Qwen / realtime | Nemotron / ultra_low_latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| low_overlap | 15.39 | 17.53 | 25.31 | 15.52 | 16.56 | 1.37 |
| rapid_turn_taking | 64.54 | 78.31 | 76.96 | 72.90 | 84.40 | 23.09 |
| overlap_heavy | 70.90 | 82.46 | 77.23 | 68.15 | 83.46 | 15.85 |
| long_return_gap | 44.57 | 51.59 | 41.43 | 45.16 | 34.98 | 3.69 |
| brief_interjections | 62.60 | 80.31 | 84.90 | 49.67 | NOT COMPLETED | 31.18 |
| long_context | 42.58 | 77.28 | 74.18 | 43.61 | 85.68 | 12.63 |
| far_field_pair | 61.44 | 80.88 | 80.17 | 69.49 | 79.81 | 18.74 |

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
- No oracle speaker counts or reference timings are supplied to inference or SDK grouping. Unattributed output is not assigned an invented speaker ID. SDK grouping, not gold timing, defines Soniox interval support; grouping does not prove continuous acoustic speech. Completed inference is not proof of complete transcription.
- Benchmark waveforms, references, standard DER semantics, Qwen outputs and previous Nemotron evidence are unchanged. Soniox interval construction is deliberately corrected; original responses remain immutable and prior token-pulse artifacts are archived. No production UI, configuration or application behavior changes.

Rebuild this comparison offline with `experiments/ami_benchmark/.venv/bin/python experiments/ami_benchmark/compare_providers.py` under Linux/WSL. It makes no provider/model calls and normally requires all 35 completed cloud case/arm runs plus seven retained Nemotron predictions. `--allow-incomplete` explicitly permits declared incomplete Qwen receipts, reports only completed per-case values, and withholds Qwen aggregate scores. It does not satisfy the outstanding inference requirement.

**Outstanding:** Qwen / realtime: brief_interjections. See the provider execution report for the preserved failure and transport evidence; no full comparison completion is claimed.
