# Qwen AMI execution record

Model: `qwen3.8-livetranslate-flash-realtime`, China (Beijing), seven intended independent AMI case-local sessions, mono PCM16 16 kHz audio submitted in 50 ms realtime-paced chunks. `session.update` selects `speaker_detection` threshold 0.5, source ASR (model default), Korean text-only translation. No reference, speaker labels, speaker-count hints or descriptions were sent. The 600 s `long_context` completed in one continuous WebSocket session; no splitting/reconnect.

## Commands and environment

- Windows interpreter: `C:/Users/salee/Documents/dev/puripuly_heart/.venv/Scripts/python.exe`; script: `experiments/ami_benchmark/providers/qwen/run.py`. Executed script with these exact argument lists in order: (1) no arguments (all seven); (2) `--case low_overlap --case rapid_turn_taking --case overlap_heavy --case long_return_gap --case brief_interjections`; (3) `--case low_overlap --case rapid_turn_taking --case overlap_heavy --case brief_interjections`; (4) the same list after TLS-edge diagnostics; (5) `--case low_overlap --case brief_interjections`. Every failed original result/event log was preserved as `*.attemptN.json` / `*.attemptN.jsonl` before submitting a fresh independent case attempt.
- Linux route: `wsl.exe -d Ubuntu -- /usr/bin/env HOME=/mnt/c/Users/salee PYTHONPATH=/mnt/c/Users/salee/Documents/dev/puripuly_heart/.venv/Lib/site-packages /usr/bin/python3 /mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/ami_benchmark/providers/qwen/run.py --case low_overlap --case brief_interjections`; next, the same command with `--case brief_interjections` only, which stopped before model connection when all resolved edges failed TLS. After offline audit, an independent TLS preflight succeeded, so the same brief-only command was run once more; its actual WebSocket TLS handshake then aborted after 60 s without opening a session.
- The same existing Beijing key/host loader read the root `.env.local` (in WSL via `HOME` pointing to its parent). No key, private endpoint, workspace ID, or resolved IP is printed or persisted. Prior reviewed Qwen helper supplies credential/endpoint logic and native event collection. Direct TLS preflight selects a responsive resolved edge, preserving the configured hostname in SNI and WebSocket Host. This diagnosis arose after TCP succeeded but TLS stalled on one resolved endpoint; on one later check every resolved endpoint stalled while unrelated public HTTPS endpoints connected normally. Preflight does **not** open a model session.
- **Route/TLS ambiguity resolved for the final failed retry:** its TLS preflight and actual WebSocket ran in the **same WSL Python process/OS**, and `execute()` passed the exact resolved IP returned by `select_tls_address()` unchanged to `websockets.connect(host=address, port=443, proxy=None)`. Both use the original configured Beijing hostname for SNI; the WebSocket URI keeps it for HTTP Host and model/key. Preflight used `ssl.create_default_context()` in a separate socket/TLS context; WebSocket uses asyncio's default SSL context, so the context object is not literally identical, but neither selects a different host/proxy/account. The preflight succeeded on address index 0; the **same-IP second socket** raised `ConnectionAbortedError: SSL handshake is taking longer than 60.0 seconds`, with `connection_opened=false`, zero events and zero audio. This is TLS negotiation, **not** an HTTP WebSocket upgrade error or the 90 s WebSocket opening timeout. A distinct earlier post-audit preflight could theoretically resolve a different IP; the case-local preflight and actual failure did not.
- The initial reviewed helper used a 30 s WebSocket opening timeout and 20 s ping timeout. Recovery runner uses 90 s opening timeout and, after an observed `1011 keepalive ping timeout` during streaming, 120 s ping timeout. These do not change the model audio/configuration, and no recovery silently continues an incomplete case within a new session.
- Official model documentation: https://help.aliyun.com/en/model-studio/qwen3-8-livetranslate-flash-realtime (Beijing model rate limit 10 requests/minute, 100,000 tokens/minute; no audio session-length ceiling stated on that model page). Protocol guide: https://help.aliyun.com/en/model-studio/qwen3-5-livetranslate-flash-realtime (finish requires server `session.finished`). Sequential execution stayed below the published request-rate limit.

One-shot **transport-only** recovery reproduction (no model session or audio submission; command loads the matching key/host without echoing them):

```text
wsl.exe -d Ubuntu -- /usr/bin/env HOME=/mnt/c/Users/salee PYTHONPATH=/mnt/c/Users/salee/Documents/dev/puripuly_heart/.venv/Lib/site-packages /usr/bin/python3 /mnt/c/Users/salee/Documents/dev/puripuly_heart/.worktrees/puripuly_heart/soniox_diar_test/experiments/ami_benchmark/providers/qwen/run.py --check-transport
```

The equivalent internal `select_tls_address()` preflight was exercised: after offline audit it reported a TLS-responsive address, but the subsequent **brief-only** real handshake stalled at the same edge. A positive preflight is not evidence of a completed model session. If transport later stabilizes, retain/move the current incomplete `results/brief_interjections.json` and `events/brief_interjections.jsonl` together as the next attempt number, update that archived result's `native_events.path`, then run only `--case brief_interjections` on the original Beijing host/key. Do not rerun six completed cases. Only once seven cases have `session.finished` and seven real RTTMs may the unchanged scorer be run as `experiments/ami_benchmark/.venv/bin/python experiments/ami_benchmark/score.py --predictions experiments/ami_benchmark/providers/qwen/predictions --output experiments/ami_benchmark/providers/qwen/score.json` from WSL with its benchmark root as cwd.


## Artifacts and interpretation

`results/<case>.json` contains the secret-redacted native `events/<case>.jsonl` hash, full input WAV/PCM SHA-256, model/effective configuration, session lifecycle, submitted audio duration, wall time, event counts, integer native `speaker_id` intervals, unattributed items and unpaired/ambiguous boundaries, and prediction hash. `predictions/<case>.rttm` exists **only for a fully completed case**; `predictions/provenance.json` has `status: incomplete`, six completed case receipts with the required input/prediction/native-result hashes and `missing_cases: [\"brief_interjections\"]`. The seventh case is never claimed complete. Failure attempts remain separately inspectable. A noncompleted case cannot be represented as an empty RTTM. Native `audio_start_ms` and `audio_end_ms` are local input seconds; `item_id` correlates start/end only, never names speakers. Finite intervals intersect the input `[0,duration]` window, wholly outside and zero-length intervals are omitted, clipping is explicit, overlaps are retained, and no unconfirmed tail or gap is filled. No GT is opened until the common scorer runs.

Known completed native predictions (all matching manifest PCM/WAV hashes, `session.finished` received, zero observed native boundary defects, unattributed intervals, out-of-window/clipped spans and server errors):

| Case | Audio sent (s) | Native bounded intervals | Distinct integer IDs | Min/max native offset (s) |
| --- | ---: | ---: | ---: | ---: |
| low_overlap | 120 | 2 | 2 | 0 / 120 |
| rapid_turn_taking | 120 | 50 | 12 | 0 / 120 |
| overlap_heavy | 120 | 64 | 17 | 0 / 120 |
| long_return_gap | 180 | 25 | 3 | 0 / 180 |
| long_context | 600 | 202 | 18 | 0 / 600 |
| far_field_pair | 120 | 57 | 11 | 0 / 120 |

The long-context 18 native IDs are **not** silently collapsed to reference speaker counts. Optimal ID mapping and overlap-aware DER were calculated individually with the unchanged `score_case` implementation; existing two-speaker Qwen controls are not generalized to this AMI material. The forced-aligned word reference versus provider utterance spans affects DER, so these scores are not pure identity quality.

## Offline RTTM repair and partial per-case scores

The first writer emitted nine rather than the shared scorer's required ten RTTM fields. Without opening a network socket, `C:/Users/salee/Documents/dev/puripuly_heart/.venv/Scripts/python.exe experiments/ami_benchmark/providers/qwen/run.py --rebuild-predictions` re-parsed each **completed saved native event log**, checked its SHA-256/count, compared the recovered source-local integer-speaker intervals against its existing completed native result, and regenerated only those six predictions with trailing `<NA>`. It refreshed each completed native result's prediction digest and all six native-result/prediction digests in `predictions/provenance.json`. The six corrected RTTMs have 10 fields on every row and retain LF-only bytes; their native event logs were not changed. The failed seventh case remains `missing_cases: [\"brief_interjections\"]` without RTTM. Hash checks passed for all six event logs, predictions, native results and provenance references.

The unchanged WSL benchmark scorer's `score_case(case, predictions)` was directly invoked for **each of the six completed manifest cases** with its isolated benchmark Python; the unchanged default seven-case CLI was also exercised and correctly raised `FileNotFoundError` for `brief_interjections.rttm` (no `score.json` produced).

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

These rows are **per-case observations only**, not a six-case benchmark aggregate or a seven-case completion claim.


## Incomplete attempt diagnostics

Prior failures include Windows 30 s opening handshakes, later Windows 60 s TLS handshake aborts, and occasional streaming disconnections without `session.finished`. The original `long_return_gap` streamed 180 s but closed before the final marker; its independent recovery completed. `brief_interjections` has no valid final RTTM yet: one attempt streamed 120 s and ended with WebSocket `1011 keepalive ping timeout`/abnormal close 1006; another streamed 79.95 s and similarly closed. The final fresh brief-only attempt failed during opening TLS without audio. These remain failure records and have never been scored as empty silence. All native event logs and original failed attempt metadata were retained (including zero-byte logs when opening failed). Across **24** recorded attempts, 10 WebSocket sessions opened; **56,318,400 PCM bytes / 1,759.95 s** were submitted, of which the six valid final sessions comprise 1,260 s. Billing amounts/provider-billed seconds are unknown; submitted audio seconds are measured from sent PCM bytes rather than invented billing.

**Status:** 6/7 completed; the six-case native results and RTTMs are hash-verified and stable for offline **per-case partial comparison**, but not a seven-case aggregate. `brief_interjections` remains externally blocked by Beijing TLS edge and/or midstream websocket availability. No `score.json` exists and no unchanged-scorer seven-case run was claimed.
