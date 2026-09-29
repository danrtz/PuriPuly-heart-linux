# Qwen AMI execution record

Model: `qwen3.8-livetranslate-flash-realtime`, China (Beijing), seven completed independent AMI case-local sessions, mono PCM16 16 kHz audio submitted in 50 ms realtime-paced chunks. `session.update` selects `speaker_detection` threshold 0.5, source ASR (model default), Korean text-only translation. No reference, speaker labels, speaker-count hints or descriptions were sent. The 600 s `long_context` completed in one continuous WebSocket session; no splitting/reconnect.

## Commands and environment

- Windows interpreter: `C:/Users/salee/Documents/dev/puripuly_heart/.venv/Scripts/python.exe`; script: `experiments/ami_benchmark/providers/qwen/run.py`. Executed script with these exact argument lists in order: (1) no arguments (all seven); (2) `--case low_overlap --case rapid_turn_taking --case overlap_heavy --case long_return_gap --case brief_interjections`; (3) `--case low_overlap --case rapid_turn_taking --case overlap_heavy --case brief_interjections`; (4) the same list after TLS-edge diagnostics; (5) `--case low_overlap --case brief_interjections`. Every failed original result/event log was preserved as `*.attemptN.json` / `*.attemptN.jsonl` before submitting a fresh independent case attempt.
- Linux route: `wsl.exe -d Ubuntu -- /usr/bin/env HOME=/mnt/c/Users/salee PYTHONPATH=/mnt/c/Users/salee/Documents/dev/puripuly_heart/.venv/Lib/site-packages /usr/bin/python3 /mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/ami_benchmark/providers/qwen/run.py --case low_overlap --case brief_interjections`; subsequently `--case brief_interjections` alone for each recovery attempt, including the final **successful** single-session 120 s input. The prior six completed cases were not rerun for final recovery.
- The same existing Beijing key/host loader read the root `.env.local` (in WSL via `HOME` pointing to its parent). No key, private endpoint, workspace ID, or resolved IP is printed or persisted. Prior reviewed Qwen helper supplies credential/endpoint logic and native event collection. Direct TLS preflight selects a responsive resolved edge, preserving the configured hostname in SNI and WebSocket Host. This diagnosis arose after TCP succeeded but TLS stalled on one resolved endpoint; on one later check every resolved endpoint stalled while unrelated public HTTPS endpoints connected normally. Preflight does **not** open a model session.
- **Route/TLS ambiguity resolved for the final failed retry:** its TLS preflight and actual WebSocket ran in the **same WSL Python process/OS**, and `execute()` passed the exact resolved IP returned by `select_tls_address()` unchanged to `websockets.connect(host=address, port=443, proxy=None)`. Both use the original configured Beijing hostname for SNI; the WebSocket URI keeps it for HTTP Host and model/key. Preflight used `ssl.create_default_context()` in a separate socket/TLS context; WebSocket uses asyncio's default SSL context, so the context object is not literally identical, but neither selects a different host/proxy/account. The preflight succeeded on address index 0; the **same-IP second socket** raised `ConnectionAbortedError: SSL handshake is taking longer than 60.0 seconds`, with `connection_opened=false`, zero events and zero audio. This is TLS negotiation, **not** an HTTP WebSocket upgrade error or the 90 s WebSocket opening timeout. A distinct earlier post-audit preflight could theoretically resolve a different IP; the case-local preflight and actual failure did not.
- The initial reviewed helper used a 30 s WebSocket opening timeout and 20 s ping timeout. Recovery runner uses 90 s opening timeout and, after an observed `1011 keepalive ping timeout` during streaming, 120 s ping timeout. These do not change the model audio/configuration, and no recovery silently continues an incomplete case within a new session.
- Official model documentation: https://help.aliyun.com/en/model-studio/qwen3-8-livetranslate-flash-realtime (Beijing model rate limit 10 requests/minute, 100,000 tokens/minute; no audio session-length ceiling stated on that model page). Protocol guide: https://help.aliyun.com/en/model-studio/qwen3-5-livetranslate-flash-realtime (finish requires server `session.finished`). Sequential execution stayed below the published request-rate limit.

One-shot **transport-only** recovery reproduction (no model session or audio submission; command loads the matching key/host without echoing them):

```text
wsl.exe -d Ubuntu -- /usr/bin/env HOME=/mnt/c/Users/salee PYTHONPATH=/mnt/c/Users/salee/Documents/dev/puripuly_heart/.venv/Lib/site-packages /usr/bin/python3 /mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/ami_benchmark/providers/qwen/run.py --check-transport
```

Historical transport-only checks established that a successful TLS preflight did not guarantee a subsequent WebSocket TLS handshake on the same edge; see preserved failed attempts below. The final brief-only invocation succeeded with the same Beijing model, host, SNI, key and direct route, after which the unchanged seven-case scorer was run.


## Artifacts and interpretation

`results/<case>.json` contains the secret-redacted native `events/<case>.jsonl` hash, full input WAV/PCM SHA-256, model/effective configuration, session lifecycle, submitted audio duration, wall time, event counts, integer native `speaker_id` intervals, unattributed items and unpaired/ambiguous boundaries, and prediction hash. `predictions/<case>.rttm` exists only for a fully completed case; `predictions/provenance.json` now has `status: completed`, seven completed case receipts with input/prediction/native-result hashes and `missing_cases: []`. Failed attempts remain separately inspectable and were never represented by fake empty RTTMs. Native `audio_start_ms` and `audio_end_ms` are local input seconds; `item_id` correlates start/end only, never names speakers. Finite intervals intersect the input `[0,duration]` window, wholly outside and zero-length intervals are omitted, clipping is explicit, overlaps are retained, and no unconfirmed tail or gap is filled. No GT was opened during inference; the unchanged scorer read reference only afterward.

Known completed native predictions (all matching manifest PCM/WAV hashes, `session.finished` received, zero observed native boundary defects, unattributed intervals, out-of-window/clipped spans and server errors):

| Case | Audio sent (s) | Native bounded intervals | Distinct integer IDs | Min/max native offset (s) |
| --- | ---: | ---: | ---: | ---: |
| low_overlap | 120 | 2 | 2 | 0 / 120 |
| rapid_turn_taking | 120 | 50 | 12 | 0 / 120 |
| overlap_heavy | 120 | 64 | 17 | 0 / 120 |
| long_return_gap | 180 | 25 | 3 | 0 / 180 |
| brief_interjections | 120 | 40 | 11 | 0.12 / 117.04 |
| long_context | 600 | 202 | 18 | 0 / 600 |
| far_field_pair | 120 | 57 | 11 | 0 / 120 |

The long-context 18 native IDs are **not** silently collapsed to reference speaker counts. Optimal ID mapping and overlap-aware DER were calculated individually with the unchanged `score_case` implementation; existing two-speaker Qwen controls are not generalized to this AMI material. The forced-aligned word reference versus provider utterance spans affects DER, so these scores are not pure identity quality.

## Historical offline RTTM repair and six-case partial scores

The first writer emitted nine rather than the shared scorer's required ten RTTM fields. Without opening a network socket, `C:/Users/salee/Documents/dev/puripuly_heart/.venv/Scripts/python.exe experiments/ami_benchmark/providers/qwen/run.py --rebuild-predictions` re-parsed each of the **then-six** completed saved native event logs, checked SHA-256/count, compared recovered source-local integer-speaker intervals to the existing native results, and regenerated their predictions with trailing `<NA>`. It refreshed those prediction and native-result digests in `predictions/provenance.json`. Those six corrected RTTMs have 10 fields on every row and retain LF-only bytes; their native logs were not changed. At that stage, the seventh case was still missing. The now-completed seventh case used the corrected 10-field writer directly.

Before the final successful measurement, the unchanged WSL benchmark scorer's `score_case(case, predictions)` was directly invoked for each of the then-six completed manifest cases. At that time, the unchanged default seven-case CLI correctly raised `FileNotFoundError` for `brief_interjections.rttm`; the full seven-case CLI has since completed successfully.

Scoring command executed (from any cwd; no output file or aggregate generated):

```text
wsl.exe -d Ubuntu -- /mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/ami_benchmark/.venv/bin/python -c "import importlib.util,json,pathlib; root=pathlib.Path('/mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/ami_benchmark'); spec=importlib.util.spec_from_file_location('ami_standard_score',root/'score.py'); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m); cases=json.loads((root/'manifest.json').read_text())['cases'];p=root/'providers/qwen/predictions'; completed={r['id'] for r in json.loads((p/'provenance.json').read_text())['cases']}; print(json.dumps([m.score_case(case,p) for case in cases if case['id'] in completed],ensure_ascii=False))"
```


| Case | Ref / native speaker counts | DER | Missed (s) | False alarm (s) | Confusion (s) | Ref total (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| low_overlap | 3 / 2 | 0.165641 | 0.000 | 16.795 | 0.300 | 103.205 |
| rapid_turn_taking | 4 / 12 | 0.844018 | 52.641 | 20.341 | 50.464 | 146.260 |
| overlap_heavy | 4 / 17 | 0.834569 | 38.747 | 24.967 | 43.862 | 128.900 |
| long_return_gap | 4 / 3 | 0.349756 | 3.564 | 39.283 | 0.621 | 124.281 |
| long_context | 3 / 18 | 0.856849 | 100.993 | 126.668 | 243.439 | 549.805 |
| far_field_pair (paired, not independent primary) | 4 / 11 | 0.798138 | 42.009 | 23.269 | 37.602 | 128.900 |

These historical rows were **per-case observations only**, not a six-case benchmark aggregate. The complete seven-case aggregate is recorded below.


## Incomplete attempt diagnostics

Historical failures include Windows 30 s opening handshakes, Windows 60 s TLS handshake aborts, and streaming disconnections without `session.finished`. The first `long_return_gap` streamed 180 s but closed before final marker; its independent recovery completed. Earlier `brief_interjections` attempts included 120 s and 79.95 s streams that closed with WebSocket `1011 keepalive ping timeout`/abnormal close 1006. All such attempts retain their native event logs and failed metadata (including zero-byte logs for opening failures); none was scored as empty silence. The first 24 recorded provider attempts opened 10 sessions and submitted 56,318,400 PCM bytes / 1,759.95 s. Billing amounts/provider-billed seconds remain unobserved; these submitted durations are computed from sent PCM bytes, not billing.

### Fresh Beijing-only recovery after the harness-remeasurement request

At an earlier checkpoint, a redacted TLS-only check found four DNS addresses, with the second completing TLS after the first timed out. The prior failed result/event pair was preserved as `results/brief_interjections.attempt6.json` plus `events/brief_interjections.attempt6.jsonl`, with its internal event path corrected and event hash unchanged. The immediately subsequent brief-only invocation found no TLS-responsive address among four and stopped before any model session/audio/API request. Those observations describe the earlier outage, **not** the later successfully completed session.

## Completed brief-only remeasurement and full standard score

Without an extra standalone transport check, ran the documented WSL `run.py --case brief_interjections` command above exactly once for this remeasurement. Its case-local TLS check selected a responsive Beijing edge on the first address; a single fresh WebSocket opened and streamed all **3,840,000 PCM bytes / 120.0 s** in 50 ms realtime-paced chunks. Server `session.created`, `session.updated`, and `session.finished` were observed; 40 speech starts and 40 matching stops produced 40 attributed intervals and 11 distinct native integer speaker IDs. There were **zero** unpaired/ambiguous boundaries, unattributed intervals, clipping events, server errors or unfinished responses. The native interval start/end range was 0.12–117.04 s; no tail was inferred. Audio streaming occupied 120.000660 s wall time; post-audio finish wait was 0.943019 s; recorded case runtime was 132.026657 s. These are runtime observations, not end-to-end translation latency or billing.

The final attempt was one new opened model WebSocket session, one completed case and 120.0 s submitted audio. Across **25 recorded attempts**, 11 WebSocket sessions opened and **60,158,400 PCM bytes / 1,879.95 s** were submitted; this includes failed attempts and the seven successful sessions (1,380 s of unique case input). Provider-billed audio, billable tokens and price are **unknown**. The six previously approved prediction byte hashes were independently checked unchanged; no case but `brief_interjections` was re-inferred. The new case's event-log SHA-256 is `697493b1d941199f245ae75dfb94a3d13946471b199754a7b426dc036f93be96`; native-result SHA-256 `8c0e052135f43877aca1b129680e3f181ca44cb7029f964d4e98294cfa4b53af`; 10-field RTTM SHA-256 `fffc81c1a4517d03ccdd070b8ef6ab92348a8273b9c8f7c2e95aa34d45015f31`. All seven manifest PCM inputs, native event logs/counts, results, predictions and provenance digests were verified. `predictions/provenance.json` has seven `completed: true` receipts and `missing_cases: []`.

Ran the **unchanged standard seven-case CLI** (no narrowed or synthetic cases):

```text
wsl.exe -d Ubuntu -- /mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/ami_benchmark/.venv/bin/python /mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/ami_benchmark/score.py --predictions /mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/ami_benchmark/providers/qwen/predictions --output /mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/ami_benchmark/providers/qwen/score.json
```

`brief_interjections`: reference 4 vs native 11 speakers; **DER 0.766200968**; reference total 117.601 s, missed detection 26.620 s, false alarm 21.339 s, confusion 42.147 s. The scorer's six independent primary cases pooled **DER 0.728848803** (total 1,170.052 s, missed 222.565 s, false alarm 249.393 s, confusion 380.833 s; speaker-count accuracy 0, MAE 7.5). The separate paired far-field case scored **DER 0.798138092** (total 128.900 s, missed 42.009 s, false alarm 23.269 s, confusion 37.602 s; count accuracy 0, MAE 7). Metric: full-duration UEM, zero collar, overlaps included, per-case optimal speaker mapping. `score.json` SHA-256: `3cd589e8e1340f2fa72f2ec8425ade6715270b36ed194a5550426b60dc41fad5`.

**Status:** 7/7 genuine Beijing sessions completed, all seven ten-field RTTMs and full standard `score.json` present. Previously failed attempts remain preserved; no residual benchmark-execution blocker. These DERs include the forced-aligned reference/utterance-span mismatch and are not pure identity scores.
