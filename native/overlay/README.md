# Native Overlay

Windows Rust runtime for the VR subtitle overlay.

## Ownership

- Rust implementation: `native/overlay/src`
- Rust tests: `native/overlay/tests`
- Python protocol and process integration:
  - `src/puripuly_heart/core/overlay`
  - `src/puripuly_heart/core/runtime/overlay.py`
  - `src/puripuly_heart/ui/desktop_overlay.py`

The shared bridge is version 13 with execution contract r2 and exclusive native
presentation retries. Authentication and readiness require
`speaker_identity_presentation: {"version":2,"policy":"immutable_first_readable_style"}`;
version 12 (15-entry palette, no divider) and the version 11 transition
handshake are incompatible. Python fixes a caption's `speaker_style` at first
readable publication and sends only that style, not speaker identity. SELF
remains white; peers use four stable per-scope styles (gold `#FFD700`, cyan
`#40DBFF`, coral `#FF7F5C`, blue `#7593FF`), or gray `#B4B4B4` when
unattributed, unavailable, handed off, or past the fourth speaker in a scope.
The canonical style colors live in `src/renderer/types.rs`. The same selected
color applies to source and translation and participates in native
render-cache invalidation and replay.

The snapshot's `speaker_divider` flag asks native to draw a gray band between
the two caption slots. Python sets it only when both visible blocks are peer
captions frozen as palette overflow for different speakers in the same scope;
native draws it only while both slots are occupied. The band is centered in the
slot gap and on the caption center, 1320 × 12 surface px (8 px `#E6E6E6` fill,
2 px black outline, rounded ends), fixed in surface pixels, and is part of frame
identity and damage tracking.

Python owns caption expiry and send-time pruning; native renders the accepted
snapshot without a validity-lease exchange or autonomous caption-expiry Hide.
Old captions can remain if removal cannot be delivered or replacement rendering
fails. Health reports presentation progress, not caption freshness. Runtime
generation retirement, bounded recovery, OFF/shutdown, and the 500 ms empty-frame
hide grace remain unchanged.

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

