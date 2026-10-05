from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

from puripuly_heart.config.process_capture_platform import (
    PROCESS_CAPTURE_MIN_WINDOWS_BUILD,
    evaluate_process_capture_platform,
    get_process_capture_platform_availability,
)


@pytest.mark.parametrize(
    ("system_name", "implementation", "python_version", "machine", "windows_build", "reason"),
    [
        ("Darwin", "CPython", (3, 14), "AMD64", 20348, "unsupported_system"),
        ("Windows", "PyPy", (3, 14), "AMD64", 20348, "unsupported_implementation"),
        ("Windows", "CPython", (3, 13), "AMD64", 20348, "unsupported_python"),
        ("Windows", "CPython", (3, 14), "ARM64", 20348, "unsupported_machine"),
        ("Windows", "CPython", (3, 14), "AMD64", 20347, "unsupported_windows_build"),
        ("Windows", "CPython", (3, 14), "AMD64", None, "unsupported_windows_build"),
    ],
)
def test_process_capture_platform_validation_fails_closed(
    system_name: str,
    implementation: str,
    python_version: tuple[int, int],
    machine: str,
    windows_build: int | None,
    reason: str,
) -> None:
    availability = evaluate_process_capture_platform(
        system_name=system_name,
        implementation=implementation,
        python_version=python_version,
        machine=machine,
        windows_build=windows_build,
    )

    assert availability.available is False
    assert availability.reason == reason


def test_process_capture_platform_validation_accepts_only_the_supported_target() -> None:
    availability = evaluate_process_capture_platform(
        system_name="Windows",
        implementation="CPython",
        python_version=(3, 14),
        machine="AMD64",
        windows_build=PROCESS_CAPTURE_MIN_WINDOWS_BUILD,
    )

    assert availability.available is True
    assert availability.reason is None


def test_linux_capture_uses_native_tools_without_importing_proctap(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "proctap", raising=False)
    module = importlib.import_module("puripuly_heart.config.process_capture_platform")
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/" + name)

    availability = get_process_capture_platform_availability()

    assert availability.available is True
    assert availability.reason is None
    assert "proctap" not in sys.modules


def test_linux_capture_reports_missing_native_tools(monkeypatch):
    module = importlib.import_module("puripuly_heart.config.process_capture_platform")
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    availability = get_process_capture_platform_availability()
    assert availability.available is False
    assert availability.reason == "missing_pulseaudio_tools"
