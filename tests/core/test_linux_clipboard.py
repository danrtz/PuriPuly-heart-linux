import os
import subprocess
import sys

import pytest

from puripuly_heart.core.clipboard.linux import _COPY_TEXT, LinuxClipboardWatcher
from puripuly_heart.core.clipboard.watcher import ClipboardWatcherError


@pytest.mark.parametrize(
    ("state", "text", "expected"),
    [
        ("data", "こんにちは\nworld", '"\\u3053\\u3093\\u306b\\u3061\\u306f\\nworld"\n'),
        ("sensitive", "password", ""),
        ("nil", "", ""),
        ("data", "x" * 65537, ""),
    ],
)
def test_clipboard_helper_unicode_and_sensitive_filter(state, text, expected):
    result = subprocess.run(
        [sys.executable, "-c", _COPY_TEXT],
        input=text,
        text=True,
        capture_output=True,
        env=dict(os.environ, CLIPBOARD_STATE=state),
        timeout=5,
    )
    assert result.returncode == 0
    assert result.stdout == expected


def test_missing_wayland_is_an_actionable_failure(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    watcher = LinuxClipboardWatcher(lambda _: None)
    with pytest.raises(ClipboardWatcherError, match="Wayland"):
        watcher.start()
    watcher.stop()


def test_wayland_watcher_delivers_changes_and_reaps_child(tmp_path, monkeypatch):
    import threading

    helper = tmp_path / "wl-paste"
    helper.write_text("""#!/usr/bin/python3
import json, sys, time
if '--watch' not in sys.argv:
    print('initial', end='')
else:
    print(json.dumps('initial'), flush=True)
    time.sleep(0.2)
    print(json.dumps('こんにちは'), flush=True)
    time.sleep(30)
""")
    helper.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("WAYLAND_DISPLAY", "isolated-test")
    received = []
    ready = threading.Event()

    def receive(text):
        received.append(text)
        ready.set()

    watcher = LinuxClipboardWatcher(receive)
    try:
        watcher.start()
        process = watcher._process
        assert ready.wait(3)
        assert received == ["こんにちは"]
    finally:
        watcher.stop()
    assert process.poll() is not None
