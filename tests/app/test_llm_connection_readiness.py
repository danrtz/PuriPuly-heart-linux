from __future__ import annotations

import asyncio
from types import SimpleNamespace

from puripuly_heart.app.adapters.ui_runtime import (
    UiInputRuntimeAdapter,
    UiPeerCaptureRuntimeAdapter,
)
from puripuly_heart.app.services.llm_connection_readiness import LlmConnectionReadinessOwner


class _Pool:
    def __init__(self) -> None:
        self.prepared = 0
        self.gate: asyncio.Event | None = None

    async def prepare_connections(self) -> None:
        self.prepared += 1
        if self.gate is not None:
            await self.gate.wait()


def _wrapped(pool: _Pool) -> object:
    racing = SimpleNamespace(primary=pool)
    semaphore = SimpleNamespace(inner=racing)
    return SimpleNamespace(provider=semaphore)


def _owner(pool: _Pool, state: dict[str, bool]) -> LlmConnectionReadinessOwner:
    return LlmConnectionReadinessOwner(
        llm_provider=lambda: _wrapped(pool),
        translation_enabled=lambda: state["translation"],
        capture_active=lambda: state["capture"],
    )


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_connections_open_only_when_translation_and_capture_are_both_on() -> None:
    pool = _Pool()
    state = {"translation": True, "capture": False}
    owner = _owner(pool, state)

    owner.sync()
    await _settle()
    assert pool.prepared == 0

    state.update(translation=False, capture=True)
    owner.sync()
    await _settle()
    assert pool.prepared == 0

    state["translation"] = True
    owner.sync()
    await _settle()
    assert pool.prepared == 1
    await owner.close()


async def test_repeated_toggles_do_not_stack_preparation() -> None:
    pool = _Pool()
    pool.gate = asyncio.Event()
    owner = _owner(pool, {"translation": True, "capture": True})

    owner.sync()
    owner.sync()
    await _settle()
    assert pool.prepared == 1

    await owner.close()


async def test_providers_without_connection_pool_are_ignored() -> None:
    owner = LlmConnectionReadinessOwner(
        llm_provider=lambda: SimpleNamespace(provider=SimpleNamespace(inner=None)),
        translation_enabled=lambda: True,
        capture_active=lambda: True,
    )
    owner.sync()
    await _settle()
    await owner.close()


async def test_talk_and_listen_toggles_request_readiness_after_state_changes() -> None:
    pool = _Pool()
    state = {"translation": True, "capture": False}
    owner = _owner(pool, state)

    async def set_self_enabled(enabled: bool) -> bool:
        state["capture"] = enabled
        return True

    async def set_peer_enabled(enabled: bool) -> bool:
        state["capture"] = enabled
        return True

    input_runtime = UiInputRuntimeAdapter(
        pipeline=SimpleNamespace(),
        manual_typing=SimpleNamespace(),
        translation=SimpleNamespace(),
        self_capture=SimpleNamespace(set_enabled=set_self_enabled),
        connection_readiness=owner,
    )
    peer_runtime = UiPeerCaptureRuntimeAdapter(
        peer=SimpleNamespace(owner=SimpleNamespace(set_enabled=set_peer_enabled)),
        overlay=SimpleNamespace(),
        connection_readiness=owner,
    )

    await input_runtime.set_stt_enabled(True)
    await _settle()
    assert pool.prepared == 1

    await peer_runtime.set_peer_translation_enabled(False)
    await peer_runtime.set_peer_translation_enabled(True)
    await _settle()
    assert pool.prepared == 2
    await owner.close()


class _ReleasablePool(_Pool):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    async def prepare_connections(self) -> None:
        self.calls.append("prepare")
        await super().prepare_connections()

    async def release_connections(self) -> None:
        self.calls.append("release")


async def test_connections_are_released_when_translation_or_both_captures_stop() -> None:
    pool = _ReleasablePool()
    state = {"translation": True, "capture": True}
    owner = LlmConnectionReadinessOwner(
        llm_provider=lambda: _wrapped(pool),
        translation_enabled=lambda: state["translation"],
        capture_active=lambda: state["capture"],
    )

    owner.sync()
    state["capture"] = False
    owner.sync()
    await _settle()
    assert pool.calls == ["prepare", "release"]

    state["capture"] = True
    owner.sync()
    await _settle()
    state["translation"] = False
    owner.sync()
    await _settle()
    assert pool.calls == ["prepare", "release", "prepare", "release"]
    await owner.close()
