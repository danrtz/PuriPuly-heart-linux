from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import numpy as np
import pytest

from puripuly_heart.config.settings_vnext.schema import ProcessCaptureTargetIntent
from puripuly_heart.core.audio import linux_inventory as inventory
from puripuly_heart.core.audio import linux_source as source
from puripuly_heart.core.audio.format import AudioFrameF32


@pytest.fixture
def devices(monkeypatch):
    values = [
        {
            "index": 11,
            "name": "headset",
            "description": "VR headset microphone",
            "sample_specification": "float32le 1ch 44100Hz",
            "properties": {},
        },
        {
            "index": 12,
            "name": "desktop.monitor",
            "description": "Monitor of speakers",
            "sample_specification": "s32le 2ch 48000Hz",
            "properties": {"device.class": "monitor"},
        },
    ]
    monkeypatch.setattr(inventory, "pulse_list", lambda kind: values)
    monkeypatch.setattr(inventory, "pulse_command", lambda *args: "headset")
    return values


def test_microphone_inventory_excludes_output_monitors_and_preserves_native_rate(devices):
    (selected,) = inventory.audio_devices()
    assert selected.name == "headset"
    assert selected.label == "VR headset microphone"
    assert selected.sample_rate_hz == 44100
    assert selected.channels == 1


def test_default_route_tracks_new_default_without_persisting_numeric_indices(devices, monkeypatch):
    assert inventory.resolve_pulse_device("").name == "headset"
    devices.append(
        {
            "index": 23,
            "name": "new-headset",
            "description": "New headset",
            "sample_specification": "float32le 1ch 48000Hz",
        }
    )
    monkeypatch.setattr(inventory, "pulse_command", lambda *args: "new-headset")
    assert inventory.resolve_pulse_device("").name == "new-headset"


def test_missing_saved_input_fails_instead_of_capturing_an_unrelated_microphone(devices):
    with pytest.raises(RuntimeError, match="unavailable"):
        inventory.resolve_pulse_device("disconnected-headset")
    observation = source.observe_linux_microphone_test_route(
        requested_device="disconnected-headset"
    )
    assert observation.should_attempt_open is False
    assert observation.resolved_device_idx is None


def test_native_process_identity_keeps_case_sensitive_posix_paths():
    target = ProcessCaptureTargetIntent.generic_executable("/opt/SomeApp/App")
    assert target.executable_identity == "/opt/SomeApp/App"
    assert target != ProcessCaptureTargetIntent.generic_executable("/opt/someapp/app")
    assert ProcessCaptureTargetIntent.vrchat("/mnt/Games/VRChat.exe").kind == "vrchat"


@pytest.mark.parametrize(
    "argument,expected",
    [
        ("/mnt/Games/VRChat.exe", "/mnt/Games/VRChat.exe"),
        (r"Z:\mnt\Games\VRChat.exe", "/mnt/Games/VRChat.exe"),
        (r"C:\Games\VRChat.exe", r"C:\Games\VRChat.exe"),
    ],
)
def test_proton_process_uses_game_identity_instead_of_shared_wine_binary(argument, expected):
    process = SimpleNamespace(exe=lambda: "/usr/bin/wine64-preloader", cmdline=lambda: [argument])
    assert inventory.linux_process_executable(process) == expected


def test_process_stream_selection_includes_children_and_excludes_unrelated_apps(monkeypatch):
    import psutil

    monkeypatch.setattr(
        psutil,
        "Process",
        lambda pid: SimpleNamespace(children=lambda recursive: [SimpleNamespace(pid=102)]),
    )
    monkeypatch.setattr(
        inventory,
        "pulse_list",
        lambda kind: [
            {"index": index, "properties": {"application.process.id": str(pid)}}
            for index, pid in ((1, 101), (2, 102), (3, 202))
        ],
    )
    assert [item["index"] for item in inventory.process_streams(101)] == [1, 2]


class FakeProcess:
    def __init__(self, data):
        self.stdout = io.BytesIO(data)
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def wait(self, timeout):
        return self.returncode


@pytest.mark.asyncio
async def test_stream_isolation_pcm_shape_and_helper_cleanup(monkeypatch):
    pcm = np.full((960, 2), 0.125, dtype="<f4")
    process = FakeProcess(pcm.tobytes())
    commands = []

    def popen(command, **kwargs):
        commands.append(command)
        return process

    monkeypatch.setattr(source.subprocess, "Popen", popen)
    capture = source.PulseAudioSource(
        device="speaker.monitor", sample_rate_hz=48000, channels=2, stream_index=84
    )
    iterator = capture.frames()
    frame = await asyncio.wait_for(anext(iterator), 1)
    assert frame.samples.shape == (960, 2)
    assert np.array_equal(frame.samples, pcm)
    assert "--monitor-stream=84" in commands[0]
    assert "--device=speaker.monitor" in commands[0]
    assert not any("force" in arg for arg in commands[0])
    with pytest.raises(RuntimeError, match="disconnected"):
        await anext(iterator)
    await capture.close()
    assert process.stdout.closed
    assert not capture._thread.is_alive()


def test_mixing_is_a_bounded_sum_without_stretching_or_concatenating_streams():
    frames = [
        AudioFrameF32(
            samples=np.full((960, 2), level, dtype=np.float32), sample_rate_hz=48000, channels=2
        )
        for level in (0.3, 0.5)
    ]
    mixed = source.mix_process_frames(frames)
    assert mixed.shape == (960, 2)
    assert np.allclose(mixed, 0.8)
    assert np.all(source.mix_process_frames(frames + frames) == 1)


@pytest.mark.asyncio
async def test_process_source_tracks_stream_replacements_and_never_uses_system_mix(monkeypatch):
    stream = {"index": 10, "sink": 1}
    monkeypatch.setattr(source, "process_streams", lambda pid: [dict(stream)])
    monkeypatch.setattr(
        source,
        "pulse_list",
        lambda kind: [
            {"index": 1, "monitor_source": "speakers.monitor"},
            {"index": 2, "monitor_source": "headphones.monitor"},
        ],
    )
    opened, closed = [], []

    class Capture:
        def __init__(self, **kwargs):
            self.args = kwargs
            opened.append(kwargs)

        async def frames(self):
            await asyncio.sleep(100)
            yield None

        async def close(self):
            closed.append(self.args)

    monkeypatch.setattr(source, "PulseAudioSource", Capture)
    watch = SimpleNamespace(identity_verified=True, close=lambda: None)
    watcher = SimpleNamespace(watch=lambda identity, callback: watch)
    capture = source.LinuxProcessAudioSource(identity=SimpleNamespace(pid=50), watcher=watcher)
    await capture._refresh()
    stream.update(index=11, sink=2)
    await capture._refresh()
    assert [item["stream_index"] for item in opened] == [10, 11]
    assert [item["device"] for item in opened] == ["speakers.monitor", "headphones.monitor"]
    assert len(closed) == 1
    await capture.close()
    assert len(closed) == 2
    assert not capture._tasks


@pytest.mark.asyncio
async def test_identity_mismatch_refuses_to_open_audio():
    closed = []
    watch = SimpleNamespace(identity_verified=False, close=lambda: closed.append(True))
    watcher = SimpleNamespace(watch=lambda identity, callback: watch)
    with pytest.raises(RuntimeError, match="identity"):
        source.LinuxProcessAudioSource(identity=SimpleNamespace(pid=50), watcher=watcher)
    assert closed == [True]


@pytest.mark.asyncio
async def test_closing_during_inventory_refresh_does_not_open_a_late_capture(monkeypatch):
    import threading

    entered, release = threading.Event(), threading.Event()

    def streams(pid):
        entered.set()
        release.wait(2)
        return [{"index": 1, "sink": 1}]

    monkeypatch.setattr(source, "process_streams", streams)
    monkeypatch.setattr(source, "pulse_list", lambda kind: [{"index": 1, "monitor_source": "mix"}])
    opened = []
    monkeypatch.setattr(source, "PulseAudioSource", lambda **kwargs: opened.append(kwargs))
    watcher = SimpleNamespace(
        watch=lambda *args: SimpleNamespace(identity_verified=True, close=lambda: None)
    )
    capture = source.LinuxProcessAudioSource(identity=SimpleNamespace(pid=50), watcher=watcher)
    refresh = asyncio.create_task(capture._refresh())
    await asyncio.to_thread(entered.wait, 2)
    close = asyncio.create_task(capture.close())
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(asyncio.gather(close, refresh), 2)
    assert not opened
    assert not capture._sources
