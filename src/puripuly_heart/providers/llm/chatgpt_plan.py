from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

import websockets
from websockets.exceptions import InvalidStatus

from puripuly_heart.config.runtime_resolution import OPENAI_MODEL_GPT_6_LUNA
from puripuly_heart.core.chatgpt.oauth import ChatGptAuthError, ChatGptReauthRequired
from puripuly_heart.core.chatgpt.session import ChatGptAccessTokenPort
from puripuly_heart.core.error_messages import format_error_report_for_log, provider_failure_report
from puripuly_heart.core.llm.latency import current_attempt
from puripuly_heart.core.llm.provider import LLMProvider
from puripuly_heart.core.observability import ProviderObservationPort
from puripuly_heart.domain.models import Translation
from puripuly_heart.providers.llm.messages import build_translation_user_message

logger = logging.getLogger(__name__)

CHATGPT_RESPONSES_WS_URL: Final = "wss://api.openai.com/v1/responses"
_SUBSCRIPTION_STATUS_BY_CODE: Final[Mapping[str, int]] = {
    "subscription_sharing_usage_limit_exceeded": 429,
    "subscription_sharing_user_not_eligible": 403,
    "subscription_sharing_invalid_user": 401,
    "subscription_sharing_usage_unavailable": 503,
    "subscription_sharing_user_unavailable": 503,
    "subscription_sharing_unsupported_capability": 400,
    "subscription_sharing_route_not_supported": 403,
}


class ChatGptPlanResponseError(RuntimeError):
    diagnostic_provider = "chatgpt"

    def __init__(self, status_code: int | None, code: str | None = None) -> None:
        self.status_code = status_code
        self.subscription_code = code
        detail = f"status={status_code}" + (f" code={code}" if code else "")
        super().__init__(f"ChatGPT plan request failed ({detail})")


WebSocketConnector = Callable[[str, Mapping[str, str]], Awaitable[Any]]


async def _connect_websocket(url: str, headers: Mapping[str, str]) -> Any:
    return await websockets.connect(
        url,
        additional_headers=dict(headers),
        max_size=None,
        ping_interval=20,
        ping_timeout=20,
        open_timeout=15,
    )


def _build_system_prompt(*, system_prompt: str, source_language: str, target_language: str) -> str:
    if "{source_language}" not in system_prompt:
        return system_prompt
    return system_prompt.format(source_language=source_language, target_language=target_language)


def _error_from_event(event: Mapping[str, object]) -> ChatGptPlanResponseError:
    kind = event.get("type")
    error: object = None
    status: object = None
    if kind == "error":
        error = event.get("error")
        status = event.get("status")
    else:
        response = event.get("response")
        if isinstance(response, Mapping):
            error = response.get("error") or response.get("incomplete_details")
    code = error.get("code") if isinstance(error, Mapping) else None
    code = code if isinstance(code, str) and code else None
    status_code = status if isinstance(status, int) else None
    if code in _SUBSCRIPTION_STATUS_BY_CODE:
        status_code = _SUBSCRIPTION_STATUS_BY_CODE[code]
    if status_code is None and kind == "response.incomplete":
        code = code or "incomplete"
    return ChatGptPlanResponseError(status_code, code)


@dataclass(slots=True)
class _PooledConnection:
    socket: Any
    token: str = field(repr=False)
    token_generation: int
    pool_epoch: int = 0


@dataclass(slots=True)
class ChatGptPlanLLMProvider(LLMProvider):
    session: ChatGptAccessTokenPort
    model: str = OPENAI_MODEL_GPT_6_LUNA
    url: str = CHATGPT_RESPONSES_WS_URL
    max_connections: int = 4
    prepared_connections: int = 3
    request_timeout_s: float = 30.0
    max_output_chars: int = 2000
    runtime_logging: ProviderObservationPort | None = None
    connector: WebSocketConnector = _connect_websocket
    _idle: list[_PooledConnection] = field(init=False, default_factory=list, repr=False)
    _open_count: int = field(init=False, default=0, repr=False)
    _condition: asyncio.Condition | None = field(init=False, default=None, repr=False)
    _closed: bool = field(init=False, default=False, repr=False)
    _pool_epoch: int = field(init=False, default=0, repr=False)
    _requests: set[asyncio.Task[str]] = field(init=False, default_factory=set, repr=False)
    _close_task: asyncio.Task[None] | None = field(init=False, default=None, repr=False)

    def _cond(self) -> asyncio.Condition:
        if self._condition is None:
            self._condition = asyncio.Condition()
        return self._condition

    async def prepare_connections(self) -> None:
        if self._closed:
            return
        async with self._cond():
            missing = max(
                0, min(self.prepared_connections, self.max_connections) - self._open_count
            )
            self._open_count += missing
        if missing == 0:
            return
        tasks = [asyncio.create_task(self._open()) for _ in range(missing)]
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            async with self._cond():
                self._open_count -= missing
                self._cond().notify_all()
            await self._discard_detached(
                [item for item in results if isinstance(item, _PooledConnection)]
            )
            raise
        created = [item for item in results if isinstance(item, _PooledConnection)]
        failures = [item for item in results if isinstance(item, BaseException)]
        async with self._cond():
            self._open_count -= len(failures)
            current = [
                connection
                for connection in created
                if not self._closed and connection.pool_epoch == self._pool_epoch
            ]
            stale = [connection for connection in created if connection not in current]
            self._open_count -= len(stale)
            self._idle.extend(current)
            self._cond().notify_all()
        await self._discard_detached(stale)
        if failures:
            self._log_failure("prepare_connections", failures[0])

    async def translate(
        self,
        *,
        utterance_id: UUID,
        text: str,
        system_prompt: str,
        source_language: str,
        target_language: str,
        context: str = "",
        scene_participant_count: int | None = None,
        max_output_tokens: int | None = None,
    ) -> Translation:
        _ = max_output_tokens
        body = {
            "type": "response.create",
            "model": self.model,
            "store": False,
            "reasoning": {"effort": "none"},
            "instructions": _build_system_prompt(
                system_prompt=system_prompt,
                source_language=source_language,
                target_language=target_language,
            ),
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": build_translation_user_message(
                                text=text,
                                context=context,
                                scene_participant_count=scene_participant_count,
                            ),
                        }
                    ],
                }
            ],
        }
        try:
            translated = await self._run_with_reauth_retry(body)
        except Exception as exc:
            self._log_failure("translate", exc)
            raise
        return Translation(utterance_id=utterance_id, text=translated)

    async def release_connections(self) -> None:
        async with self._cond():
            self._pool_epoch += 1
            idle = list(self._idle)
            self._idle.clear()
            self._open_count -= len(idle)
            self._cond().notify_all()
        await self._discard_detached(idle)

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_pool())
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await self._close_task
            raise

    async def _close_pool(self) -> None:
        async with self._cond():
            idle = list(self._idle)
            self._idle.clear()
            self._open_count -= len(idle)
            self._cond().notify_all()
        requests = tuple(self._requests)
        for task in requests:
            task.cancel()
        await asyncio.gather(
            self._discard_detached(idle),
            *requests,
            return_exceptions=True,
        )

    async def _run_with_reauth_retry(self, body: Mapping[str, object]) -> str:
        try:
            return await self._run(body)
        except ChatGptPlanResponseError as exc:
            if exc.status_code != 401 or exc.subscription_code is not None:
                raise
        return await self._run(body)

    async def _run(self, body: Mapping[str, object]) -> str:
        observation = current_attempt()
        if observation is not None:
            observation.transport = "websocket"
            observation.connection_reused = None
            observation.connect_ms = None
        acquired = asyncio.Event()
        task = asyncio.create_task(self._run_connection(body, acquired))
        self._requests.add(task)
        task.add_done_callback(self._request_finished)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if not acquired.is_set():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise

    def _request_finished(self, task: asyncio.Task[str]) -> None:
        self._requests.discard(task)
        if not task.cancelled():
            task.exception()

    async def _run_connection(self, body: Mapping[str, object], acquired: asyncio.Event) -> str:
        connection = await self._acquire()
        acquired.set()
        reusable = False
        try:
            text = await asyncio.wait_for(
                self._exchange(connection, body),
                timeout=self.request_timeout_s,
            )
            reusable = True
            return text
        except ChatGptPlanResponseError as exc:
            if exc.status_code == 401:
                self.session.invalidate_access_token(connection.token)
            raise
        finally:
            await self._release(connection, reusable=reusable)

    async def _exchange(self, connection: _PooledConnection, body: Mapping[str, object]) -> str:
        observation = current_attempt()
        message = json.dumps(body)
        if observation is not None:
            observation.mark_sent()
        await connection.socket.send(message)
        parts: list[str] = []
        length = 0
        while True:
            event = json.loads(await connection.socket.recv())
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "response.output_text.delta":
                delta = event.get("delta")
                if isinstance(delta, str):
                    if delta and observation is not None and observation.first_text_at is None:
                        observation.mark_first_text()
                    parts.append(delta)
                    length += len(delta)
                    if length > self.max_output_chars:
                        raise RuntimeError("ChatGPT plan response was truncated by length limit")
            elif kind == "response.completed":
                if observation is not None:
                    observation.record_openai_response(event.get("response"))
                result = "".join(parts).strip()
                if not result:
                    raise RuntimeError("ChatGPT plan response contained empty message content")
                return result
            elif kind in ("response.failed", "response.incomplete", "error"):
                raise _error_from_event(event)

    async def _acquire(self) -> _PooledConnection:
        observation = current_attempt()
        auth_started_at = observation.request.clock() if observation is not None else None
        try:
            token_generation = await self._current_token_generation()
        finally:
            if observation is not None and auth_started_at is not None:
                observation.auth_ms = (observation.auth_ms or 0) + max(
                    0, round((observation.request.clock() - auth_started_at) * 1000)
                )
        if observation is not None and observation.connection_wait_ms is None:
            observation.connection_wait_ms = 0
        stale: list[_PooledConnection] = []
        try:
            async with self._cond():
                while True:
                    if self._closed:
                        raise RuntimeError("ChatGPT plan provider is closed")
                    while self._idle:
                        candidate = self._idle.pop()
                        if (
                            candidate.token_generation == token_generation
                            and candidate.pool_epoch == self._pool_epoch
                        ):
                            if observation is not None:
                                observation.connection_reused = True
                            return candidate
                        stale.append(candidate)
                        self._open_count -= 1
                    if self._open_count < self.max_connections:
                        self._open_count += 1
                        if observation is not None:
                            observation.connection_reused = False
                        break
                    wait_started_at = (
                        observation.request.clock() if observation is not None else None
                    )
                    try:
                        await self._cond().wait()
                    finally:
                        if observation is not None and wait_started_at is not None:
                            observation.connection_wait_ms = (
                                observation.connection_wait_ms or 0
                            ) + max(
                                0, round((observation.request.clock() - wait_started_at) * 1000)
                            )
        finally:
            for connection in stale:
                await self._discard(connection)
        try:
            return await self._open()
        except BaseException:
            async with self._cond():
                self._open_count -= 1
                self._cond().notify_all()
            raise

    async def _release(self, connection: _PooledConnection, *, reusable: bool) -> None:
        keep = (
            reusable
            and not self._closed
            and connection.pool_epoch == self._pool_epoch
            and getattr(connection.socket, "close_code", None) is None
        )
        async with self._cond():
            if keep:
                self._idle.append(connection)
            else:
                self._open_count -= 1
            self._cond().notify_all()
        if not keep:
            await self._discard(connection)

    async def _current_token_generation(self) -> int:
        try:
            await self.session.access_token()
        except ChatGptReauthRequired:
            raise
        except ChatGptAuthError as exc:
            raise ChatGptPlanResponseError(exc.status_code or 503, exc.code) from exc
        return self.session.token_generation

    async def _open(self) -> _PooledConnection:
        pool_epoch = self._pool_epoch
        observation = current_attempt()
        auth_started_at = observation.request.clock() if observation is not None else None
        try:
            token = await self.session.access_token()
        finally:
            if observation is not None and auth_started_at is not None:
                observation.auth_ms = (observation.auth_ms or 0) + max(
                    0, round((observation.request.clock() - auth_started_at) * 1000)
                )
        generation = self.session.token_generation
        connect_started_at = observation.request.clock() if observation is not None else None
        try:
            socket = await self.connector(self.url, {"Authorization": f"Bearer {token}"})
        except InvalidStatus as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 401:
                self.session.invalidate_access_token(token)
            raise ChatGptPlanResponseError(status) from exc
        finally:
            if observation is not None and connect_started_at is not None:
                observation.connect_ms = max(
                    0, round((observation.request.clock() - connect_started_at) * 1000)
                )
        return _PooledConnection(
            socket=socket, token=token, token_generation=generation, pool_epoch=pool_epoch
        )

    async def _discard_detached(self, connections: list[_PooledConnection]) -> None:
        if not connections:
            return
        closing = asyncio.gather(
            *(self._discard(connection) for connection in connections), return_exceptions=True
        )
        try:
            await asyncio.shield(closing)
        except asyncio.CancelledError:
            await closing
            raise

    async def _discard(self, connection: _PooledConnection) -> None:
        close = getattr(connection.socket, "close", None)
        if callable(close):
            try:
                await close()
            except Exception:
                return

    def _log_failure(self, operation: str, exc: BaseException) -> None:
        report = provider_failure_report(exc, provider="chatgpt", operation=operation)
        rendered = "[Basic][LLM] ChatGPT plan request failed [%s]: %s" % (
            operation,
            format_error_report_for_log(report),
        )
        if self.runtime_logging is not None:
            self.runtime_logging.emit_basic(rendered, level=logging.ERROR)
            return
        logger.error(rendered)


__all__ = [
    "CHATGPT_RESPONSES_WS_URL",
    "ChatGptPlanLLMProvider",
    "ChatGptPlanResponseError",
]
