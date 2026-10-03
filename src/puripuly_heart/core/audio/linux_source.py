from __future__ import annotations

import asyncio
import contextlib
import queue
import subprocess
import threading
import time
from collections.abc import AsyncIterator

import janus
import numpy as np

from puripuly_heart.core.audio.format import AudioFrameF32
from puripuly_heart.core.audio.linux_inventory import (
    LINUX_AUDIO_HOST_API,
    process_streams,
    pulse_list,
    resolve_pulse_device,
)
from puripuly_heart.core.audio.source import (
    MicrophoneTestRouteObservation,
    PhysicalCaptureProgression,
    SelfMicCaptureChannelDecision,
    SoundDeviceInputMetadata,
)


class PulseAudioSource:
    def __init__(
        self,
        *,
        device: str,
        sample_rate_hz: int,
        channels: int,
        stream_index: int | None = None,
        max_queue_frames: int = 64,
    ) -> None:
        if sample_rate_hz <= 0 or channels <= 0 or max_queue_frames <= 0:
            raise ValueError("Audio format and queue capacity must be positive")
        self.actual_sample_rate_hz = sample_rate_hz
        self.opened_channels = self.frame_channels = self.requested_channels = channels
        self._queue = janus.Queue(maxsize=max_queue_frames)
        self._progression = PhysicalCaptureProgression(sample_rate_hz=sample_rate_hz)
        self.queue_drop_count = 0
        self._closed = False
        self._error = None
        command = [
            "parec",
            "--raw",
            "--format=float32le",
            f"--rate={sample_rate_hz}",
            f"--channels={channels}",
            f"--device={device}",
            "--client-name=PuriPuly Heart",
            "--stream-name=PuriPuly capture",
            "--latency-msec=40",
            "--process-time-msec=20",
        ]
        if stream_index is not None:
            command.append(f"--monitor-stream={stream_index}")
        try:
            self._process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        except Exception:
            self._queue.close()
            raise
        self._thread = threading.Thread(target=self._read, daemon=True, name="puripuly-pulse")
        self._thread.start()

    @property
    def capture_progression_snapshot(self):
        return self._progression.snapshot

    def _read(self) -> None:
        count = max(1, self.actual_sample_rate_hz // 50)
        size = count * self.opened_channels * 4
        try:
            while not self._closed:
                data = self._process.stdout.read(size)
                if not data:
                    if not self._closed:
                        self._error = RuntimeError(
                            "Audio capture ended: device or stream disconnected"
                        )
                    break
                if len(data) % (self.opened_channels * 4):
                    self._error = RuntimeError("Audio capture returned an incomplete PCM frame")
                    break
                samples = (
                    np.frombuffer(data, dtype="<f4").reshape((-1, self.opened_channels)).copy()
                )
                capture = self._progression.observe_frame(
                    sample_count=len(samples),
                    observed_at_monotonic_s=time.monotonic(),
                )
                frame = AudioFrameF32(
                    samples=samples,
                    channels=self.opened_channels,
                    sample_rate_hz=self.actual_sample_rate_hz,
                    capture=capture,
                )
                try:
                    self._queue.sync_q.put_nowait(frame)
                    self._progression.mark_admitted(capture)
                except queue.Full:
                    self.queue_drop_count += 1
        except Exception as exc:
            if not self._closed:
                self._error = exc
        finally:
            with contextlib.suppress(Exception):
                self._queue.sync_q.put_nowait(None)

    async def frames(self) -> AsyncIterator[AudioFrameF32]:
        while not self._closed:
            if not self._thread.is_alive() and self._queue.async_q.empty():
                if self._error:
                    raise self._error
                return
            item = await self._queue.async_q.get()
            if item is None:
                if self._error:
                    raise self._error
                return
            yield item

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await asyncio.to_thread(self._stop)
        self._queue.close()
        await self._queue.wait_closed()

    def _stop(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=1)
        self._thread.join(timeout=1)
        if self._process.stdout:
            self._process.stdout.close()


class LinuxMicrophoneAudioSource(PulseAudioSource):
    def __init__(self, *, sample_rate_hz=None, channels=1, device=None, **kwargs) -> None:
        selected = resolve_pulse_device(device)
        super().__init__(
            device=selected.name,
            sample_rate_hz=sample_rate_hz or selected.sample_rate_hz,
            channels=min(channels, selected.channels),
        )


class LinuxLoopbackAudioSource(PulseAudioSource):
    def __init__(self, *, device_name="", **kwargs) -> None:
        selected = resolve_pulse_device(device_name, outputs=True)
        self.resolved_device_name = selected.name
        self.resolved_device_index = selected.index
        self.resolved_channels = min(selected.channels, 2)
        self.used_default_fallback = False
        super().__init__(
            device=selected.monitor,
            sample_rate_hz=selected.sample_rate_hz,
            channels=self.resolved_channels,
        )


def resolve_linux_input_device(*, host_api="", device="") -> int:
    return resolve_pulse_device(device).index


def determine_linux_mic_capture_channels(*, device_idx, internal_channels):
    selected = resolve_pulse_device(device_idx)
    return SelfMicCaptureChannelDecision(
        device_idx=selected.index,
        internal_channels=internal_channels,
        preferred_capture_channels=min(selected.channels, 2),
        metadata=SoundDeviceInputMetadata(
            device_idx=selected.index,
            name=selected.label,
            max_input_channels=selected.channels,
            default_samplerate=float(selected.sample_rate_hz),
            metadata_status="ok",
        ),
    )


def observe_linux_microphone_test_route(*, saved_host_api="", requested_device=""):
    try:
        selected = resolve_pulse_device(requested_device)
        return MicrophoneTestRouteObservation(
            saved_host_api=saved_host_api,
            actual_host_api=LINUX_AUDIO_HOST_API,
            requested_device=requested_device,
            hostapi_index=None,
            resolved_device_idx=selected.index,
            resolved_device_name=selected.label,
            resolution_exception_class=None,
            resolution_exception_message=None,
            should_attempt_open=True,
        )
    except Exception as exc:
        return MicrophoneTestRouteObservation(
            saved_host_api=saved_host_api,
            actual_host_api=LINUX_AUDIO_HOST_API,
            requested_device=requested_device,
            hostapi_index=None,
            resolved_device_idx=None,
            resolved_device_name=None,
            resolution_exception_class=type(exc).__name__,
            resolution_exception_message=str(exc),
            should_attempt_open=False,
        )


class LinuxProcessAudioSource:
    def __init__(self, *, identity, watcher) -> None:
        self.identity = identity
        self._closed = False
        self.terminal_reason = None
        self._sources = {}
        self._tasks = {}
        self._bindings = {}
        self._failures = {}
        self._resource_lock = asyncio.Lock()
        self._progression = PhysicalCaptureProgression(sample_rate_hz=48000)
        self._watch = watcher.watch(identity, self._on_terminal)
        if not self._watch.identity_verified:
            self._watch.close()
            raise RuntimeError("Application capture target exited or changed identity")

    def _on_terminal(self) -> None:
        self.terminal_reason = "target_exited"

    @property
    def capture_progression_snapshot(self):
        return self._progression.snapshot

    async def _refresh(self) -> None:
        async with self._resource_lock:
            if not self._closed and self.terminal_reason is None:
                await self._refresh_streams()

    async def _refresh_streams(self) -> None:
        streams = await asyncio.to_thread(process_streams, self.identity.pid)
        sinks = {int(item["index"]): item for item in await asyncio.to_thread(pulse_list, "sinks")}
        if self._closed or self.terminal_reason is not None:
            return
        bindings = {}
        for item in streams:
            sink = sinks.get(int(item["sink"]))
            if sink:
                bindings[int(item["index"])] = str(sink["monitor_source"])
        for index in tuple(self._sources):
            if bindings.get(index) != self._bindings.get(index):
                await self._remove(index)
                self._progression.observe_unknown_discontinuity(
                    observed_at_monotonic_s=time.monotonic()
                )
        for index, monitor in bindings.items():
            if self._closed or self.terminal_reason is not None:
                return
            if index not in self._sources:
                source = PulseAudioSource(
                    device=monitor, sample_rate_hz=48000, channels=2, stream_index=index
                )
                self._sources[index] = source
                self._bindings[index] = monitor
                iterator = source.frames()
                self._tasks[index] = (iterator, asyncio.create_task(anext(iterator)))

    async def _remove(self, index) -> None:
        pair = self._tasks.pop(index, None)
        if pair is None:
            return
        raw_source = self._sources.pop(index)
        self._bindings.pop(index, None)
        iterator, task = pair
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        await raw_source.close()
        await iterator.aclose()
        self._bindings.pop(index, None)

    async def frames(self) -> AsyncIterator[AudioFrameF32]:
        refreshed = 0.0
        deadline = time.monotonic()
        try:
            while not self._closed and self.terminal_reason is None:
                now = time.monotonic()
                if now - refreshed >= 0.5:
                    await self._refresh()
                    refreshed = time.monotonic()
                if not self._tasks:
                    await asyncio.sleep(0.05)
                    continue
                deadline = max(deadline + 0.02, time.monotonic())
                await asyncio.sleep(max(0.0, deadline - time.monotonic()))
                ready = [index for index, pair in self._tasks.items() if pair[1].done()]
                if not ready:
                    continue
                frames = []
                for index in ready:
                    pair = self._tasks.get(index)
                    if pair is None or self._closed:
                        continue
                    iterator, task = pair
                    try:
                        frame = task.result()
                    except StopAsyncIteration, RuntimeError:
                        self._failures[index] = self._failures.get(index, 0) + 1
                        await self._remove(index)
                        if self._failures[index] >= 3:
                            raise RuntimeError("Application audio stream capture repeatedly failed")
                        self._progression.observe_unknown_discontinuity(
                            observed_at_monotonic_s=time.monotonic()
                        )
                        continue
                    self._failures.pop(index, None)
                    frames.append(frame)
                    self._tasks[index] = (iterator, asyncio.create_task(anext(iterator)))
                if frames:
                    samples = mix_process_frames(frames)
                    capture = self._progression.observe_frame(
                        sample_count=len(samples),
                        observed_at_monotonic_s=time.monotonic(),
                        unknown_discontinuity=any(
                            frame.capture and frame.capture.discontinuity_before for frame in frames
                        ),
                    )
                    self._progression.mark_admitted(capture)
                    yield AudioFrameF32(
                        samples=samples, sample_rate_hz=48000, channels=2, capture=capture
                    )
        finally:
            await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await asyncio.to_thread(self._watch.close)
        async with self._resource_lock:
            for index in tuple(self._sources):
                await self._remove(index)


def mix_process_frames(frames: list[AudioFrameF32]) -> np.ndarray:
    samples = np.zeros((max(len(frame.samples) for frame in frames), 2), dtype=np.float32)
    for frame in frames:
        samples[: len(frame.samples)] += frame.samples
    return np.clip(samples, -1, 1)
