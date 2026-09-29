# Soniox diarization live diagnosis

## Decision

The app does not restrict Soniox to three or four raw speakers. On this controlled six-speaker public audio, **the unsegmented direct Soniox realtime WebSocket itself returned five raw speaker IDs for six reference identities**, including repeated speaker IDs shared by distinct reference speakers and a changed ID for the same reference speaker on a later clip. The app-like VAD/manual-finalize wire input returned four IDs. The full-file Soniox async model also returned only four IDs; this particular fixture's merges cannot be attributed solely to app segmentation or realtime finalization. The four-color presentation palette is a separate app-side limit, not a raw-ID limit.

This is a causal/integration probe, **not a representative VRChat benchmark, a DER estimate, or evidence about Mandarin/Japanese accuracy**. These are clean, read English LibriSpeech recordings concatenated into artificial interleaved turns, not natural multilingual conversations. No product code was modified.

## Reproduction and fixture

Run from repository root using the installed main-repository environment:

```powershell
C:/Users/salee/Documents/dev/puripuly_heart/.venv/Scripts/python.exe experiments/soniox_diarization/probe.py --arm all
C:/Users/salee/Documents/dev/puripuly_heart/.venv/Scripts/python.exe experiments/soniox_diarization/async_probe.py
```

Python requires `websockets`, `numpy`, `onnxruntime`, `keyring`, `requests` and `ffmpeg` on PATH. The scripts use `SONIOX_API_KEY` or locally retrieve `puripuly-heart` / `soniox_api_key` from Windows keyring. The key is never printed or saved. `fixture.json` lists all 12 direct public FLAC URLs by relative path, six original LibriSpeech test-clean speaker IDs, two different utterances per ID, and order A-D-B-E-C-F-A-D-B-E-C-F. Each utterance is followed by 0.500 seconds of appended digital silence, identical across all arms. The decoded 16-kHz mono fixture is **51.730 seconds**, SHA-256 `2eb1ab143c2a7dbaa7448c31b44dd8c517b85042e769f2da5d2ddaec14028762`. The precise decoded-sample intervals and each downloaded FLAC SHA-256/URL are in the output JSON. Sources are cached under `clips/` and are public-only.

Provenance: [upstream LibriSpeech test-clean](https://www.openslr.org/12/) is human-read LibriVox audio licensed CC BY 4.0, described as 16-kHz audiobook speech. The [mirror card](https://huggingface.co/datasets/JinchuanTian/librispeech-test-clean-plain-tts) explicitly says these are **original ground-truth LibriSpeech audio and transcripts**, despite `plain-tts` in the derivative dataset's name; its [JSONL metadata](https://huggingface.co/datasets/JinchuanTian/librispeech-test-clean-plain-tts/resolve/main/dialogues.jsonl) identifies each `utt_id`/`speaker_id`. The concatenation and inserted silences are our modifications. Public audio alone was sent to Soniox. No private logs/audio/settings or credentials were uploaded.

## Arms and raw evidence

All three realtime arms used the same `stt-rt-v5` WebSocket endpoint, source samples, 16-kHz mono `pcm_s16le`, English hint `['en']`, no context, `enable_endpoint_detection=false`, `enable_language_identification=false`, and `enable_speaker_diarization=true`. `probe.py` sends 50-ms frames paced at audio duration and records **raw final token text, native `speaker`, token `start_ms`/`end_ms`, and request ID** before any app mapping. Tokens before each `<fin>` remain included. One WebSocket session per arm; no intentional reconnect.

| Arm | Wire input and `<fin>` markers | Final lexical tokens mapped to known speakers | Raw IDs | Same-reference split token pairs | Different-reference merged token pairs |
| --- | --- | ---: | ---: | ---: | ---: |
| continuous | 51.730 s unchanged PCM; one final `finalize` after all audio | 173 | 5 | 401/2617 (15.3%) | 2052/12261 (16.7%) |
| forced | Exact same 51.730 s PCM, no removed audio or padding; finalize at 6,12,...,48 s and EOF, nine `<fin>` | 170 | 5 | 378/2531 (14.9%) | 2075/11834 (17.5%) |
| segmented | App Silero VAD/ListenDeliveryController-produced source spans, with same app selective padding rule; 47.940 s PCM sent, 15 `<fin>` | 167 | 4 | 383/2504 (15.3%) | 2334/11357 (20.6%) |
| async full-file | Same 51.730 s WAV uploaded, `stt-async-v5`, full-file native final token evidence | 173 | 4 | 195/2610 (7.5%) | 2620/12268 (21.4%) |

The metric denominator is **unordered pairs of identified, timed, alphanumeric final tokens whose midpoint lands inside exactly one known speaker interval**. For a pair from the *same* reference speaker, a split means distinct raw model IDs. For a pair from *different* reference speakers, a merge means the same raw model ID. Punctuation-only, untimed, null-speaker, silence, or unlabeled/ambiguous tokens are excluded; exact exclusions are in each result JSON. These pair fractions are correlated token-count-weighted proxies, not duration-weighted diarization error rate or independent confidence intervals. Tokenization and eligible denominators differ by arm; repeated content from VAD overlap can count twice. Raw speaker labels are arbitrary and must be matched by confusion, not compared numerically across independent sessions.

The saved `continuous.json`, `forced.json`, `segmented.json`, and `async_full_file.json` contain complete final native token evidence, confusion rows, timestamp-to-original-audio mappings, and provenance. Examples of reference-vendor confusion in **continuous**: true speaker `1995` and distinct `2094` both emitted ID `2` throughout their measured tokens (`29` and `21`); `1188` emitted `1` for all `46` tokens, while distinct `1089` emitted `1` for 15 tokens on its first clip and `5` for 13 on its second; `260` also emitted `1` for 10 tokens then `5` for 11. The segmented run kept true `1995`/`2094` both on ID `2` (`27`/`20` tokens), and `1089` switched from `1` to `4` across its clips. The async full-file arm also merged `1995`/`2094` as `2` and `1188`/`260` as `1`, while splitting `1089` between `1` and `4`. These are raw Soniox responses, before UI colors or transcript-run normalization.

In continuous realtime, **168 lexical-or-punctuation final tokens were already finalized before its sole `<fin>`** (181 total final non-marker tokens). The forced/segmented streams had no final tokens before their first `<fin>`. Thus “continuous” means no client-forced intermediate finalization, *not* that every token waits for the full recording. The forced arm's almost identical confusion does not disprove Soniox's general finalization warning: this one clean fixture with many naturally finalized tokens has limited statistical power. The async arm improves the same-speaker split proxy but worsens the merge proxy here; it does **not** establish that async resolves this fixture's six identities.

### Per-source-clip raw speaker IDs

Each cell is `dominant native ID / within-clip changes`: changes count transitions between consecutive **eligible alphanumeric final tokens** mapped by midpoint into that original source clip; the denominator is that clip's eligible token count, available from `tokens`/`timeline` in the output JSON. The four arms' arbitrary ID namespaces must not be compared across sessions.

| True speaker / LibriSpeech clip | Continuous | Forced | App-segmented | Async |
| --- | ---: | ---: | ---: | ---: |
| 1089 / 0001 | 1 / 0 | 1 / 0 | 1 / 0 | 1 / 0 |
| 1995 / 0003 | 2 / 0 | 2 / 0 | 2 / 0 | 2 / 0 |
| 1188 / 0001 | 1 / 0 | 1 / 0 | 1 / 0 | 1 / 0 |
| 2094 / 0004 | 2 / 0 | 2 / 0 | 2 / 0 | 2 / 0 |
| 121 / 0001 | 4 / 1 | 4 / 1 | 3 / 0 | 3 / 0 |
| 260 / 0001 | 1 / 0 | 1 / 0 | 1 / 0 | 1 / 0 |
| 1089 / 0003 | 5 / 0 | 5 / 0 | 4 / 0 | 4 / 0 |
| 1995 / 0004 | 2 / 0 | 2 / 0 | 2 / 0 | 2 / 0 |
| 1188 / 0006 | 1 / 0 | 1 / 0 | 1 / 1 | 1 / 0 |
| 2094 / 0007 | 2 / 0 | 2 / 0 | 2 / 0 | 2 / 0 |
| 121 / 0002 | 4 / 2 | 4 / 2 | 3 / 0 | 3 / 0 |
| 260 / 0004 | 5 / 0 | 5 / 1 | 4 / 2 | 1 / 0 |

Continuous and forced changed `121`'s raw ID **inside** two source clips (`121/0001` has 2 tokens under ID `3` and 16/15 under `4`; `121/0002` has 2 under `3` and 8/7 under `4`). App-segmented changed IDs within `1188/0006` and `260/0004`. The strong `1089` ID `1→5` recurrence in continuous/forced and `1→4` in segmented/async occurred **after five intervening clips by other people**, not across adjacent utterances by the same human. This fixture does **not** reproduce or measure the reported same-human adjacent-utterance switching; it establishes within-clip switching in some arms, and nonadjacent same-human recurrence failures in all arms.

### How closely segmented resembles production

`app_segments.py` replays the same decoded samples in 512-sample chunks through the actual bundled Silero ONNX VAD (`create_peer_vad_gating`), actual `PeerAudioSegmentLedger` and `ListenDeliveryController`, and actual bundled Smart Turn inference owner, at ~real-time pacing with source-timed capture spans. It uses read-only saved peer VAD values (onset 0.3, hangover 500 ms, pre-roll 500 ms) and source mode/manual language `zh-CN`, matching the saved peer delivery profile while testing English audio under an English Soniox language hint. This is **not a full desktop capture/backend integration**: it bypasses the app's capture device/resampler/queue and writes the controller's source spans directly to the equivalent Soniox WebSocket config and `finalize` control; frame pacing is 50 ms rather than app payload chunk sizes, and it sends the fixture's original PCM samples rather than the app's float32 re-quantization (at most a PCM quantization step). It waits for `<fin>` before subsequent segment audio, as scoped engine does for a non-overlap session. Therefore assign differences jointly to VAD-filtered audio, changed silence/context, selective padding, and forced finalization, **not to finalization alone**. The forced arm isolates finalization with identical acoustic bytes.

The saved settings currently select `qwen_audio` for peer STT, not Soniox; this Soniox peer-wire contrast diagnoses what Soniox receives when selected and cannot be attributed to the currently selected peer provider. Saved self STT is `soniox` / `stt-rt-v5`. The English hint deliberately matches the English diagnostic fixture rather than the saved peer `zh-CN`/`ja` expected-language selection.

Observed actual VAD replay: 15 segments, all `delivery_pause` (no hard 6-s deadline on this material), Smart Turn ready and 18 inferences, one segment received 200 ms selective app padding after 4.000 s content, 14 received none, and 288 final tail samples were not admitted after the last speech segment. `segments.json` contains exact captured source spans, reasons, trailing-silence observations, and padding. Due to real-time Smart Turn scheduling, two preprocessing replays differed by one 32-ms chunk on one segment; `segmented.json` holds the live run's final sent audio and raw token evidence. Actual pause seals ranged ~256–800 ms observed silence, so the persisted Soniox setting `trailing_silence_ms=100` does **not** itself force a 100-ms finalization delay: scoped `seal_turn` ignores that argument, sends VAD tail already admitted, and adds selective 200 ms for 4–7 s pause segments or hard deadlines only.

The 6-second mechanism is a **hard maximum from segment opening**, not six-second fixed slicing: `ListenDeliveryController.HARD_LIMIT_S=6` seals with `delivery_deadline` and `seal_active_for_rollover`, and `create_peer_vad_gating` carries up to 300 ms pre-roll into the next segment. Earlier pauses may seal at 4 s/192 ms or 5 s/128 ms if the age thresholds apply; normally Smart Turn probes at 224 ms, decides around 512 ms, and falls back to 800 ms if incomplete. The forced arm's fixed 6-second boundaries are therefore an isolated control, not claimed to be full app behavior.

## Implementation pathway and interpretation

- `core/runtime/audio_vad_loop.py:231-245,325-330,369-412` dispatches peer source through external delivery segmentation. `core/audio/listen_delivery.py:38-48,151-187,337-366` defines pause/deadline policy. `core/vad/gating.py:474-509,549-575` defines rollover and 300-ms context. `core/stt/scoped_engine.py:517-660,709-747` writes pre-roll and VAD chunks, seals turns, awaits terminal. `providers/stt/soniox.py:308-358,360-404,992-1058` sends one config per socket with endpoint detection off, continues a session across manual finalize, adds only selective padding, and does **not** use configured trailing_silence_ms to generate that much zero audio.
- `providers/stt/soniox.py:522-583,588-677,698-744` reads final tokens' native `speaker` as a string and groups adjacent equal IDs into final speaker runs with per-session UUID scope; no truncation to four raw IDs. `core/stt/scoped_engine.py:794-809,859-881,1215-1240` reuses a same-scope healthy session, but retires on epoch failure/config change/age ceiling, so reconnect resets vendor context and speaker namespace. `providers/stt/soniox.py:279,663-674` gives new socket a new speaker scope, while successful finalized turns return `epoch_disposition='reuse'`.
- `core/orchestrator/translation_turn.py:78-151,776-778` splits peer transcript by vendor speaker runs before output. `core/speaker_identity.py:13-65` assigns up to four palette colors to distinct raw keys per scope and marks fifth+ `palette_overflow`; that changes display color, **not** native speaker IDs. Independent app session restarts can reset palette assignment even if vendor raw numeric IDs repeat. Existing persisted diagnostics intentionally omit native speaker IDs (`providers/stt/soniox.py:788-820`); no retrospective real-user confusion matrix can be derived from their absence.

[Soniox's own realtime diarization guidance](https://soniox.com/docs/stt/concepts/speaker-diarization) warns that realtime can have higher attribution error and temporary switches, that early endpoint/manual finalization reduces diarization accuracy, and that support for up to 15 speakers is not a guarantee of discovering all voices. Its [manual finalize guidance](https://soniox.com/docs/stt/rt/manual-finalization) recommends approximately 200 ms silence after speech. This live fixture demonstrates vendor-attributable merge and split behavior even without intermediate client finalization and also in its async full-file result. It cannot establish frequency on VRChat conversational Chinese/Japanese, causality for the user's particular sessions, or a universal Soniox speaker-ID ceiling. Distinguish missing IDs from the separately proven four-color presentation cap in any subsequent UX diagnosis.

## Costs and failures

Live traffic: three WebSocket sessions, one uploaded async file and one async transcription job, seven async REST requests including file/job deletion; audio supplied was 51.730 + 51.730 + 47.940 + 51.730 = **203.130 input-audio seconds**. Vendor billing may use total realtime stream duration, not just sent audio. All three WebSockets received expected `<fin>` counts (1/9/15), the async job completed and both async resources were deleted, and no transport or provider errors occurred. This experiment does not assert exact billed seconds. Public audio clips remain locally cached for reproducibility.

## Execution record and environment

Baseline at probe time: branch `soniox_diar_test`, HEAD `547014fe04b92ab5f81f17bbeb5dfb88c5680a02` (confirmed with `git rev-parse HEAD && git branch --show-current`); Windows x64, Python 3.14.7 from `C:/Users/salee/Documents/dev/puripuly_heart/.venv/Scripts/python.exe`, `websockets` 16.1.1, `numpy` 2.5.1, `onnxruntime` 1.28.0, `keyring` 25.7.0, `requests` 2.32.5, FFmpeg 8.0.1. The commands below were executed **once each for Soniox**; the offline segmentation-only replay made no Soniox request.

| Executed command (repository root, prepend the Python executable above) | Observed completion output |
| --- | --- |
| `experiments/soniox_diarization/probe.py --arm continuous` | `completed=continuous sent_seconds=51.73 fin_count=1 final_tokens=181`; 173 mapped eligible tokens |
| `experiments/soniox_diarization/probe.py --arm forced` | `completed=forced sent_seconds=51.73 fin_count=9 final_tokens=185`; 170 mapped eligible tokens |
| `experiments/soniox_diarization/probe.py --segments-only` | `app_segments=15`, Smart Turn `ready`, `smart_turn_inferences=18`; no WebSocket |
| `experiments/soniox_diarization/probe.py --arm segmented` | `app_segments=15`; `completed=segmented sent_seconds=47.94 fin_count=15 final_tokens=186`; 167 mapped eligible tokens |
| `experiments/soniox_diarization/async_probe.py` | `async_status=queued`, then `async_status=completed`; `completed=async_full_file final_tokens=182`; `async_http_requests=7` including deletions |

The background shell tool marked all five jobs **completed**, and all emitted the listed success output without a Python traceback; it did not expose numerical exit codes in its returned transcript. No tests were run (investigation only). Cached public FLAC files and Python bytecode are excluded by the task-local `.gitignore`; the manifest/scripts/report and four JSON evidence outputs remain reproducible without committing cache bytes.

## External evidence and practical decisions

- [Soniox speaker diarization](https://soniox.com/docs/stt/concepts/speaker-diarization): up to 15 speakers **per transcription session** is a supported ceiling, not a guaranteed discovered count. Similar voices can reduce accuracy. The vendor explicitly documents realtime attribution errors and temporary switches, and recommends async for maximum accuracy. Our async result is counterevidence to treating that recommendation as a guaranteed fix.
- [Final versus non-final tokens](https://soniox.com/docs/stt/rt/real-time-transcription): non-final tokens may change; finalized tokens will not be revised. This probe scores only final tokens, so the observed errors are not merely provisional display flicker.
- [Current models](https://soniox.com/docs/stt/models): `stt-rt-v5` and `stt-async-v5` are active; v4 names route to v5 after June 30, 2026. Comparing the old alias against v5 would not establish a model-version contrast. Release-note claims of improved separation provide no independent error-rate baseline.
- [Context](https://soniox.com/docs/stt/concepts/context): speaker descriptions in `context.general` are experimental assistance, whereas our application supplies vocabulary through `context.terms`. Neither is a documented persistent voice-identity enrollment API. No speaker-context arm was run.
- Public evidence research did not establish an independent current Soniox-v5 diarization benchmark. [DIHARD III](https://arxiv.org/abs/2012.01477) provides broader evidence that performance depends strongly on recording domain, not an expected Soniox error rate. [AMI](https://groups.inf.ed.ac.uk/ami/corpus/overview.shtml) offers annotated four-person meetings, but the researched download workflow required registration; a small, directly downloadable LibriSpeech-derived probe avoided a new account and large meeting-data transfer.

The immediate decision is **not to change production segmentation or switch providers on this one fixture**. The direct-API errors rule out the app as the necessary cause of every merge/split; they do not prove that capture, VAD, session resets, or presentation never add errors. Fixed six-second finalization was not a remedy, and the segmented arm changes audio/context as well as finalization frequency, so it cannot isolate a single harmful knob.

Recommended priorities:

1. Treat four-color presentation as a separate usability limitation. More colors could expose more distinct vendor IDs, but cannot separate people Soniox already assigned the same ID.
2. Do not promise stable person identity from these realtime speaker labels or infer that the documented 15-speaker ceiling means reliable 15-person separation. A new connection is a new identity scope.
3. Before a production latency/segmentation change or provider replacement, use a small consented target-domain recording with known Chinese/Japanese conversational turns, including same-person adjacent utterances and overlapping voices. Compare the same waveform against this direct/segmented protocol and any candidate provider; preserve raw final IDs only in an explicit local experiment. This is a recommendation, not an unperformed acceptance check for the current engineering probe.

User-visible behavior and maintained architecture are unchanged. No desktop GUI/HMD interaction, production capture-device path, or product test suite was exercised.

## Existing local-log findings

Read-only investigation streamed **both complete files**, not only search-tool excerpts, from `C:/Users/salee/AppData/Local/puripuly-heart/`: `puripuly_heart.log` (6,955,812 bytes / 31,456 lines) and `puripuly_heart.backup.log` (20,971,269 bytes / 106,253 lines). Only diagnostic metadata was aggregated; private transcript text and credentials were not copied into experiment artifacts or sent externally. Backup timestamps contain clock time only, so no calendar date is inferred for its sessions.

The backup does contain substantial peer Soniox use:

| Backup-log observation | Count / evidence |
| --- | --- |
| Peer Soniox terminal turns | 1,630: 1,449 final, 141 empty, 14 failed, 15 expired, 11 cancelled |
| Accounted successful audio | 86,827,422 samples / 16 kHz = 5,426.7 s, about 90 min 27 s |
| Turns with at least 6 s of successful samples | 192; maximum 103,744 samples = 6.484 s |
| Long sustained provider epoch | 03:57:43–04:46:57; 519 turns, 482 final + 37 empty, all causes `none`; lines 90339–98918 |
| Last sustained provider epoch | 04:47:11–05:13:23; 221 turns, 210 final + 10 empty + 1 cancelled/`toggle_off`; lines 98942–103322 |
| Failed-terminal causes | 5 `provider_send_timeout`, 8 `provider_final_timeout`, 1 `provider_reported` |
| Expiries and cancellation | 5 `overload`, 10 `expired_before_recognition`; 5 cancelled/`closed`, 6 cancelled/`toggle_off` |

This establishes real sustained recognition sessions and some failures, **not** a diarization success/failure rate. A `final` outcome means a final transcript terminal, not a correct speaker assignment. The 192 long turns do not prove 192 hard-deadline cuts because those older rows omit the cut reason. The two substantial intervals each retain one provider epoch; this argues against a new provider session for every utterance. However, the backup does not retain the detailed Soniox reconnect/finalize-write/fin-accepted markers needed to reconstruct every transport recovery. Its 26 applied transitions/handoffs to Soniox must not be reported as 26 proven reconnects. Accounted successful samples are not an expected-capture baseline and do not measure capture loss.

The current log has 90 peer Soniox turn keys (89 terminal records: 27 final, 23 empty, 30 failed, 6 expired, 3 cancelled; one lacks a terminal), but only 314,786 successful samples, about 19.7 seconds total. Its 219 detailed peer Soniox summaries at 10:40:26.885–10:49:14.065 include 54 fin, 69 provider-error, 30 local-stop, 27 protocol-error, 27 transport-error, 9 abort and 3 local-close rows. These are summary-row counts, not independent user turns. [INFERENCE] Tiny inputs, short configured timeouts and concentrated repeated cases make this block test/probe-like; treating its error fraction as normal conversation performance would be misleading. The newest peer Soniox entries at 21:41:54 are just two empty 64-ms inputs in separate epochs (`puripuly_heart.log:31421–31430`), not the user's sustained conversation.

Crucially, persisted diagnostics intentionally exclude raw native speaker IDs (`docs/architecture.md:421–426`, `providers/stt/soniox.py:788–820`), and no user-session audio or speaker-reference labels were available. Consequently, **the actual historical frequency of different-person merges and same-person adjacent switches cannot be recovered from these logs**. The user's observations are not contradicted by that observability limit. The live public-audio probe above supplies independent, attributable examples of vendor merges and splits; it does not retroactively identify the cause of each historical incident.
