# Qwen LiveTranslate diarization comparison

## Outcome

**Completed one live session.** The exact Qwen3.8 LiveTranslate realtime model processed the full six-speaker comparison waveform in Beijing, with no alternate model or retry. The complete sanitized native event stream and normalized intervals are saved in the ignored evidence artifacts.

The fixture was read from `experiments/diarization_comparison/nemotron/fixture.wav` and validated as mono, 16-kHz PCM16, 51.730 seconds. Its decoded PCM SHA-256 is `2eb1ab143c2a7dbaa7448c31b44dd8c517b85042e769f2da5d2ddaec14028762`, matching the comparison fixture.

## Request and effective configuration

- Model: `qwen3.8-livetranslate-flash-realtime` (not `qwen3.8-flash` or Qwen-MT).
- Region and route: Beijing `ALIBABA_API_HOST_BEIJING` plus the matching local region key were loaded internally from the main repository `.env.local`. Host and key values were never printed or saved. The supplied secure WebSocket host was the official Beijing region; the harness added `/api-ws/v1/realtime` and the exact model query once.
- Output: text only; target `ko`; source ASR left at the model's documented always-enabled default.
- Input: the complete original waveform as real-time-paced 50-ms mono PCM16 chunks at 16 kHz.
- Diarization: `audio.input.turn_detection.type=speaker_detection`, threshold `0.5`.
- No known speaker count, descriptions, or ground-truth speaker IDs are sent.

The server-confirmed `session.updated` configuration matched the request: text-only output, Korean target, PCM at 16 kHz, `speaker_detection` with threshold `0.5`, and source ASR left at the model's always-enabled default. In normalization, `item_id` is only the association key; the `speaker` value is read from native `input_audio_buffer.speech_started.speaker_id` and stringified, while the sanitized native integer is retained.

## Invocation and evidence

Invocation record (machine-local directory elided):

The actual invocation used the main repository's virtual-environment Python from the repository root:

```text
<main-repo>/.venv/Scripts/python.exe experiments/diarization_comparison/qwen/run.py --region beijing
```

Observed outcome in `result.json`: `status=evaluation_status=completed`; fixture hash matched; one websocket connection request/session; 51.73 seconds / 1,655,360 bytes sent; 324 native events received; `session.finished` received; no errors. The full harness wall runtime was 63.359704 seconds.

The provider returned 13 bounded speech intervals and 13 completed source transcripts; all 13 `response.done` events had `completed` status. There were no missing speaker attributions, ambiguous/unbounded intervals, or overlaps. The emitted speaker IDs were `"1"` through `"12"` across those intervals; this is an observed provider labeling count, not a ground-truth accuracy claim or a supplied speaker-count constraint. `unknown_coverage` is empty.

Post-hoc reference check: reference speaker `1089` first occurs at 0.000–3.275 s and overlaps Qwen ID `"1"`; the same speaker returns at 30.040–32.720 s and overlaps ID `"7"` for most of that turn (ID `"6"` also overlaps its first 0.20 s). The reference was not supplied to the model. This is an example of provider IDs changing on a returning reference speaker, not an accuracy score.

The largest `speech_stopped.audio_end_ms` was 50,880 ms (50.88 s), while 51.73 s of source audio was submitted. This is a provider speech-boundary offset, not wall-clock runtime. Audio streaming took 51.736138 s and the post-audio wait for session completion was 0.712604 s. The first `response.text.delta` was received 3.367246 s after websocket connection; that is a connection-relative wall reception time, not an input-to-response latency. `nominal_latency_s` and `nominal_delay_s` remain null. Alibaba's low-as-2.3-second latency statement is only a general product claim, not a measured result here. Billing amount and billed usage were not queried; the official materials do not state a maximum speaker count.

## Host selection and access

- The matching Beijing host and API key were obtained from the existing main-repository `.env.local`; only allow-listed host/key names were parsed. Their values were kept out of stdout and artifacts, and the env file was not changed. A local exact-value scan of `result.json`, `events.jsonl`, and this report against parsed provider keys, hosts, workspace IDs/host identifier, and checked keyring values passed with zero matches; scan emitted no private values.
- The provided host was a secure WebSocket origin on the official Beijing region, with no path or query. The harness normalized it to the documented realtime path and added `model=qwen3.8-livetranslate-flash-realtime` exactly once. `result.json` records a redacted endpoint template and the host variable name only.
- The same fixture SHA-256 was verified before opening the session. The request streamed the entire PCM waveform in 50-ms chunks, sent `session.finish`, and waited for `session.finished`; no cutoff or retry was observed.

## Reproduction and files

From `experiments/diarization_comparison/qwen`, run `python run.py --region beijing` using the existing main-repository `.env.local` host/key or equivalent local environment values. The harness verifies the fixture hash before connecting, uses only allow-listed local env entries or matching keyring credentials, preserves complete sanitized native events with separate reception timestamps, and writes normalized results in original-source seconds. `result.json` and `events.jsonl` are now regular task artifacts rather than ignore rules; `.gitignore` only excludes Python bytecode/cache. No product tests, product/config changes, alternate models, or second live session were used.

Task files: `run.py`, `.gitignore`, this report. Local evidence: `result.json`, `events.jsonl`.

Official API references: [Qwen LiveTranslate model and streaming procedure](https://help.aliyun.com/en/model-studio/qwen3-5-livetranslate-flash-realtime), [client events](https://help.aliyun.com/en/model-studio/live-translator-client-events), and [server events](https://help.aliyun.com/en/model-studio/live-translator-server-events).
