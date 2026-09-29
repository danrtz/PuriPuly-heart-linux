# Two additional speaker-recurrence controls

The two original Qwen controls are reused without new Qwen calls. The WAV files are byte-identical to those sessions, verified by decoded PCM SHA-256. Each Soniox arm and Nemotron preset was run once per fixture; the preserved six-person benchmark is unchanged.

All rows use the existing source-clip dominant-ID metric: native timestamps are intersected with each reference clip, same-ID overlap is counted once, ambiguous/missing support is not assigned an ID, and the uniquely longest ID wins. No gaps are bridged. Unresolved clips yield unresolved pairs, never successful matches. This is not DER, ASR accuracy, or a representative population estimate. Reference speaker labels are used only after inference.

**Observed result:** all 18 saved runs preserve the expected dominant-ID grouping on these controls, with no unresolved clip pairs. This is a tie on the coarse recurrence metric, not proof that every speech boundary or short within-clip assignment is equally accurate. These short two-person controls do not overturn the longer six-person observations.

## repeated: A A B B A A (22.280 s)

PCM SHA-256: `a498e5872ad0edb2ebe3fe38d811b09a824e43c6080c1ec5b74870008520c650`. Same-person pair denominator: **7**; different-person pair denominator: **8**.

| Provider / arm | Dominant native IDs in clip order | Same-person matches | False merges | Unresolved same / different pairs | Clips with multiple native IDs |
| --- | --- | ---: | ---: | --- | ---: |
| Soniox / continuous | `1, 1, 2, 2, 1, 1` | 7/7 | 0/8 | 0 / 0 | 0 |
| Soniox / forced | `1, 1, 2, 2, 1, 1` | 7/7 | 0/8 | 0 / 0 | 0 |
| Soniox / segmented | `1, 1, 2, 2, 1, 1` | 7/7 | 0/8 | 0 / 0 | 0 |
| Soniox / async_full_file | `1, 1, 2, 2, 1, 1` | 7/7 | 0/8 | 0 / 0 | 0 |
| Nemotron / offline | `0, 0, 1, 1, 0, 0` | 7/7 | 0/8 | 0 / 0 | 0 |
| Nemotron / low_latency | `0, 0, 1, 1, 0, 0` | 7/7 | 0/8 | 0 / 0 | 0 |
| Nemotron / very_low_latency | `0, 0, 1, 1, 0, 0` | 7/7 | 0/8 | 0 / 0 | 0 |
| Nemotron / ultra_low_latency | `0, 0, 1, 1, 0, 0` | 7/7 | 0/8 | 0 / 0 | 0 |
| Qwen / previous_control | `1, 1, 2, 2, 1, 1` | 7/7 | 0/8 | 0 / 0 | 2 |

### Nemotron timing

| Preset | Nominal buffer delay (s) | Measured full-clip CPU processing time after model load (s) |
| --- | ---: | ---: |
| offline | 30.400 | 1.198 |
| low_latency | 1.040 | 2.367 |
| very_low_latency | 0.640 | 3.616 |
| ultra_low_latency | 0.320 | 6.968 |

## distinct: A1 B1 A2 B2 (14.080 s)

PCM SHA-256: `d569edbca911b0db8e5b9239efe3fa5057b16e0763fc1d442a37dd6b303f0fa6`. Same-person pair denominator: **2**; different-person pair denominator: **4**.

| Provider / arm | Dominant native IDs in clip order | Same-person matches | False merges | Unresolved same / different pairs | Clips with multiple native IDs |
| --- | --- | ---: | ---: | --- | ---: |
| Soniox / continuous | `1, 2, 1, 2` | 2/2 | 0/4 | 0 / 0 | 1 |
| Soniox / forced | `1, 2, 1, 2` | 2/2 | 0/4 | 0 / 0 | 1 |
| Soniox / segmented | `1, 2, 1, 2` | 2/2 | 0/4 | 0 / 0 | 0 |
| Soniox / async_full_file | `1, 2, 1, 2` | 2/2 | 0/4 | 0 / 0 | 0 |
| Nemotron / offline | `0, 1, 0, 1` | 2/2 | 0/4 | 0 / 0 | 0 |
| Nemotron / low_latency | `0, 1, 0, 1` | 2/2 | 0/4 | 0 / 0 | 0 |
| Nemotron / very_low_latency | `0, 1, 0, 1` | 2/2 | 0/4 | 0 / 0 | 0 |
| Nemotron / ultra_low_latency | `0, 1, 0, 1` | 2/2 | 0/4 | 0 / 0 | 0 |
| Qwen / previous_control | `1, 2, 1, 2` | 2/2 | 0/4 | 0 / 0 | 3 |

### Nemotron timing

| Preset | Nominal buffer delay (s) | Measured full-clip CPU processing time after model load (s) |
| --- | ---: | ---: |
| offline | 30.400 | 0.099 |
| low_latency | 1.040 | 1.270 |
| very_low_latency | 0.640 | 1.850 |
| ultra_low_latency | 0.320 | 3.324 |

## Interpretation limits and execution

IDs are compared only within a session, never by their literal values across providers or presets. Dominant IDs can hide short within-clip switches; per-clip ID duration and uncovered/ambiguous support remain in comparison.json. Native token spans and diarization segments expose different temporal support, so uncovered duration is not ranked as missed-speech accuracy.

The repeated fixture reuses exact waveform copies; its seven same-person pairs are not seven independent trials. The distinct fixture has two returning-speaker pairs. These clean, short, read-English controls do not establish performance on multilingual/noisy VRChat speech or explain any failure in the longer six-person fixture.

The retained Qwen repeated-copy control merged B/B into one interval and had two empty source transcriptions plus phrase bleed. Its labels can still be compared, but this is not a clean ASR-success claim. The distinct Qwen control had four completed source transcripts. Neither Qwen session was rerun here.

Nemotron used the existing pinned checkpoint and CPU environment; nominal buffering is not measured live end-to-end delay. CPU processing times are offline replay measurements. Soniox app-equivalent segmentation uses the existing actual VAD/ListenDelivery/SmartTurn probe, not full desktop capture; its source timeline accounts for omitted silence and added padding.

Provider execution commands, completion markers, API usage/cleanup and effective parameters are in [Soniox execution evidence](soniox/execution_report.md) and [Nemotron execution evidence](nemotron/report.md). Original Qwen evidence is in [the validation report](../qwen_validation/report.md). No production code, settings, or user-visible behavior changed.

Rebuild fixtures with `python experiments/diarization_comparison/additional_controls/fixtures.py`. After executing the two provider runners, run the offline comparison with `python experiments/diarization_comparison/additional_controls/compare.py`. It makes no inference or API calls and rejects missing, incomplete, or wrong-waveform inputs.
