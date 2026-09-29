# Native-speaker recurrence across twelve source clips

## Scope and primary metric

This offline comparison reuses the **51.730-second** 16-kHz mono fixture (SHA-256 `2eb1ab143c2a7dbaa7448c31b44dd8c517b85042e769f2da5d2ddaec14028762`): twelve known source clips from six LibriSpeech test-clean speakers, each speaker represented by two clips. It analyzes saved normalized spans only; no reference information was sent to inference.

For each source clip, normalized native spans are clipped to the known source interval and swept at their exact endpoints. Duration contributes to an ID only where exactly one distinct non-null native ID is active and no null-ID span overlaps. Overlapping spans with the same ID count once. A null-ID overlap with fewer than two known IDs is unknown; two or more distinct known IDs are ambiguous; time with no active span is uncovered support. The dominant ID is the ID with the greatest uniquely labeled duration. No unique duration or a tied maximum makes the clip unresolved. No gap bridging or smoothing is applied; zero-duration spans contribute no duration.

The primary comparison is deliberately a small **12-clip dominant-ID recurrence probe**, not DER or missed-speech accuracy. It counts same-person clip-pair ID matches out of 6 and different-person false merges out of 60. A pair with either clip unresolved is unresolved, never correct. IDs are compared only within one model run; ID values across providers and runs have no shared namespace.

| Run | Same-person ID matches / 6 (splits; unresolved) | Different-person false merges / 60 (distinct IDs; unresolved) | Unresolved clips | Clips with >1 native ID |
| --- | --- | --- | ---: | ---: |
| Soniox realtime — continuous | 4 / 6 (splits 2; unresolved 0) | 10 / 60 (distinct 50; unresolved 0) | 0 | 2 |
| Soniox realtime — fixed 6-s control | 4 / 6 (splits 2; unresolved 0) | 10 / 60 (distinct 50; unresolved 0) | 0 | 3 |
| Soniox realtime — app-segmentation equivalent | 4 / 6 (splits 2; unresolved 0) | 10 / 60 (distinct 50; unresolved 0) | 0 | 3 |
| Soniox async full-file | 5 / 6 (splits 1; unresolved 0) | 12 / 60 (distinct 48; unresolved 0) | 0 | 0 |
| Nemotron-3-Diarization — offline-style | 6 / 6 (splits 0; unresolved 0) | 0 / 60 (distinct 60; unresolved 0) | 0 | 0 |
| Nemotron-3-Diarization — low latency | 6 / 6 (splits 0; unresolved 0) | 0 / 60 (distinct 60; unresolved 0) | 0 | 0 |
| Nemotron-3-Diarization — very low latency | 6 / 6 (splits 0; unresolved 0) | 0 / 60 (distinct 60; unresolved 0) | 0 | 0 |
| Nemotron-3-Diarization — ultra low latency | 6 / 6 (splits 0; unresolved 0) | 0 / 60 (distinct 60; unresolved 0) | 0 | 0 |
| Qwen 3.8 LiveTranslate realtime | 0 / 6 (splits 6; unresolved 0) | 0 / 60 (distinct 60; unresolved 0) | 0 | 11 |

### Per-clip dominant labels and duration support

Unique-ID durations include only uniquely labeled time. Unknown, ambiguous, and uncovered seconds partition the remainder of each known clip; uncovered time is a support diagnostic, not a missed-speech score. `Observed IDs` exposes within-clip changes that a single dominant label can hide.

| Run | Clip | Reference | Dominant ID | Unique ID seconds | Unique total (s) | Unknown (s) | Ambiguous (s) | Uncovered (s) | Observed IDs |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Soniox realtime — continuous | `1089-134686-0001` | 1089 | `1` | `1`: 0.960 | 0.960 | 0.000 | 0.000 | 2.315 | `1` |
| Soniox realtime — continuous | `1995-1826-0003` | 1995 | `2` | `2`: 1.020 | 1.020 | 0.000 | 0.000 | 2.070 | `2` |
| Soniox realtime — continuous | `1188-133604-0001` | 1188 | `1` | `1`: 2.100 | 2.100 | 0.000 | 0.000 | 6.940 | `1` |
| Soniox realtime — continuous | `2094-142345-0004` | 2094 | `2` | `2`: 0.720 | 0.720 | 0.000 | 0.000 | 1.920 | `2` |
| Soniox realtime — continuous | `121-121726-0001` | 121 | `4` | `3`: 0.120, `4`: 0.960 | 1.080 | 0.000 | 0.000 | 4.845 | `3`, `4` |
| Soniox realtime — continuous | `260-123286-0001` | 260 | `1` | `1`: 0.600 | 0.600 | 0.000 | 0.000 | 2.470 | `1` |
| Soniox realtime — continuous | `1089-134686-0003` | 1089 | `5` | `5`: 0.840 | 0.840 | 0.000 | 0.000 | 1.840 | `5` |
| Soniox realtime — continuous | `1995-1826-0004` | 1995 | `2` | `2`: 0.840 | 0.840 | 0.000 | 0.000 | 2.195 | `2` |
| Soniox realtime — continuous | `1188-133604-0006` | 1188 | `1` | `1`: 0.720 | 0.720 | 0.000 | 0.000 | 1.680 | `1` |
| Soniox realtime — continuous | `2094-142345-0007` | 2094 | `2` | `2`: 0.660 | 0.660 | 0.000 | 0.000 | 2.040 | `2` |
| Soniox realtime — continuous | `121-121726-0002` | 121 | `4` | `3`: 0.120, `4`: 0.480 | 0.600 | 0.000 | 0.000 | 3.810 | `3`, `4` |
| Soniox realtime — continuous | `260-123286-0004` | 260 | `5` | `5`: 0.720 | 0.720 | 0.000 | 0.000 | 2.745 | `5` |
| Soniox realtime — fixed 6-s control | `1089-134686-0001` | 1089 | `1` | `1`: 0.960 | 0.960 | 0.000 | 0.000 | 2.315 | `1` |
| Soniox realtime — fixed 6-s control | `1995-1826-0003` | 1995 | `2` | `2`: 0.960 | 0.960 | 0.000 | 0.000 | 2.130 | `2` |
| Soniox realtime — fixed 6-s control | `1188-133604-0001` | 1188 | `1` | `1`: 2.100 | 2.100 | 0.000 | 0.000 | 6.940 | `1` |
| Soniox realtime — fixed 6-s control | `2094-142345-0004` | 2094 | `2` | `2`: 0.600 | 0.600 | 0.000 | 0.000 | 2.040 | `2` |
| Soniox realtime — fixed 6-s control | `121-121726-0001` | 121 | `4` | `3`: 0.120, `4`: 0.830 | 0.950 | 0.000 | 0.000 | 4.975 | `3`, `4` |
| Soniox realtime — fixed 6-s control | `260-123286-0001` | 260 | `1` | `1`: 0.600 | 0.600 | 0.000 | 0.000 | 2.470 | `1` |
| Soniox realtime — fixed 6-s control | `1089-134686-0003` | 1089 | `5` | `5`: 0.740 | 0.740 | 0.000 | 0.000 | 1.940 | `5` |
| Soniox realtime — fixed 6-s control | `1995-1826-0004` | 1995 | `2` | `2`: 0.780 | 0.780 | 0.000 | 0.000 | 2.255 | `2` |
| Soniox realtime — fixed 6-s control | `1188-133604-0006` | 1188 | `1` | `1`: 0.600 | 0.600 | 0.000 | 0.000 | 1.800 | `1` |
| Soniox realtime — fixed 6-s control | `2094-142345-0007` | 2094 | `2` | `2`: 0.595 | 0.595 | 0.000 | 0.000 | 2.105 | `2` |
| Soniox realtime — fixed 6-s control | `121-121726-0002` | 121 | `4` | `3`: 0.120, `4`: 0.405 | 0.525 | 0.000 | 0.000 | 3.885 | `3`, `4` |
| Soniox realtime — fixed 6-s control | `260-123286-0004` | 260 | `5` | `1`: 0.060, `5`: 0.600 | 0.660 | 0.000 | 0.000 | 2.805 | `1`, `5` |
| Soniox realtime — app-segmentation equivalent | `1089-134686-0001` | 1089 | `1` | `1`: 0.960 | 0.960 | 0.000 | 0.000 | 2.315 | `1` |
| Soniox realtime — app-segmentation equivalent | `1995-1826-0003` | 1995 | `2` | `2`: 1.020 | 1.020 | 0.000 | 0.000 | 2.070 | `2` |
| Soniox realtime — app-segmentation equivalent | `1188-133604-0001` | 1188 | `1` | `1`: 2.160 | 2.160 | 0.000 | 0.000 | 6.880 | `1` |
| Soniox realtime — app-segmentation equivalent | `2094-142345-0004` | 2094 | `2` | `2`: 0.720 | 0.720 | 0.000 | 0.000 | 1.920 | `2` |
| Soniox realtime — app-segmentation equivalent | `121-121726-0001` | 121 | `3` | `3`: 0.906 | 0.906 | 0.000 | 0.000 | 5.019 | `3` |
| Soniox realtime — app-segmentation equivalent | `260-123286-0001` | 260 | `1` | `1`: 0.600 | 0.600 | 0.000 | 0.000 | 2.470 | `1` |
| Soniox realtime — app-segmentation equivalent | `1089-134686-0003` | 1089 | `4` | `4`: 0.720 | 0.720 | 0.000 | 0.000 | 1.960 | `4` |
| Soniox realtime — app-segmentation equivalent | `1995-1826-0004` | 1995 | `2` | `2`: 0.720 | 0.720 | 0.000 | 0.000 | 2.315 | `2` |
| Soniox realtime — app-segmentation equivalent | `1188-133604-0006` | 1188 | `1` | `1`: 0.600, `2`: 0.120 | 0.720 | 0.000 | 0.000 | 1.680 | `1`, `2` |
| Soniox realtime — app-segmentation equivalent | `2094-142345-0007` | 2094 | `2` | `1`: 0.060, `2`: 0.540 | 0.600 | 0.000 | 0.000 | 2.100 | `1`, `2` |
| Soniox realtime — app-segmentation equivalent | `121-121726-0002` | 121 | `3` | `3`: 0.480 | 0.480 | 0.000 | 0.000 | 3.930 | `3` |
| Soniox realtime — app-segmentation equivalent | `260-123286-0004` | 260 | `4` | `1`: 0.300, `3`: 0.060, `4`: 0.360 | 0.720 | 0.000 | 0.000 | 2.745 | `1`, `3`, `4` |
| Soniox async full-file | `1089-134686-0001` | 1089 | `1` | `1`: 1.020 | 1.020 | 0.000 | 0.000 | 2.255 | `1` |
| Soniox async full-file | `1995-1826-0003` | 1995 | `2` | `2`: 0.960 | 0.960 | 0.000 | 0.000 | 2.130 | `2` |
| Soniox async full-file | `1188-133604-0001` | 1188 | `1` | `1`: 2.100 | 2.100 | 0.000 | 0.000 | 6.940 | `1` |
| Soniox async full-file | `2094-142345-0004` | 2094 | `2` | `2`: 0.720 | 0.720 | 0.000 | 0.000 | 1.920 | `2` |
| Soniox async full-file | `121-121726-0001` | 121 | `3` | `3`: 1.080 | 1.080 | 0.000 | 0.000 | 4.845 | `3` |
| Soniox async full-file | `260-123286-0001` | 260 | `1` | `1`: 0.600 | 0.600 | 0.000 | 0.000 | 2.470 | `1` |
| Soniox async full-file | `1089-134686-0003` | 1089 | `4` | `4`: 0.840 | 0.840 | 0.000 | 0.000 | 1.840 | `4` |
| Soniox async full-file | `1995-1826-0004` | 1995 | `2` | `2`: 0.840 | 0.840 | 0.000 | 0.000 | 2.195 | `2` |
| Soniox async full-file | `1188-133604-0006` | 1188 | `1` | `1`: 0.720 | 0.720 | 0.000 | 0.000 | 1.680 | `1` |
| Soniox async full-file | `2094-142345-0007` | 2094 | `2` | `2`: 0.660 | 0.660 | 0.000 | 0.000 | 2.040 | `2` |
| Soniox async full-file | `121-121726-0002` | 121 | `3` | `3`: 0.600 | 0.600 | 0.000 | 0.000 | 3.810 | `3` |
| Soniox async full-file | `260-123286-0004` | 260 | `1` | `1`: 0.780 | 0.780 | 0.000 | 0.000 | 2.685 | `1` |
| Nemotron-3-Diarization — offline-style | `1089-134686-0001` | 1089 | `0` | `0`: 2.540 | 2.540 | 0.000 | 0.000 | 0.735 | `0` |
| Nemotron-3-Diarization — offline-style | `1995-1826-0003` | 1995 | `1` | `1`: 2.730 | 2.730 | 0.000 | 0.000 | 0.360 | `1` |
| Nemotron-3-Diarization — offline-style | `1188-133604-0001` | 1188 | `2` | `2`: 6.260 | 6.260 | 0.000 | 0.000 | 2.780 | `2` |
| Nemotron-3-Diarization — offline-style | `2094-142345-0004` | 2094 | `3` | `3`: 1.620 | 1.620 | 0.000 | 0.000 | 1.020 | `3` |
| Nemotron-3-Diarization — offline-style | `121-121726-0001` | 121 | `4` | `4`: 3.980 | 3.980 | 0.000 | 0.000 | 1.945 | `4` |
| Nemotron-3-Diarization — offline-style | `260-123286-0001` | 260 | `5` | `5`: 2.280 | 2.280 | 0.000 | 0.000 | 0.790 | `5` |
| Nemotron-3-Diarization — offline-style | `1089-134686-0003` | 1089 | `0` | `0`: 2.080 | 2.080 | 0.000 | 0.000 | 0.600 | `0` |
| Nemotron-3-Diarization — offline-style | `1995-1826-0004` | 1995 | `1` | `1`: 2.320 | 2.320 | 0.000 | 0.000 | 0.715 | `1` |
| Nemotron-3-Diarization — offline-style | `1188-133604-0006` | 1188 | `2` | `2`: 1.480 | 1.480 | 0.000 | 0.000 | 0.920 | `2` |
| Nemotron-3-Diarization — offline-style | `2094-142345-0007` | 2094 | `3` | `3`: 1.820 | 1.820 | 0.000 | 0.000 | 0.880 | `3` |
| Nemotron-3-Diarization — offline-style | `121-121726-0002` | 121 | `4` | `4`: 3.160 | 3.160 | 0.000 | 0.000 | 1.250 | `4` |
| Nemotron-3-Diarization — offline-style | `260-123286-0004` | 260 | `5` | `5`: 2.570 | 2.570 | 0.000 | 0.000 | 0.895 | `5` |
| Nemotron-3-Diarization — low latency | `1089-134686-0001` | 1089 | `0` | `0`: 2.570 | 2.570 | 0.000 | 0.000 | 0.705 | `0` |
| Nemotron-3-Diarization — low latency | `1995-1826-0003` | 1995 | `1` | `1`: 2.730 | 2.730 | 0.000 | 0.000 | 0.360 | `1` |
| Nemotron-3-Diarization — low latency | `1188-133604-0001` | 1188 | `2` | `2`: 6.250 | 6.250 | 0.000 | 0.000 | 2.790 | `2` |
| Nemotron-3-Diarization — low latency | `2094-142345-0004` | 2094 | `3` | `3`: 1.630 | 1.630 | 0.000 | 0.000 | 1.010 | `3` |
| Nemotron-3-Diarization — low latency | `121-121726-0001` | 121 | `4` | `4`: 3.980 | 3.980 | 0.000 | 0.000 | 1.945 | `4` |
| Nemotron-3-Diarization — low latency | `260-123286-0001` | 260 | `5` | `5`: 2.270 | 2.270 | 0.000 | 0.000 | 0.800 | `5` |
| Nemotron-3-Diarization — low latency | `1089-134686-0003` | 1089 | `0` | `0`: 2.080 | 2.080 | 0.000 | 0.000 | 0.600 | `0` |
| Nemotron-3-Diarization — low latency | `1995-1826-0004` | 1995 | `1` | `1`: 2.320 | 2.320 | 0.000 | 0.000 | 0.715 | `1` |
| Nemotron-3-Diarization — low latency | `1188-133604-0006` | 1188 | `2` | `2`: 1.480 | 1.480 | 0.000 | 0.000 | 0.920 | `2` |
| Nemotron-3-Diarization — low latency | `2094-142345-0007` | 2094 | `3` | `3`: 1.820 | 1.820 | 0.000 | 0.000 | 0.880 | `3` |
| Nemotron-3-Diarization — low latency | `121-121726-0002` | 121 | `4` | `4`: 3.090 | 3.090 | 0.000 | 0.000 | 1.320 | `4` |
| Nemotron-3-Diarization — low latency | `260-123286-0004` | 260 | `5` | `5`: 2.560 | 2.560 | 0.000 | 0.000 | 0.905 | `5` |
| Nemotron-3-Diarization — very low latency | `1089-134686-0001` | 1089 | `0` | `0`: 2.560 | 2.560 | 0.000 | 0.000 | 0.715 | `0` |
| Nemotron-3-Diarization — very low latency | `1995-1826-0003` | 1995 | `1` | `1`: 2.730 | 2.730 | 0.000 | 0.000 | 0.360 | `1` |
| Nemotron-3-Diarization — very low latency | `1188-133604-0001` | 1188 | `2` | `2`: 6.260 | 6.260 | 0.000 | 0.000 | 2.780 | `2` |
| Nemotron-3-Diarization — very low latency | `2094-142345-0004` | 2094 | `3` | `3`: 1.620 | 1.620 | 0.000 | 0.000 | 1.020 | `3` |
| Nemotron-3-Diarization — very low latency | `121-121726-0001` | 121 | `4` | `4`: 3.890 | 3.890 | 0.000 | 0.000 | 2.035 | `4` |
| Nemotron-3-Diarization — very low latency | `260-123286-0001` | 260 | `5` | `5`: 2.270 | 2.270 | 0.000 | 0.000 | 0.800 | `5` |
| Nemotron-3-Diarization — very low latency | `1089-134686-0003` | 1089 | `0` | `0`: 2.080 | 2.080 | 0.000 | 0.000 | 0.600 | `0` |
| Nemotron-3-Diarization — very low latency | `1995-1826-0004` | 1995 | `1` | `1`: 2.320 | 2.320 | 0.000 | 0.000 | 0.715 | `1` |
| Nemotron-3-Diarization — very low latency | `1188-133604-0006` | 1188 | `2` | `2`: 1.490 | 1.490 | 0.000 | 0.000 | 0.910 | `2` |
| Nemotron-3-Diarization — very low latency | `2094-142345-0007` | 2094 | `3` | `3`: 1.810 | 1.810 | 0.000 | 0.000 | 0.890 | `3` |
| Nemotron-3-Diarization — very low latency | `121-121726-0002` | 121 | `4` | `4`: 3.160 | 3.160 | 0.000 | 0.000 | 1.250 | `4` |
| Nemotron-3-Diarization — very low latency | `260-123286-0004` | 260 | `5` | `5`: 2.560 | 2.560 | 0.000 | 0.000 | 0.905 | `5` |
| Nemotron-3-Diarization — ultra low latency | `1089-134686-0001` | 1089 | `0` | `0`: 2.600 | 2.600 | 0.000 | 0.000 | 0.675 | `0` |
| Nemotron-3-Diarization — ultra low latency | `1995-1826-0003` | 1995 | `1` | `1`: 2.740 | 2.740 | 0.000 | 0.000 | 0.350 | `1` |
| Nemotron-3-Diarization — ultra low latency | `1188-133604-0001` | 1188 | `2` | `2`: 6.240 | 6.240 | 0.000 | 0.000 | 2.800 | `2` |
| Nemotron-3-Diarization — ultra low latency | `2094-142345-0004` | 2094 | `3` | `3`: 1.610 | 1.610 | 0.000 | 0.000 | 1.030 | `3` |
| Nemotron-3-Diarization — ultra low latency | `121-121726-0001` | 121 | `4` | `4`: 3.890 | 3.890 | 0.000 | 0.000 | 2.035 | `4` |
| Nemotron-3-Diarization — ultra low latency | `260-123286-0001` | 260 | `5` | `5`: 2.260 | 2.260 | 0.000 | 0.000 | 0.810 | `5` |
| Nemotron-3-Diarization — ultra low latency | `1089-134686-0003` | 1089 | `0` | `0`: 2.030 | 2.030 | 0.000 | 0.000 | 0.650 | `0` |
| Nemotron-3-Diarization — ultra low latency | `1995-1826-0004` | 1995 | `1` | `1`: 2.320 | 2.320 | 0.000 | 0.000 | 0.715 | `1` |
| Nemotron-3-Diarization — ultra low latency | `1188-133604-0006` | 1188 | `2` | `2`: 1.490 | 1.490 | 0.000 | 0.000 | 0.910 | `2` |
| Nemotron-3-Diarization — ultra low latency | `2094-142345-0007` | 2094 | `3` | `3`: 1.820 | 1.820 | 0.000 | 0.000 | 0.880 | `3` |
| Nemotron-3-Diarization — ultra low latency | `121-121726-0002` | 121 | `4` | `4`: 2.880 | 2.880 | 0.000 | 0.000 | 1.530 | `4` |
| Nemotron-3-Diarization — ultra low latency | `260-123286-0004` | 260 | `5` | `5`: 2.530 | 2.530 | 0.000 | 0.000 | 0.935 | `5` |
| Qwen 3.8 LiveTranslate realtime | `1089-134686-0001` | 1089 | `1` | `1`: 3.155 | 3.155 | 0.000 | 0.000 | 0.120 | `1` |
| Qwen 3.8 LiveTranslate realtime | `1995-1826-0003` | 1995 | `2` | `1`: 0.145, `2`: 2.945 | 3.090 | 0.000 | 0.000 | 0.000 | `1`, `2` |
| Qwen 3.8 LiveTranslate realtime | `1188-133604-0001` | 1188 | `3` | `2`: 0.395, `3`: 8.485 | 8.880 | 0.000 | 0.000 | 0.160 | `2`, `3` |
| Qwen 3.8 LiveTranslate realtime | `2094-142345-0004` | 2094 | `4` | `3`: 0.135, `4`: 2.305 | 2.440 | 0.000 | 0.000 | 0.200 | `3`, `4` |
| Qwen 3.8 LiveTranslate realtime | `121-121726-0001` | 121 | `5` | `4`: 0.195, `5`: 5.330 | 5.525 | 0.000 | 0.000 | 0.400 | `4`, `5` |
| Qwen 3.8 LiveTranslate realtime | `260-123286-0001` | 260 | `6` | `5`: 0.330, `6`: 2.740 | 3.070 | 0.000 | 0.000 | 0.000 | `5`, `6` |
| Qwen 3.8 LiveTranslate realtime | `1089-134686-0003` | 1089 | `7` | `6`: 0.200, `7`: 2.440 | 2.640 | 0.000 | 0.000 | 0.040 | `6`, `7` |
| Qwen 3.8 LiveTranslate realtime | `1995-1826-0004` | 1995 | `8` | `7`: 0.220, `8`: 2.815 | 3.035 | 0.000 | 0.000 | 0.000 | `7`, `8` |
| Qwen 3.8 LiveTranslate realtime | `1188-133604-0006` | 1188 | `9` | `8`: 0.125, `9`: 1.875 | 2.000 | 0.000 | 0.000 | 0.400 | `8`, `9` |
| Qwen 3.8 LiveTranslate realtime | `2094-142345-0007` | 2094 | `10` | `10`: 2.395, `9`: 0.185 | 2.580 | 0.000 | 0.000 | 0.120 | `10`, `9` |
| Qwen 3.8 LiveTranslate realtime | `121-121726-0002` | 121 | `11` | `10`: 0.185, `11`: 4.225 | 4.410 | 0.000 | 0.000 | 0.000 | `10`, `11` |
| Qwen 3.8 LiveTranslate realtime | `260-123286-0004` | 260 | `12` | `11`: 0.155, `12`: 2.640 | 2.795 | 0.000 | 0.000 | 0.670 | `11`, `12` |

## Secondary fixed-173-anchor diagnostic (not ranked)

The saved common anchors are the 173 continuous-Soniox lexical-token midpoints, validated against the previous continuous-arm eligibility/confusion counts. This point-span analysis is retained for diagnostics only: exact token-interval coverage is not a comparable speaker-accuracy measure across token and segment outputs. In particular, the low-coverage forced/app-segmented Soniox pair outcomes below are not accuracy percentages. The raw assignments remain under `strict_anchor_diagnostic_not_ranked` in `comparison.json`.

| Run | Identified / missing / ambiguous anchors | Same-reference ID matches / splits / unresolved | Different-reference distinct IDs / merges / unresolved |
| --- | --- | --- | --- |
| Soniox realtime — continuous | 173 / 0 / 0 of 173 | 2216 / 401 / 0 | 10209 / 2052 / 0 |
| Soniox realtime — fixed 6-s control | 74 / 99 / 0 of 173 | 430 / 87 / 2100 | 1758 / 426 / 10077 |
| Soniox realtime — app-segmentation equivalent | 57 / 116 / 0 of 173 | 252 / 24 / 2341 | 1010 / 310 / 10941 |
| Soniox async full-file | 147 / 26 / 0 of 173 | 1695 / 180 / 742 | 6812 / 2044 / 3405 |
| Nemotron-3-Diarization — offline-style | 171 / 2 / 0 of 173 | 2552 / 0 / 65 | 11983 / 0 / 278 |
| Nemotron-3-Diarization — low latency | 171 / 2 / 0 of 173 | 2552 / 0 / 65 | 11983 / 0 / 278 |
| Nemotron-3-Diarization — very low latency | 171 / 2 / 0 of 173 | 2552 / 0 / 65 | 11983 / 0 / 278 |
| Nemotron-3-Diarization — ultra low latency | 171 / 2 / 0 of 173 | 2552 / 0 / 65 | 11983 / 0 / 278 |
| Qwen 3.8 LiveTranslate realtime | 172 / 1 / 0 of 173 | 1384 / 1188 / 45 | 12116 / 18 / 127 |

The Nemotron rows retain the 171/173 identified anchors and zero identified-pair splits/merges across presets; the continuous Soniox row covers its own 173-anchor locations. The other Soniox strict token-span rows are support diagnostics only. The previous Soniox own-token pair proxies (including their own eligible-token denominators) remain in `../soniox_diarization/report.md` and are a separate metric, not a column in the clip recurrence table.

The earlier strict-span quality ranking was withdrawn: 107 of the 116 app-segmented anchor misses still had the baseline whole word in that source clip's transcript. Exact word-token interval support differs from utterance-level support; a hole at another run's token midpoint is not evidence of a wrong speaker.

## Nemotron preset latency

| Preset | Nominal input-buffer delay (s) | Measured full-clip CPU processing time after model load (s) |
| --- | ---: | ---: |
| Nemotron-3-Diarization — offline-style | 30.400 | 1.516 |
| Nemotron-3-Diarization — low latency | 1.040 | 9.970 |
| Nemotron-3-Diarization — very low latency | 0.640 | 15.757 |
| Nemotron-3-Diarization — ultra low latency | 0.320 | 31.749 |

Nemotron nominal values are configured input-buffer delays, not measured live end-to-end latency. CPU processing time is measured wall-clock preprocessing, inference and segment conversion for the whole fixture, after model load, without realtime pacing. Soniox own-token proxies and Qwen session details remain in their respective experiment records. Qwen's primary clip result above uses its completed, hash-matched normalized native intervals.

## Reproduction and limits

The evaluator makes no inference/API calls. Clip-level support durations are not missed-speech or DER estimates: the models expose different native span granularities, and silence/uncovered time is reported rather than scored as an error. Dominant IDs intentionally hide within-clip switching; the observed-ID lists and `clips_with_multiple_native_ids` count expose that limitation.

This is one clean read-English audiobook concatenation, not a representative benchmark of multilingual or noisy VRChat speech. No production code, settings, or user-visible behavior was changed.

Qwen's [speaker_id contract](https://help.aliyun.com/en/model-studio/live-translator-server-events) identifies speakers when speaker_detection is enabled but does not explicitly guarantee persistent IDs for returning people across turns. The observed 0/6 recurrence result fails this application's persistent-person-label requirement on this fixture; it is not evidence of violating an explicit vendor stability guarantee.

Run the offline comparison from the repository root:

```powershell
C:/Python314/python.exe experiments/diarization_comparison/evaluate.py
```

Observed evaluator result: phase `complete`, 9 completed normalized model runs, 0 not evaluated, all scored artifacts matched the fixture PCM hash. The fixed-anchor denominator remains 173; its point assignments are retained only as a secondary diagnostic.
