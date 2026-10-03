# PuriPuly Heart on Linux

This fork ports [kapitalismho/PuriPuly-heart](https://github.com/kapitalismho/PuriPuly-heart) to native Linux while keeping its interface, translation providers, conversation routing and settings model. It starts from upstream `991ef0bdf06d744ebb6e7aa6d8df5d4ee5f8ca46` (2.7.0). The development branch is `linux-port`.

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
| Local Vulkan speech recognition | Real RX 7900 XT discovery, model activation, English/Japanese recognition, authenticated IPC and shutdown passed. TALK correctly waits for speech before loading; full Japanese VAD → GPU recognition → English translation passed. |
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

The full Python suite passed 6,720 tests with 53 skipped. Native validation passed 10 speech-worker and 252 overlay tests. Follow-up regressions cover the final capture-startup, device-selection, peer-language labels and OSC-transition fixes. The installed desktop launcher, saved settings, real microphone start/stop, caption controls and credential storage were also checked. Physical headset and account-backed cloud services remain outside these completed checks.

## Updates and removal

Linux uses source updates rather than upstream Windows installers. After reviewing and pulling updates to this fork, rerun `scripts/linux/install-user.sh`. Native builds remain reproducible against the committed Cargo locks and pinned llama.cpp archive identities; Python dependency versions follow `pyproject.toml` and the resolved virtual environment.

Removing the user launchers, desktop entry and `puripuly-heart.png` icon removes desktop integration. The checkout and its `.venv` can then be removed. Keep `~/.config/puripuly-heart` if you want to preserve settings, downloaded models, account references and logs. Do not remove another installation's shared settings accidentally.
