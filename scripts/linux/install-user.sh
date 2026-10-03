#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_root"
skip_native=0
case ${1:-} in
    --skip-native) skip_native=1 ;;
    --help|-h)
        printf '%s\n' 'Usage: scripts/linux/install-user.sh [--skip-native]' 'Installs into this checkout and your user application menu; leaves settings intact.'
        exit 0 ;;
    '') ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
esac
if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
    printf '%s\n' 'This installer targets x86-64 Linux.' >&2
    exit 1
fi
task_python=${PURIPULY_SYSTEM_PYTHON:-python3.14}
"$task_python" -c 'import sys; assert sys.version_info[:2] == (3, 14), "Python 3.14 is required"'
if [[ ! -x .venv/bin/python ]]; then
    "$task_python" -m venv .venv
fi
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 14), "The checkout virtual environment must use Python 3.14"'
.venv/bin/python -m pip install -e .
if (( ! skip_native )); then
    scripts/linux/build-native.sh
fi
for native in build/desktop/libpuripuly-gtk-rgba.so build/gpu_worker/PuriPulyHeartGpuWorker build/overlay/PuriPulyHeartOverlay build/llama.cpp/llama.cpp-b10423/cpu/llama-server build/llama.cpp/llama.cpp-b10423/vulkan/llama-server; do
    if [[ ! -x "$native" ]]; then
        printf 'Missing native runtime: %s. Run scripts/linux/build-native.sh.\n' "$native" >&2
        exit 1
    fi
done
.venv/bin/python - "$repo_root" <<'PY'
import os
import shlex
import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1])
user_bin = Path.home() / ".local" / "bin"
data_root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
applications = data_root / "applications"
icon = data_root / "icons" / "hicolor" / "256x256" / "apps" / "puripuly-heart.png"
launchers = {
    "puripuly-heart": ("puripuly_heart.main", "run-gui"),
    "puripuly": ("puripuly_heart.cli.main",),
}
for name in launchers:
    path = user_bin / name
    if path.exists() and (not path.is_file() or "puripuly_heart" not in path.read_text(errors="replace")):
        raise SystemExit(f"Refusing to overwrite another program: {path}")
user_bin.mkdir(parents=True, exist_ok=True)
applications.mkdir(parents=True, exist_ok=True)
icon.parent.mkdir(parents=True, exist_ok=True)
for name, arguments in launchers.items():
    command = [str(root / ".venv" / "bin" / "python"), "-m", *arguments]
    path = user_bin / name
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\ncd -- " + shlex.quote(str(root)) + "\nexec " + shlex.join(command) + ' "$@"\n')
    path.chmod(0o755)
shutil.copyfile(root / "src/puripuly_heart/data/icons/icon.png", icon)
launcher = str(user_bin / "puripuly-heart")
launcher = launcher.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
entry = "\n".join((
    "[Desktop Entry]",
    "Type=Application",
    "Name=PuriPuly Heart",
    "Comment=Real-time speech translation and VR subtitles",
    f'Exec="{launcher}"',
    "Icon=puripuly-heart",
    "Terminal=false",
    "Categories=AudioVideo;Audio;",
    "Keywords=VRChat;translation;subtitles;speech;",
    "StartupNotify=true",
    "",
))
(applications / "puripuly-heart.desktop").write_text(entry)
print(f"Installed launchers in {user_bin} and desktop entry in {applications}")
print(f"Keep this checkout at {root}; the launchers use its virtual environment and native builds.")
PY
if command -v update-desktop-database >/dev/null; then
    update-desktop-database "${XDG_DATA_HOME:-$HOME/.local/share}/applications"
fi
printf '%s\n' 'Launch PuriPuly Heart from the application menu, or run ~/.local/bin/puripuly-heart.'
