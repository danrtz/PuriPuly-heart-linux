from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
from collections.abc import Callable

from puripuly_heart.core.clipboard.watcher import ClipboardWatcherError
from puripuly_heart.core.runtime_logging import emit_basic_log

logger = logging.getLogger(__name__)
_MAX_BYTES = 65536
_COPY_TEXT = """
import json, os, sys
if os.environ.get('CLIPBOARD_STATE', 'data') == 'data':
    data = sys.stdin.buffer.read(65537)
    if len(data) <= 65536:
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            pass
        else:
            print(json.dumps(text), flush=True)
"""


class LinuxClipboardWatcher:
    def __init__(self, on_text: Callable[[str], None]) -> None:
        self._on_text = on_text
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._last_text: str | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        executable = shutil.which("wl-paste")
        if not executable or not os.environ.get("WAYLAND_DISPLAY"):
            raise ClipboardWatcherError("Clipboard translation requires Wayland and wl-clipboard")
        self.stop()
        self._stop.clear()
        self._last_text = None
        initial = subprocess.Popen(
            [executable, "--no-newline", "--type", "text"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            snapshot = subprocess.run(
                [sys.executable, "-c", _COPY_TEXT],
                stdin=initial.stdout,
                capture_output=True,
                timeout=1.0,
                check=False,
            )
            if snapshot.stdout:
                self._last_text = json.loads(snapshot.stdout).strip()
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        finally:
            if initial.stdout is not None:
                initial.stdout.close()
            if initial.poll() is None:
                initial.terminate()
            try:
                initial.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                initial.kill()
                initial.wait(timeout=1.0)
        self._process = subprocess.Popen(
            [
                executable,
                "--no-newline",
                "--type",
                "text",
                "--watch",
                sys.executable,
                "-c",
                _COPY_TEXT,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if self._stop.wait(0.1) or self._process.poll() is not None:
            self.stop()
            raise ClipboardWatcherError(
                "Cannot watch this Wayland clipboard; check wl-clipboard support"
            )
        self._thread = threading.Thread(
            target=self._watch, name="PuriPulyClipboardWatcher", daemon=True
        )
        self._thread.start()

    def _watch(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        while not self._stop.is_set():
            line = process.stdout.readline(_MAX_BYTES * 6 + 16)
            if not line:
                break
            try:
                text = json.loads(line)
                if not isinstance(text, str):
                    continue
                text = text.strip()
                if not text or text == self._last_text:
                    continue
                self._last_text = text
                self._on_text(text)
            except Exception:
                emit_basic_log(
                    logger,
                    "[Clipboard] Clipboard text could not be submitted.",
                    level=logging.ERROR,
                )

    def stop(self) -> None:
        self._stop.set()
        process = self._process
        if process is not None:
            if process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=1.0)
            if self._thread is not None and self._thread is not threading.current_thread():
                self._thread.join(timeout=2.0)
            if process.stdout is not None:
                process.stdout.close()
        self._process = None
        self._thread = None
        self._last_text = None
