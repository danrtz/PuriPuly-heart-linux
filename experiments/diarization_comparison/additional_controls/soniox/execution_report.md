# Soniox additional controls: execution record

Eight real Soniox calls completed, one fresh realtime WebSocket for each of the six realtime arms and one full-file asynchronous upload/job for each case. Source fixtures were read without modification; no Qwen run, product/config change, or Git mutation was performed. Outputs are `repeated/{continuous,forced,segmented,async_full_file}.json` and `distinct/{continuous,forced,segmented,async_full_file}.json` beside this report. Every successful result has `completed: true`, native final tokens, timeline, source PCM SHA-256, model/config, sent seconds, and lifecycle evidence. Async results separately record actual deletion outcomes in `cleanup`.

## Commands and observed outcomes

From repository root, each of these commands was run once with `C:/Users/salee/Documents/dev/puripuly_heart/.venv/Scripts/python.exe` in place of `<python>`:

| Command | Sent audio s | Final tokens | Finalization / cleanup |
| --- | ---: | ---: | --- |
| `<python> experiments/diarization_comparison/additional_controls/soniox/run.py repeated continuous` | 22.280 | 94 | 1/1 `<fin>`, `finished=true` |
| `<python> experiments/diarization_comparison/additional_controls/soniox/run.py repeated forced` | 22.280 | 96 | 4/4 `<fin>`, `finished=true` |
| `<python> experiments/diarization_comparison/additional_controls/soniox/run.py repeated segmented` | 20.336 | 95 | 6/6 `<fin>`, `finished=true` |
| `<python> experiments/diarization_comparison/additional_controls/soniox/run.py repeated async_full_file` | 22.280 | 100 | Job completed; transcription and file deleted; 7 HTTP requests |
| `<python> experiments/diarization_comparison/additional_controls/soniox/run.py distinct continuous` | 14.080 | 63 | 1/1 `<fin>`, `finished=true` |
| `<python> experiments/diarization_comparison/additional_controls/soniox/run.py distinct forced` | 14.080 | 66 | 3/3 `<fin>`, `finished=true` |
| `<python> experiments/diarization_comparison/additional_controls/soniox/run.py distinct segmented` | 13.416 | 65 | 4/4 `<fin>`, `finished=true` |
| `<python> experiments/diarization_comparison/additional_controls/soniox/run.py distinct async_full_file` | 14.080 | 65 | Job completed; transcription and file deleted; 7 HTTP requests |

Total supplied input audio: **142.832 seconds** across six WebSocket sessions, two uploaded full-file WAVs and two transcription jobs. All 19 client `finalize` markers received `<fin>`; all six sessions received `finished=true`. Async: 14 REST requests including four successful deletion requests, no unresolved file/job, no provider errors. All eight saved results report two native speaker IDs each; native ID values are scoped to each independent request, so their equality across requests has no cross-run identity meaning. The Director-owned common evaluator handles source-clip dominance and pairwise scoring.

## Fixture and method

Shared immutable manifest `../fixtures.json`: repeated = 22.280 s, PCM SHA-256 `a498e5872ad0edb2ebe3fe38d811b09a824e43c6080c1ec5b74870008520c650`; distinct = 14.080 s, PCM SHA-256 `d569edbca911b0db8e5b9239efe3fa5057b16e0763fc1d442a37dd6b303f0fa6`. The runner checks decoded 16-kHz mono PCM16 against fixture length, duration, and hash before any API call. It does not send source-turn labels, speaker names, or known person count to Soniox. All WAVs are the public audio fixture, not user/private recordings.

Realtime uses prior `probe.py` `live_arm()` and `regions()`: `stt-rt-v5`, 16-kHz mono PCM16, `language_hints=['en']`, diarization on, endpoint detection and language identification off, no context, ~50-ms realtime-paced writes. Continuous has one EOF finalize, forced has exactly six-second boundaries plus EOF, segmented uses prior `app_segments.py` actual Silero VAD, segment ledger, ListenDeliveryController, and Smart Turn helper with its same onset/hangover/pre-roll/settings, sending captured source pieces then per-segment finalize in one session. Repeated segmented emitted six `delivery_pause` segments, zero padding, Smart Turn ready with four inferences, 128 dropped EOF samples; distinct emitted four `delivery_pause` segments, zero padding, ready with four inferences, zero dropped EOF samples. The source-piece maps and reason/padding/EOF diagnostics reside in each segmented JSON. Segmentation is a source replay of application components, **not** a claim that the desktop capture pipeline ran. Async uses `stt-async-v5`, diarization on, language hint English, one uploaded full-file WAV per case, request cleanup after completed job, and identity source/provider timeline.

Runtime: Windows x64, Python 3.14.7 from the main repository venv; `websockets` 16.1.1, `requests` 2.32.5, `numpy` 2.5.1, `onnxruntime` 1.28.0. The existing local keyring credential was available; secrets were neither printed nor saved. This small read-English constructed-turn probe does not measure target-domain VRChat/Mandarin/Japanese diarization, overlap, desktop capture, latency distribution, or actual billed seconds.

Verification: each of eight live commands printed its successful completion and expected finalize/cleanup evidence. A post-run fact command loaded all eight JSONs and found 8/8 `completed=true`, 142.832 sent seconds, six WebSocket sessions, 19 `<fin>`, 14 async HTTP requests, and 644 saved final tokens. No permanent test was added for this validation-only experiment.
