from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass

from puripuly_heart.config.audio_host_api import LINUX_AUDIO_HOST_API as LINUX_AUDIO_HOST_API
from puripuly_heart.config.process_capture_platform import ProcessCapturePlatformAvailability
from puripuly_heart.config.process_capture_resolution import ProcessCaptureResolver, ProcessSnapshot
from puripuly_heart.core.audio.process_identity import (
    linux_process_executable as linux_process_executable,
)


def pulse_command(*args: str) -> str:
    result = subprocess.run(
        ["pactl", *args], capture_output=True, text=True, timeout=5, check=False
    )
    if result.returncode:
        raise RuntimeError("Cannot connect to PipeWire/PulseAudio. Is pipewire-pulse running?")
    return result.stdout.strip()


def pulse_list(kind: str) -> list[dict]:
    value = json.loads(pulse_command("--format=json", "list", kind))
    if not isinstance(value, list):
        raise RuntimeError("Unexpected PulseAudio inventory response")
    return value


@dataclass(frozen=True, slots=True)
class PulseDevice:
    index: int
    name: str
    label: str
    channels: int
    sample_rate_hz: int
    monitor: str | None = None


def audio_devices(*, outputs: bool = False) -> tuple[PulseDevice, ...]:
    devices = []
    for entry in pulse_list("sinks" if outputs else "sources"):
        properties = entry.get("properties", {})
        if not outputs and (
            properties.get("device.class") == "monitor"
            or entry.get("name", "").endswith(".monitor")
        ):
            continue
        match = re.search(r"(\d+)ch\s+(\d+)Hz", entry.get("sample_specification", ""))
        if not match:
            continue
        name = str(entry["name"])
        devices.append(
            PulseDevice(
                index=int(entry["index"]),
                name=name,
                label=str(entry.get("description") or name),
                channels=int(match[1]),
                sample_rate_hz=int(match[2]),
                monitor=str(entry.get("monitor_source") or name + ".monitor") if outputs else None,
            )
        )
    return tuple(devices)


def resolve_pulse_device(value: int | str | None, *, outputs: bool = False) -> PulseDevice:
    devices = audio_devices(outputs=outputs)
    if value is None or value == "":
        value = pulse_command("get-default-sink" if outputs else "get-default-source")
    for device in devices:
        if value in (device.index, str(device.index), device.name, device.label):
            return device
    raise RuntimeError(
        "Selected audio device is unavailable; select a connected device in Settings"
    )


def process_streams(pid: int) -> list[dict]:
    import psutil

    process = psutil.Process(pid)
    pids = {pid}
    try:
        pids.update(child.pid for child in process.children(recursive=True))
    except psutil.Error:
        pass
    return [
        item
        for item in pulse_list("sink-inputs")
        if str(item.get("properties", {}).get("application.process.id", ""))
        in {str(item) for item in pids}
    ]


class LinuxAudioProcessSnapshots:
    def snapshots(self) -> tuple[ProcessSnapshot, ...]:
        import psutil

        snapshots = {}
        for item in pulse_list("sink-inputs"):
            try:
                process = psutil.Process(int(item["properties"]["application.process.id"]))
                if process.uids().real != os.getuid():
                    continue
                executable = linux_process_executable(process)
                while (parent := process.parent()) is not None and linux_process_executable(
                    parent
                ) == executable:
                    process = parent
                snapshots[process.pid] = ProcessSnapshot(
                    pid=process.pid,
                    parent_pid=None,
                    is_current_user=True,
                    executable_path=executable,
                    instance_id=f"{process.pid}:{process.create_time()}",
                )
            except psutil.Error, KeyError, ValueError:
                continue
        return tuple(snapshots.values())


class LinuxProcessCaptureResolver(ProcessCaptureResolver):
    def __init__(self) -> None:
        super().__init__(
            snapshots=LinuxAudioProcessSnapshots(),
            platform_availability=lambda: ProcessCapturePlatformAvailability(available=True),
        )
