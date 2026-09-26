# Native Overlay

Windows Rust runtime for the VR subtitle overlay.

## Ownership

- Rust implementation: `native/overlay/src`
- Rust tests: `native/overlay/tests`
- Python protocol and process integration:
  - `src/puripuly_heart/core/overlay`
  - `src/puripuly_heart/core/runtime/overlay.py`
  - `src/puripuly_heart/ui/desktop_overlay.py`

The shared bridge protocol is version 12 with execution contract r2 and exclusive
native presentation retries. Authentication and readiness advertise
`speaker_identity_presentation: {"version":1,"policy":"immutable_first_readable_style"}`.
Version 11's `speaker_transition_presentation` handshake is rejected. Python
selects and freezes the speaker style before readable publication; native receives
only the selected `speaker_style` string, not provider speaker identity keys.
Semantic SELF/PEER channels remain independent of style. SELF text is always white.
Missing or unsupported peer styles are gray (`#9AA0A6`). The 15 identified peer
styles are fixed sRGB colors, without cycling:

| Style | Color | Style | Color | Style | Color |
| --- | --- | --- | --- | --- | --- |
| gold | `#FFD700` | cyan | `#33D6FF` | p02 | `#FF6B6B` |
| p03 | `#7CFF6B` | p04 | `#C77DFF` | p05 | `#FF9F1C` |
| p06 | `#FF5D8F` | p07 | `#4DFFC8` | p08 | `#B8FF3C` |
| p09 | `#FF4D4D` | p10 | `#6C8CFF` | p11 | `#E6FF4D` |
| p12 | `#FF7AD9` | p13 | `#5CFFEA` | p14 | `#FFB020` |

The same brush colors both primary and secondary rows. Style participates in
frame identity and render caches, so a style-only change repaints and retries use
the current style. Python owns caption expiry and send-time pruning; native renders
the accepted current snapshot without a validity-lease exchange or autonomous
caption-expiry Hide. Old captions can remain if the application cannot deliver
removal or the replacement frame fails. Health responses report presentation
stage and meaningful progress to the Python supervisor, not caption freshness.
Runtime generations, semantic retirement, bounded recovery, explicit OFF/shutdown,
and the 500 ms empty-frame hide grace remain unchanged.

Run commands from the repository root. On Windows, use a short `--target-dir`
path if the checkout is deep enough to exceed MSBuild's tracking-file path limit.

## Verification

```powershell
cargo test --locked --manifest-path native/overlay/Cargo.toml
cargo test --locked --manifest-path native/overlay/Cargo.toml windows_graphics_style_changes_repaint_both_rows_and_replay_identically -- --nocapture
cargo build --manifest-path native/overlay/Cargo.toml --locked --release --bin PuriPulyHeartOverlay --target-dir target

New-Item -ItemType Directory -Force -Path build/overlay | Out-Null
Copy-Item target/release/PuriPulyHeartOverlay.exe build/overlay/PuriPulyHeartOverlay.exe -Force
Copy-Item third_party/openvr/win64/openvr_api.dll build/overlay/openvr_api.dll -Force

.\build\overlay\PuriPulyHeartOverlay.exe --check-startup-contract
```

The deterministic, graphics, and Python integration tiers run sequentially in
the single Windows-only `Overlay` job (`native-overlay`) in
`.github/workflows/pr-ci.yml`. The five real-process Python integration tests
run with `INTEGRATION=1` and zero skips enforced:

```powershell
$env:INTEGRATION = "1"
uv run --frozen pytest tests/app/test_desktop_overlay_runner.py::test_import_run_desktop_overlay_dispatch_is_provider_secret_and_stt_free tests/app/test_desktop_overlay_runner.py::test_import_preview_dispatch_is_provider_secret_and_stt_free tests/core/runtime/test_overlay_runtime.py::test_overlay_runtime_receives_real_subprocess_shutdown_ack_before_reader_cleanup tests/ui/test_flet_desktop_view_process_owner.py::test_windows_kill_on_close_job_reaps_assigned_real_process tests/ui/test_flet_desktop_view_process_owner.py::test_owner_reaps_real_process_and_pid_file_across_ten_cycles --junitxml=overlay-integration-results.xml
```


Shared protocol or startup changes also run:

```powershell
python -m pytest tests/core/test_overlay_protocol.py tests/core/test_overlay_manifest.py tests/app/test_desktop_overlay_runner.py

```

## Completion

Overlay behavior, protocol, or startup changes complete with:

1. Rust tests
2. Windows release build
3. Runtime assembly
4. Startup-contract verification
5. Python integration tests when the shared boundary changes

