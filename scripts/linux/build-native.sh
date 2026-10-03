#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_root"
task_python=${PURIPULY_PYTHON:-"$repo_root/.venv/bin/python"}

if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
    printf '%s\n' 'This build targets x86-64 Linux.' >&2
    exit 1
fi
for tool in cc cargo cmake pkg-config glslc; do
    if ! command -v "$tool" >/dev/null; then
        printf 'Missing build tool: %s. See docs/Linux.md.\n' "$tool" >&2
        exit 1
    fi
done
if [[ ! -x "$task_python" ]]; then
    printf '%s\n' 'Create the application virtual environment first with scripts/linux/install-user.sh.' >&2
    exit 1
fi
pkg-config --exists cairo pangocairo pango vulkan gtk+-3.0
mkdir -p build/desktop
cc -shared -fPIC -O2 -Wall -Wextra -o build/desktop/libpuripuly-gtk-rgba.so native/linux/gtk_rgba.c $(pkg-config --cflags --libs gtk+-3.0) -ldl
export CARGO_TARGET_DIR=${CARGO_TARGET_DIR:-"$repo_root/target"}
export CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS:-4}
export TRANSCRIBE_CMAKE_ARGS="${TRANSCRIBE_CMAKE_ARGS:+$TRANSCRIBE_CMAKE_ARGS }-DTRANSCRIBE_USE_SYSTEM_BLAS=OFF"
cargo build --release --locked --manifest-path native/gpu_worker/Cargo.toml
cargo build --release --locked --manifest-path native/overlay/Cargo.toml
install -Dm755 "$CARGO_TARGET_DIR/release/PuriPulyHeartGpuWorker" build/gpu_worker/PuriPulyHeartGpuWorker
install -Dm755 "$CARGO_TARGET_DIR/release/PuriPulyHeartOverlay" build/overlay/PuriPulyHeartOverlay
"$task_python" -m puripuly_heart.release_evidence.linux_managed_gemma_distribution --cache-dir build/llama-cache
printf '%s\n' 'Native speech, subtitle overlay and local translation runtimes are ready.'
