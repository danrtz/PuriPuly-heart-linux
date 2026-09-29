# Alibaba workspace backend — issue #200

## Scope and status

Implements the backend and typed application contract in [issue #200](https://github.com/kapitalismho/PuriPuly-heart/issues/200). Rendered settings controls, layout, and final localized copy remain a separate UI rollout. This record does **not** claim that rollout or all live-service completion criteria have passed.

- Baseline: `95590edf789890f88f5fa5596f2e07dac44e7de7`.
- Initial implementation: `b2aa88c0b69fbd424ea5ed96ef41f0a06c363441`.
- Reviewed repair/source candidate: `b74984caa06abe43aa68b79ce8ce85be9d5a40ca`.
- Verification date: 2026-09-29.
- Commits are local; no push, PR, merge, deployment, or issue closure was performed.
- Independent full checkpoint review covered baseline → initial implementation. Four material findings were accepted and repaired; bounded independent repair verification returned `repair_verified` at the source candidate above.

## Backend and UI-session handoff

The system map and ownership contract are in [architecture.md](architecture.md#alibaba-workspace-connections).

- Schema 49 preserves existing connections as `legacy_shared`; each supported region has its own mode, normalized API Host, and revision. Existing models and active-region selection are retained.
- `config/alibaba_connection.py` resolves an immutable connection into compatible HTTP, native HTTP, and Qwen Audio WebSocket addresses. Dedicated hosts are structurally validated for the selected region before probing or execution; there is no hidden shared-host fallback.
- `app/services/provider/alibaba_workspace.py` owns drafts and independent capability evidence. Evidence follows the effective credential, region, mode, host, revision, capability, and model. Draft edits/probes do not apply runtime settings.
- `UiApplicationBoundary` exposes `begin_alibaba_connection_draft`, `alibaba_connection_draft`, `alibaba_active_connection`, `edit_alibaba_connection_draft`, `verify_alibaba_connection_draft`, `apply_alibaba_connection_draft`, and `cancel_alibaba_connection_draft`. The application port and intents mirror these operations; `AlibabaConnectionDraftSnapshot` is the typed projection in `app/ports/settings_view.py`.
- Existing `persist_provider_secret_change` actions retain regional secret save/replace/delete semantics. Removing or editing a host is not key deletion. Effective credential lookup retains existing regional, legacy, and environment precedence.
- The contract exposes regional editing, key presence, ASR/translation/both verification, separate readiness and failure categories, active/draft identity, affected consumers, explicit shared recovery, application results, maintenance/help, and possible verification usage. These operations do not require Qwen translation to expose Alibaba ASR configuration.
- Apply merges intended edits onto current canonical state and rejects conflicting edited-region revisions. Newer untouched regional settings survive. Returning to shared also recovers from an invalid dedicated draft without deleting a key.
- Existing provider application/lifecycle owners replace affected clients. No new replay, endpoint fallback, timeout/concurrency policy, model, region, or generic profile framework was introduced. Current rolling ASR membership has no Qwen member; Self and Peer Qwen Audio are covered.

## Credential-free verification

The following command exited successfully after the repairs:

```shell
uv run --extra dev pytest -q tests/app/test_alibaba_workspace.py tests/config/test_alibaba_connection.py tests/config/test_settings_vnext_migration_serialization.py tests/config/test_settings_vnext_schema.py tests/config/test_runtime_resolution.py tests/app/test_provider_credential_verification_owner.py tests/app/test_wiring_providers.py tests/app/test_provider_runtime_policy.py tests/app/test_provider_application_owner.py tests/app/test_ui_provider_runtime_adapter.py tests/app/test_provider_verifier_adapter.py tests/app/test_settings_mutation_legacy.py tests/app/test_settings_view_boundary.py tests/providers/test_qwen_async.py tests/providers/test_qwen_audio.py
```

The same 15 files separately collected **569 cases**. Execution produced successful dot progress without a numeric passed summary; 569 is a collection count, not a separately observed executed-count summary. No repository-wide pytest run is claimed.

Coverage combines new Alibaba behavior tests and retained canonical/provider tests:

| Requirement | Evidence and limits |
| --- | --- |
| Regional resolution and safety | `tests/config/test_alibaba_connection.py`, runtime-resolution and wiring suites: regional modes, exact addresses, selected credentials, malformed/mismatched host rejection, and no dedicated-to-shared fallback. |
| Migration/persistence | Canonical migration/serialization/schema suites: older settings, regional roundtrip, existing recovery and persistence behavior. Controlled adapter smoke saved and reloaded dedicated and shared temporary settings. No real profile was migrated during live validation. |
| Independent capabilities | Workspace and credential-verification suites: selected models, capability isolation, connection/key/model invalidation, stale responses, draft isolation, safe errors. |
| Lifecycle | Qwen Audio and provider-application/runtime-policy suites retain consecutive tasks, queued successor, finalization, stop/restart, stale-event, and replacement coverage. Hardware capture/application replacement is not claimed from those tests. |
| Typed application contract | Real `UiProviderRuntimeAdapter` with controlled transports and temporary canonical persistence exercised begin/edit/verify/apply/read/cancel and shared recovery. This is a composed application-adapter smoke, not a fully booted desktop application. |
| Review repairs | Regressions cover newer untouched Singapore preservation, stale edited-region rejection, invalid-host shared recovery, legacy/environment credentials and rotations, and top-level/nested error codes. |

Two throwaway, credential-free adapter smokes ran successfully and were removed afterward:

1. Begin → dedicated Beijing edit → independent controlled ASR/translation probes → apply → reload → verified active evidence → explicit shared return → reload.
2. Legacy/environment credential presence and verification; malformed dedicated host → shared recovery with unchanged secrets; merge a newer untouched Singapore setting; reject a stale edited Singapore setting; invalidate evidence when the effective environment key changes.

The second emitted:

```text
PASS: typed UI legacy fallback, invalid→shared recovery, unrelated Singapore merge, edited stale rejection, effective environment revision
```

Formatting checks:

- `uv run ruff check .`: **passed**.
- Black check over all 21 repair-touched Python paths: **passed**.
- `uv run black --check .`: **failed only on pre-existing, untouched `tests/ui/test_settings_prompt_switching.py`**; 987 files would remain unchanged. Checking that file's already committed `b2aa88c0` version also failed. The unrelated file was intentionally not restyled. Full-repository formatting CI is therefore not claimed green.

## Authorized, bounded live evidence

The user authorized a few paid Alibaba calls, then explicitly selected shared-only validation because no workspace API Host was available. Only the existing Beijing regional credential was used. No secret values, authorization headers, raw provider errors, microphone audio, or conversation content were recorded. Temporary settings, in-memory secret storage, and offline-generated audio were isolated and removed; the user's settings and secrets were not changed.

### Configuration

| Field | Tested value |
| --- | --- |
| Region / mode | Beijing / `legacy_shared` |
| Host | `dashscope.aliyuncs.com` |
| Translation model | `qwen3.8-flash` |
| ASR model | `qwen-audio-3.1-asr-flash-streaming` |
| Compatible HTTP | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| Qwen Audio | `wss://dashscope.aliyuncs.com/api-ws/v1/inference` |

At initial candidate `b2aa88c0`:

- Real typed adapter/workspace owner/resolver/verifier: independent ASR verification **verified** and independent translation verification **verified**. Draft was canceled without apply.
- Three controlled speech tasks returned final transcripts containing the expected synthetic words and normal `task-finished` events. The first two reused one WebSocket; closing it and constructing a replacement session completed the third task on the same shared endpoint.
- The first translation harness call mistakenly left prompt placeholders unresolved; its output is **not** counted as semantic success. A corrected production-rendered prompt produced Korean text. Exact output was not retained at this checkpoint, so a bounded final-candidate check below supplied exact result evidence.

At repaired source candidate `b74984ca`, one additional translation and one speech task recorded exact non-private results:

```text
Controlled input:
The purple lantern is glowing beside the quiet river.

English → Korean translation:
보라색 등불이 고요한 강 옆에서 빛나고 있어요.

Final ASR transcript:
The purple lantern is glowing beside the quiet river.
```

Windows offline SAPI generated the 3.53-second phrase; it was converted to 16-kHz PCM without recording a microphone. The ASR event was final, with one normal `task-finished`, then the session closed. The repaired credential resolver was also exercised through an isolated typed adapter draft and canceled without applying.

Cumulative paid operations: one translation verification, one ASR verification, three translation calls (including the malformed historical harness prompt), and four speech tasks across three ASR sessions. Unchanged verifier/reuse/reconnection evidence was retained rather than repeating the whole paid sequence. These small checks establish only the observed configuration and behavior, not a latency or statistical quality claim.

## Subsequent dedicated-host validation

After the user supplied an API Host in the private local environment file and requested testing, bounded live checks ran on clean candidate `771dc882a21b32f6221e360a2fd49479b02db058` (unchanged product source from `b74984ca`). This supersedes the earlier missing-host blocker for Beijing only; it does not turn every live criterion into a pass.

- Region/mode: Beijing / `workspace_dedicated`.
- Host: official Beijing workspace structure validated by the product resolver; private workspace identity redacted. SHA-256 host fingerprint prefix: `8f4f611505c6`.
- Credential: explicitly Beijing-bound environment key, used only in an isolated in-memory regional secret store. No actual profile, environment file, or saved secret was modified.
- Models: `qwen3.8-flash` and `qwen-audio-3.1-asr-flash-streaming`.
- Other supplied region variables did not expand the supported region scope. Singapore and Tokyo were not called; Tokyo is outside this implementation's Beijing/Singapore support.

The narrow real application composition used `UiProviderRuntimeAdapter`, `AlibabaWorkspaceOwner`, `ProviderSettingsOwner`, `ProviderVerifierAdapter`, `SettingsOwner`, and temporary canonical persistence. Runtime replacement hooks were controlled rather than a fully booted application.

| Check | Observed outcome |
| --- | --- |
| Dedicated draft, independent ASR and translation verification | Both capabilities verified. |
| Dedicated apply/save/reload | Temporary settings restored dedicated mode and connection revision 1. |
| Dedicated translation | Exact Korean output below. |
| Two consecutive dedicated ASR tasks on one WebSocket | Both exact final transcripts below; normal `task-finished` counts 1 then 2. |
| Close and open a replacement dedicated ASR session | **Failed:** `QwenAudioProtocolError` before `open_session()` returned. No replacement speech was sent; not retried. |
| Explicit dedicated → shared settings return | Passed in a separately reconstructed temporary configuration: dedicated revision 1 → shared revision 2, same regional key source. |
| Shared translation and ASR after that explicit return | Both succeeded with exact controlled results; ASR had normal `task-finished`. |

```text
Controlled input and final ASR transcript (dedicated and shared):
The purple lantern is glowing beside the quiet river.

Translation output (dedicated and shared):
보라색 등불이 고요한 강 옆에서 빛나고 있어요.
```

The audio was the same 3.53-second offline SAPI fixture converted to 16-kHz PCM, not microphone or conversation audio. Temporary files and in-memory credentials were removed after the checks.

The reconnect exception's HTTP status, provider error code, source-origin line, and handshake-versus-task-start stage were not captured. The failure's root cause is **undetermined**; this evidence does not establish whether it was transient service behavior, protocol/lifecycle behavior, or a harness problem. No diagnostic paid rerun was made. The original session's observed state after close was `closing`; the evidence does not establish the provider's remote resource-release timing.

A separate harness-only count-bookkeeping `KeyError` stopped the original temporary sequence after the replacement failure. The explicit shared return therefore used a fresh temporary configuration reconstructed from the same dedicated settings. It proves the isolated settings transition and successful shared requests, **not** an uninterrupted original-session rollback or a full application runtime rebind.

This additional run attempted: 1 dedicated ASR verifier, 1 dedicated translation verifier, 1 dedicated translation, 2 dedicated speech tasks on one WebSocket, 1 failed dedicated replacement open, 1 shared translation, and 1 shared speech task. Speech-task counts refer to explicitly supplied controlled speech; provider session internals may start a successor idle task. No other regional calls were made.

Upstream `dev` advanced separately to `547014fe04b92ab5f81f17bbeb5dfb88c5680a02` through #201, which also allocated schema 49. It was not merged or tested in this validation. The schema-version collision must be reconciled before integration; these results apply to the pinned branch candidate, not the newer upstream tree.

## Instrumented diagnostic follow-up (2026-09-29)

On clean baseline `73803fc21b71bf05e2d105a7c7d3385a090ddcaa` with narrow Qwen Audio diagnostic logging, one authorized dedicated cycle attempted the original production `websockets.connect` path. The strict Beijing resolver and previously recorded workspace-host fingerprint matched. A new `QwenAudioProtocolError` occurred on the **initial** connection before any speech task or replacement attempt: file-only logging reported `stage=connect`, `reason=connect_failed`, elapsed 5,032 ms, underlying and nested classes `TimeoutError`, with no HTTP status, WebSocket close code, or numeric provider code. The raised exception originated at the production connection wrapper. No WebSocket handshake completed; consequently this occurrence is **not a reproduction of the prior failure after close/reopen**. The rule to stop on a captured failure prevented further paid cycles. Traffic this follow-up: one failed initial dedicated WebSocket open, zero controlled speech tasks, zero replacement attempts, and no other provider or region calls.

Subsequent credential-free DNS, TCP, and TLS checks against the same validated workspace host completed in 0, 48, and 125 ms respectively, but they did not exercise the WebSocket upgrade or prove the service's availability at the earlier failure time. A local loopback WebSocket smoke exercised successful startup, one synthetic task finish, and close; a separate delayed HTTP upgrade deterministically produced the same instrumented `connect_failed`/nested `TimeoutError` path. The new record distinguishes this initial handshake deadline from run-task send, task-start wait, receive-before-ready, and close timing; it does not recover the lost cause of the historical replacement failure. No timeout, retry, endpoint, or lifecycle policy was changed without evidence of a product fault. Dedicated replacement remains unresolved.

## Blocked, not run, and follow-up

- **Failed / unresolved:** dedicated ASR close/recreate. The subsequent live run removed the missing Beijing API Host prerequisite and proved dedicated translation/ASR, but its replacement session failed as recorded above. Completion criterion 7 is not wholly passed.
- **Not run:** Singapore live calls. Tokyo is outside this implementation's supported regions and was not tested.
- **Not run:** fully booted application/hardware capture replacement and real-profile persistent apply/rebind. Provider sessions and narrowly composed real application adapters were exercised; application apply/replacement evidence is controlled/simulated.
- **Outstanding by scope:** concrete rendered UI rollout and visual/interaction verification. The UI session must consume the typed contract rather than redefine routing, readiness, or rollback.
- **Pre-existing CI exception:** unrelated Black failure noted above.
- Issue #200 remains open/in progress rather than treating the unresolved dedicated reconnect, integration/schema coordination, or later UI rollout as completed. No measured latency improvement is claimed.
