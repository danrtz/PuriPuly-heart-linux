# PuriPuly Heart on Linux

This fork ports [kapitalismho/PuriPuly-heart](https://github.com/kapitalismho/PuriPuly-heart) to native Linux while keeping its interface, translation providers, conversation routing and settings model. It started from upstream `991ef0bdf06d744ebb6e7aa6d8df5d4ee5f8ca46` (2.7.0) and now integrates upstream `0f9ed03e` (2.8.0). The development branch is `linux-port`.

The original project and this derivative are licensed under **AGPL-3.0-or-later**. Original attribution, licenses and third-party notices remain in the repository. This is an independent fork, not an official upstream Linux release.

## Requirements

The current installation targets **x86-64 Linux and Python 3.14**. It has been tested on Arch Linux with Hyprland, PipeWire, a Ryzen 7 9800X3D and a Radeon RX 7900 XT using Mesa RADV. Other distributions must provide equivalent libraries; they have not been verified here.

For an Arch desktop already using PipeWire:

```sh
sudo pacman -S --needed python python-pip base-devel rust cmake ninja pkgconf \
  shaderc vulkan-headers vulkan-icd-loader spirv-headers cairo pango openxr \
  libpulse portaudio gtk3 libsecret xdg-utils wl-clipboard xorg-xwayland \
  noto-fonts noto-fonts-cjk
```

Run the existing PipeWire PulseAudio compatibility service (`pipewire-pulse`) or a PulseAudio server. The capture adapter uses `pactl` and `parec` from `libpulse`; it does not change the server sample rate or global audio routing. Keep the Vulkan driver appropriate to your GPU installed. The package list does not install or replace a graphics driver.

A Secret Service provider, such as GNOME Keyring or a compatible KWallet service, supplies encrypted account storage. Unlock the keyring normally in your desktop session. Headset subtitles require WiVRn or Monado with `XR_EXTX_overlay` and `XR_KHR_vulkan_enable2` support.

## Install

Keep the checkout in a permanent location. From its root:

```sh
scripts/linux/install-user.sh
```

The installer creates or reuses `.venv`, installs the Python application into it, builds the native speech worker and VR overlay, downloads the pinned Linux llama.cpp runtimes, and adds user launchers and an application-menu entry. It does not require root after system prerequisites are installed. It does not overwrite application settings, enable autostart or download speech/translation models.

The build uses four jobs by default. Set `CARGO_BUILD_JOBS` to change this. Set `PURIPULY_SYSTEM_PYTHON` when the Python 3.14 executable has a different name.

The launchers use this checkout directly:

- `~/.local/bin/puripuly-heart`: graphical application.
- `~/.local/bin/puripuly`: JSON command-line control.
- `${XDG_DATA_HOME:-~/.local/share}/applications/puripuly-heart.desktop`: menu entry.

Moving or deleting the checkout breaks those launchers. Rerun the installer after moving it. If native builds already exist, `scripts/linux/install-user.sh --skip-native` refreshes Python dependencies and launchers without rebuilding them. An unrelated executable with the same launcher name is not overwritten.

To rebuild native components separately:

```sh
scripts/linux/build-native.sh
```

GPU ASR uses `transcribe-cpp` 0.1.3 with Vulkan. The script disables its automatic system BLAS dependency because the upstream Rust bindings do not link that optional library correctly on Linux. Vulkan acceleration remains enabled.

Local translation uses official llama.cpp **b10423**, commit `a94d563ed801d1da1b8c2432946de07d0231bb3d`, Linux CPU and Vulkan archives. Download sizes and SHA-256 digests are pinned and checked before extraction. The preparation command can also run independently:

```sh
.venv/bin/python -m puripuly_heart.release_evidence.linux_managed_gemma_distribution
```

Runtime files are staged under `build/gpu_worker`, `build/overlay` and `build/llama.cpp/llama.cpp-b10423`. Neither Windows executables nor Wine are used by the Linux application.

## First use

Open **PuriPuly Heart** from your application menu. Choose your microphone and playback source in Audio settings. The default microphone is resolved when capture starts, so after connecting a VR headset and making it the system default, restart TALK or the microphone test to use it. Named device selections retain stable PipeWire/PulseAudio IDs across application restarts. For English/Japanese conversations, select English as your language and Japanese as the other language, then choose speech-recognition and translation providers.

Local Qwen speech recognition and local Gemma translation work without an online translation account after their model downloads complete. The tested models are approximately:

| Model | Download |
| --- | ---: |
| Qwen3-ASR 0.6B int8, CPU | 0.99 GB |
| Qwen3-ASR 1.7B Q6_K, Vulkan | 1.69 GB |
| Gemma 4 E4B Q4 plus MTP draft model | 4.28 GB |

Each model follows the upstream pinned revision and integrity manifest. Downloads show progress and are installed separately from the source checkout. With default paths, settings, models and logs are stored under `~/.config/puripuly-heart`; `XDG_CONFIG_HOME` changes that location.

Cloud speech and translation providers retain their original account/API-key setup. Their availability, billing and service limits belong to those services. No cloud request or account sign-in is necessary to use the tested local models.

The original home controls keep their roles:

- **TALK** transcribes your microphone.
- **TRANS** translates recognized speech or submitted text using the selected provider.
- **LISTEN** captures the selected playback source and translates the other speaker. Review its first-use consent prompt, and select VRChat's active playback stream for application-only listening.
- **CAPTIONS** shows the selected desktop or headset subtitle overlay. For desktop use, position it while unlocked, then lock it to pass mouse clicks through.

For local English/Japanese use, select Qwen for speech and Gemma for translation, then enable TALK and TRANS. The first utterance can take longer while its model loads. Stop TALK and LISTEN when finished. OSC can be switched off independently when testing outside VRChat.

For VR subtitles, select the active WiVRn/Monado OpenXR runtime and start the headset session through your normal VR launcher. A runtime lacking the overlay extension is reported as unsupported rather than replacing its main VR session. The desktop subtitle overlay remains an alternative.

## Feature and validation status

| Feature | Linux implementation and evidence |
| --- | --- |
| Main application and settings | Original Flet interface runs natively on the tested Wayland desktop. Linux window resize controls are enabled. |
| Microphone and output capture | Native PulseAudio protocol capture; real 44.1 kHz microphone and output-monitor frames and clean shutdown verified. |
| Per-application listening | Captures a selected playback stream, follows process descendants and refreshed streams. A controlled 48 kHz stereo playback test and process-exit cleanup passed. Live VRChat/Discord session checks remain separate. |
| Local CPU speech recognition | Real Qwen model loading and English/Japanese recognition passed. Real microphone TALK start/stop and recorded speech through VAD → recognition → local translation also passed. |
| Local Vulkan speech recognition | Real RX 7900 XT discovery, model activation, English/Japanese recognition, authenticated IPC and shutdown passed. In 2.8.0, TALK prepares the GPU backend before capture is admitted, so startup failures are reported before listening begins. The original full Japanese VAD → GPU recognition → English translation check passed; see the update validation below. |
| Peer LISTEN pipeline | A public Japanese recording passed through the production conversion, VAD, GPU recognition and English translation pipeline with OSC disabled. Original/translated history labels and clean stop were verified; user consent and application audio were not changed. |
| Local CPU/GPU translation | Real Gemma English↔Japanese translation passed with original prompts, prefix caching, CPU MTP and native server shutdown. |
| Cloud speech/translation and account connections | Existing adapters and UI are retained. Provider-specific end-to-end checks require configured accounts and were not performed for this port. |
| VRChat OSC and conversation routing | A real English→Japanese translation reached an isolated UDP receiver as `/chatbox/input`. Hot port changes are covered. Peer captions remain excluded from the VRChat chatbox. An actual VRChat session remains necessary to validate the complete user workflow. |
| Desktop subtitles | Live XWayland window verified with transparent English/Japanese captions, exact positioning, always-on-top, click-through and unlock/relock. The main application remains native Wayland. |
| VR subtitles | Native Pango/Cairo text rendering and Vulkan/OpenXR presentation. An isolated Monado simulated-headset test passed on the RX 7900 XT, including scene changes, positioning, visibility and shutdown. Physical headset appearance and comfort still need wearer confirmation. |
| Clipboard translation | Event-driven `wl-paste` on Wayland; skips sensitive clipboard events, bounds input size and stops owned watcher processes. Starts only when enabled. |
| Application control and credentials | Private POSIX instance locks and authenticated local control; Secret Service save/read/delete verified with a temporary credential. |
| Windows builds | Original Windows paths and adapters are retained. This Linux machine cannot validate a new Windows release artifact. |

Per-application selection currently lists applications with active PulseAudio playback streams. Pure JACK applications and native PipeWire clients that bypass the PulseAudio compatibility layer are not included. SteamVR runtimes without `XR_EXTX_overlay` cannot present this Linux overlay alongside the main VR application.

### Measured local model smoke tests

These short functional checks used public speech samples and simple conversational text. They are not comprehensive accuracy benchmarks or full conversational latency measurements.

| Check | CPU | RX 7900 XT Vulkan |
| --- | ---: | ---: |
| English speech, 11 seconds | 0.761 s decode | 0.213 s decode |
| Japanese speech, 5.08 seconds | 0.480 s decode | 0.121 s decode |
| English → Japanese, short message | 0.644 s | 0.219 s |
| Japanese → English, short message | 0.519 s | 0.162 s |

CPU and GPU produced the same Japanese speech transcription and preserved the meaning of both translation samples. Translation times exclude first-time model/prefix preparation. First translation preparation took approximately 1.28 seconds on Vulkan and 5.19 seconds on CPU in this test. Other audio, message lengths, hardware and simultaneous games change these results.

The initial 2.7.0 Linux stability pass completed 6,751 Python tests with 53 skipped. Native validation passed 10 speech-worker and 252 overlay tests. Regressions cover capture startup, device selection, peer-language labels, OSC transitions and failure recovery. The installed desktop launcher, saved settings, real microphone start/stop, caption controls and credential storage were also checked. Physical headset and account-backed cloud services remain outside these completed checks.

### Stability pass — October 3, 2026

Failure injection reproduced and fixed five lifecycle problems:

- Restart GPU now clears a failed worker state even when the failure has stopped both capture channels. It leaves capture stopped until explicitly enabled again.
- OSC shutdown cancels blocked discovery instead of waiting indefinitely.
- Reapplying a manual OSC endpoint retries its receiver after another program releases the port.
- Clipboard shutdown terminates owned helper processes even when their parent has already exited, preventing a blocked pipe from hanging cleanup.
- Desktop caption operations tolerate an X11 window disappearing between lookup and use.

The longer translation run also exposed unnecessary RAM growth from llama.cpp's default 8 GiB historical prompt-cache budget. The server now uses `--cache-ram 0`, while retaining prompt caching in the three resident slots and the application's disk prefix cache. Across 24 simultaneous self/peer utterance pairs (48 outputs), the last eight server RSS samples stayed at about 2,136 MiB with only 4 KiB growth; the default-cache run grew from 3,796 to 4,262 MiB over the same final eight pairs. Median recognition-to-translation latency was 0.397 s versus 0.402 s, with all outputs succeeding and no orphaned workers after shutdown. These figures describe server RAM, not GPU VRAM.

| Check | Observed result |
| --- | --- |
| Host/control lifecycle | 834 queries across four host lifetimes; concurrent queries, duplicate-launch refusal, idempotent setting changes, rejected invalid settings and restart after an intentional test-host kill passed. |
| Damaged settings | Truncated JSON and a future settings version were rejected at startup; original files remained intact and no live control endpoint remained. |
| Audio lifecycle | 12 generated-silence capture cycles, three per-app stream replacements, missing-device handling and forced helper exit passed. Test resources were removed and default audio routes stayed unchanged. |
| Speech lifecycle | Repeated CPU/GPU self and peer sessions, simultaneous utterances, live provider handoffs, rapid cancellation and real worker-kill/recovery passed. Stopping capture returned to 11 file descriptors, four async tasks and zero open fixture sources. |
| Desktop captions | Four launches verified transparency, placement and click-through, including recovery after an owned caption process was killed. A real destroyed X11 window was handled without exceptions. |
| Native VR captions | Five isolated simulated-headset runs and failures involving runtime/service absence, bridge disconnection and runtime loss exited correctly with no orphaned child processes. |
| OSC | 20 rapid mode-change cycles plus port contention and blocked-discovery tests passed; Off cleared pending pages and peer captions stayed out of the chatbox. |
| Installed GUI idle | Over 60 seconds, the Python host used about 0.77% of one CPU core and the Flet child used 0%; file-descriptor counts stayed at 20/30 and combined RSS changed by about 24 KiB. Capture remained off. |

These bounded checks use isolated settings, public recorded speech and generated silence. They do not establish physical-headset compatibility, cloud-account operation or multi-day reliability. Detailed local probe results are retained under the ignored `diagnostics/stability/` directory.

### Upstream 2.8.0 integration — October 5, 2026

This update incorporates 19 upstream commits from `991ef0bd` through `0f9ed03e`. It retains the Linux adapters and stability fixes while adding upstream speech diagnostics and recovery, independent caption delivery, ChatGPT connection-pool admission and model-specific prompts, the activation-notice setting, and revised provider/account UI. Upstream's Windows-native packaging changes remain Windows-specific.

The previous permissive GPU ingress workaround is replaced by upstream's explicit backend preparation. Recorded-audio validation exposed one additional case: selecting GPU recognition while stopped could leave an attached but unprepared provider, causing the next TALK activation to fail with `gpu_not_ready`. The readiness adapter now requires a ready GPU with the self channel active, so the normal capture-start path prepares that dormant provider before admitting audio. Regression coverage includes both idle GPU and already-active peer cases; existing peer ownership remains intact.

The refreshed `uv.lock` includes Linux `python-xlib` and cross-platform `psutil`, while keeping Windows capture dependencies platform-specific. A separate checkout and virtual environment were used throughout; the installed app and user settings were not updated.

The Linux speech worker, GTK shim and OpenXR overlay built successfully. Native tests passed 10 speech-worker and 254 overlay cases, including Python-to-native caption lifecycle checks. The overlay test suite requires `uv` on PATH; the Linux application installer itself does not. The rebuilt overlay passed an isolated Monado simulated-headset run with caption updates, visibility changes and clean shutdown. Recorded Japanese GPU self/peer sessions, live CPU↔GPU handoffs, forced speech-worker termination and manual recovery, and English CPU/GPU self/peer recognition plus local translation passed in an 88-second run. Twelve fixture sources closed, no worker processes survived shutdown, and no user microphone or live VRChat OSC was used. The final Python suite passed 7,137 tests with 68 skipped; Ruff, the locked dependency environment, shell syntax and diff checks also passed. Physical-headset/live VRChat, cloud-account and Windows artifact checks remain unverified.

## Updates and removal

Linux uses source updates rather than upstream Windows installers. After reviewing and pulling updates to this fork, rerun `scripts/linux/install-user.sh`. Native builds remain reproducible against the committed Cargo locks and pinned llama.cpp archive identities; Python dependency versions follow `pyproject.toml` and the resolved virtual environment.

Removing the user launchers, desktop entry and `puripuly-heart.png` icon removes desktop integration. The checkout and its `.venv` can then be removed. Keep `~/.config/puripuly-heart` if you want to preserve settings, downloaded models, account references and logs. Do not remove another installation's shared settings accidentally.
