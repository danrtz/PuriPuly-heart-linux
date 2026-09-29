from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field

_WRAPPER_ATTRIBUTES = ("provider", "inner", "primary")
_MAX_WRAPPER_DEPTH = 6


async def _call_connection_pool(llm: object | None, method_name: str) -> bool:
    current = llm
    for _ in range(_MAX_WRAPPER_DEPTH):
        if current is None:
            return False
        method = getattr(current, method_name, None)
        if callable(method):
            result = method()
            if inspect.isawaitable(result):
                await result
            return True
        current = next(
            (
                getattr(current, name)
                for name in _WRAPPER_ATTRIBUTES
                if getattr(current, name, None) is not None
            ),
            None,
        )
    return False


async def prepare_llm_connections(llm: object | None) -> bool:
    return await _call_connection_pool(llm, "prepare_connections")


async def release_llm_connections(llm: object | None) -> bool:
    return await _call_connection_pool(llm, "release_connections")


@dataclass(slots=True)
class LlmConnectionReadinessOwner:
    llm_provider: Callable[[], object | None]
    translation_enabled: Callable[[], bool]
    capture_active: Callable[[], bool]
    _task: asyncio.Task[bool] | None = field(init=False, default=None, repr=False)
    _task_action: str | None = field(init=False, default=None, repr=False)

    def sync(self) -> None:
        action = "prepare" if self.translation_enabled() and self.capture_active() else "release"
        task = self._task
        if task is not None and not task.done() and self._task_action == action:
            return
        self._task_action = action
        self._task = asyncio.get_running_loop().create_task(
            self._run(action, task), name=f"llm-connection-{action}"
        )

    async def close(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _run(self, action: str, previous: asyncio.Task[bool] | None) -> bool:
        if previous is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await previous
        try:
            if action == "prepare":
                return await prepare_llm_connections(self.llm_provider())
            return await release_llm_connections(self.llm_provider())
        except Exception:
            return False


__all__ = [
    "LlmConnectionReadinessOwner",
    "prepare_llm_connections",
    "release_llm_connections",
]
