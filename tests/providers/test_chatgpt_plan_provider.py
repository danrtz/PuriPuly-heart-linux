from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from uuid import uuid4

import pytest
from websockets.exceptions import InvalidStatus

from puripuly_heart.core.error_messages import provider_failure_report
from puripuly_heart.providers.llm.chatgpt_plan import (
    ChatGptPlanLLMProvider,
    ChatGptPlanResponseError,
)

Script = Callable[[dict[str, object]], list[dict[str, object]]]


def _completed(text: str) -> Script:
    def script(_request: dict[str, object]) -> list[dict[str, object]]:
        return [
            {"type": "response.created", "response": {"id": "resp"}},
            {"type": "response.output_text.delta", "delta": text[: len(text) // 2]},
            {"type": "response.output_text.delta", "delta": text[len(text) // 2 :]},
            {"type": "response.completed", "response": {"id": "resp", "output": []}},
        ]

    return script


class _FakeSocket:
    def __init__(self, server: _FakeServer, token: str) -> None:
        self.server = server
        self.token = token
        self.sent: list[dict[str, object]] = []
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self.close_code: int | None = None

    async def send(self, raw: str) -> None:
        request = json.loads(raw)
        self.sent.append(request)
        self.server.requests.append(request)
        if self.server.gate is not None:
            await self.server.gate.wait()
        for event in self.server.script(request):
            await self._queue.put(json.dumps(event))

    async def recv(self) -> str:
        return await self._queue.get()

    async def close(self) -> None:
        self.close_code = 1000
        self.server.closed += 1


class _FakeServer:
    def __init__(self, script: Script) -> None:
        self.script = script
        self.sockets: list[_FakeSocket] = []
        self.requests: list[dict[str, object]] = []
        self.closed = 0
        self.reject_tokens: set[str] = set()
        self.gate: asyncio.Event | None = None

    async def connect(self, url: str, headers: Mapping[str, str]) -> _FakeSocket:
        assert url == "wss://api.openai.com/v1/responses"
        token = headers["Authorization"].removeprefix("Bearer ")
        if token in self.reject_tokens:
            raise InvalidStatus(type("Response", (), {"status_code": 401})())
        socket = _FakeSocket(self, token)
        self.sockets.append(socket)
        return socket


class _FakeSession:
    def __init__(self) -> None:
        self.token = "token-1"
        self._generation = 1
        self.invalidated: list[str] = []

    @property
    def token_generation(self) -> int:
        return self._generation

    async def access_token(self) -> str:
        return self.token

    def invalidate_access_token(self, token: str) -> None:
        self.invalidated.append(token)
        if token == self.token:
            self.token = f"token-{self._generation + 1}"
            self._generation += 1

    def rotate(self) -> None:
        self._generation += 1
        self.token = f"token-{self._generation}"


def _provider(
    server: _FakeServer, session: _FakeSession, **kwargs: object
) -> ChatGptPlanLLMProvider:
    return ChatGptPlanLLMProvider(session=session, connector=server.connect, **kwargs)


async def _translate(provider: ChatGptPlanLLMProvider, text: str = "안녕") -> str:
    result = await provider.translate(
        utterance_id=uuid4(),
        text=text,
        system_prompt="Translate {source_language} to {target_language}.",
        source_language="Korean",
        target_language="English",
        max_output_tokens=64,
    )
    return result.text


async def _wait_for_requests(server: _FakeServer, count: int) -> None:
    async with asyncio.timeout(1):
        while len(server.requests) < count:
            await asyncio.sleep(0)


async def test_translate_sends_plan_compatible_request_and_reuses_connection() -> None:
    server = _FakeServer(_completed("Hello there"))
    provider = _provider(server, _FakeSession())

    assert await _translate(provider) == "Hello there"
    assert await _translate(provider, "고마워") == "Hello there"

    assert len(server.sockets) == 1
    request = server.requests[0]
    assert request["type"] == "response.create"
    assert request["model"] == "gpt-6-luna"
    assert request["store"] is False
    assert request["reasoning"] == {"effort": "none"}
    assert request["instructions"] == "Translate Korean to English."
    assert "stream" not in request
    assert "temperature" not in request
    assert "max_output_tokens" not in request
    assert "stream_id" not in request
    message = request["input"][0]
    assert message["role"] == "user"
    assert "안녕" in message["content"][0]["text"]
    await provider.close()
    assert server.closed == 1


async def test_concurrent_requests_use_separate_connections_within_pool_limit() -> None:
    server = _FakeServer(_completed("ok"))
    server.gate = asyncio.Event()
    provider = _provider(server, _FakeSession(), max_connections=2)

    tasks = [asyncio.create_task(_translate(provider)) for _ in range(3)]
    await asyncio.sleep(0.01)
    assert len(server.sockets) == 2
    server.gate.set()
    assert await asyncio.gather(*tasks) == ["ok", "ok", "ok"]
    assert len(server.sockets) == 2
    await provider.close()


async def test_usage_limit_error_discards_connection_and_maps_to_user_message() -> None:
    def script(_request: dict[str, object]) -> list[dict[str, object]]:
        return [
            {
                "type": "error",
                "status": 429,
                "error": {"code": "subscription_sharing_usage_limit_exceeded"},
            }
        ]

    server = _FakeServer(script)
    provider = _provider(server, _FakeSession())

    with pytest.raises(ChatGptPlanResponseError) as exc_info:
        await _translate(provider)

    assert exc_info.value.status_code == 429
    assert server.closed == 1
    report = provider_failure_report(exc_info.value, provider="chatgpt", operation="translate")
    assert report.message.key == "provider.chatgpt.usage_limit"


async def test_not_eligible_failure_maps_to_user_message() -> None:
    def script(_request: dict[str, object]) -> list[dict[str, object]]:
        return [
            {
                "type": "response.failed",
                "response": {"error": {"code": "subscription_sharing_user_not_eligible"}},
            }
        ]

    provider = _provider(_FakeServer(script), _FakeSession())
    with pytest.raises(ChatGptPlanResponseError) as exc_info:
        await _translate(provider)
    report = provider_failure_report(exc_info.value, provider="chatgpt", operation="translate")
    assert report.message.key == "provider.chatgpt.not_eligible"


async def test_handshake_unauthorized_invalidates_token_and_retries_once() -> None:
    server = _FakeServer(_completed("ok"))
    session = _FakeSession()
    server.reject_tokens.add("token-1")
    provider = _provider(server, session)

    assert await _translate(provider) == "ok"
    assert session.invalidated == ["token-1"]
    assert [socket.token for socket in server.sockets] == ["token-2"]
    await provider.close()


async def test_refreshed_token_replaces_idle_connection() -> None:
    server = _FakeServer(_completed("ok"))
    session = _FakeSession()
    provider = _provider(server, session)

    await _translate(provider)
    session.rotate()
    await _translate(provider)

    assert [socket.token for socket in server.sockets] == ["token-1", "token-2"]
    assert server.sockets[0].close_code is not None
    await provider.close()


async def test_runaway_output_is_rejected_and_connection_discarded() -> None:
    server = _FakeServer(_completed("x" * 50))
    provider = _provider(server, _FakeSession(), max_output_chars=10)

    with pytest.raises(RuntimeError, match="length limit"):
        await _translate(provider)
    assert server.closed == 1


async def test_prepare_connections_opens_idle_connections_for_first_utterances() -> None:
    server = _FakeServer(_completed("ok"))
    provider = _provider(server, _FakeSession(), prepared_connections=2)

    await provider.prepare_connections()
    assert len(server.sockets) == 2
    assert server.requests == []

    await asyncio.gather(_translate(provider), _translate(provider))
    assert len(server.sockets) == 2
    await provider.close()
    assert server.closed == 2


async def test_release_closes_idle_connections_and_drains_in_flight_ones() -> None:
    server = _FakeServer(_completed("ok"))
    provider = _provider(server, _FakeSession(), prepared_connections=2)
    await provider.prepare_connections()

    server.gate = asyncio.Event()
    in_flight = asyncio.create_task(_translate(provider))
    await asyncio.sleep(0.01)
    await provider.release_connections()
    assert server.closed == 1

    server.gate.set()
    assert await in_flight == "ok"
    assert server.closed == 2

    assert await _translate(provider) == "ok"
    assert await _translate(provider) == "ok"
    assert len(server.sockets) == 3
    assert server.closed == 2
    await provider.close()


async def test_cancelled_preparation_closes_partial_connections_and_unblocks_next_request() -> None:
    server = _FakeServer(_completed("ready"))
    pending = asyncio.Event()
    gate = asyncio.Event()
    calls = 0

    async def connect(url: str, headers: Mapping[str, str]) -> _FakeSocket:
        nonlocal calls
        calls += 1
        if calls == 3:
            pending.set()
            await gate.wait()
        return await server.connect(url, headers)

    provider = ChatGptPlanLLMProvider(
        session=_FakeSession(), connector=connect, prepared_connections=3, max_connections=3
    )
    try:
        preparation = asyncio.create_task(provider.prepare_connections())
        await pending.wait()
        preparation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await preparation
        assert server.closed == 2
        assert await asyncio.wait_for(_translate(provider), timeout=1) == "ready"
    finally:
        await provider.close()
    assert server.closed == 3


async def test_cancelled_release_finishes_closing_every_detached_connection() -> None:
    server = _FakeServer(_completed("ready"))
    provider = _provider(server, _FakeSession(), prepared_connections=3)
    await provider.prepare_connections()
    started = asyncio.Event()
    gate = asyncio.Event()
    for socket in server.sockets:
        original = socket.close

        async def slow_close(original: Callable = original) -> None:
            started.set()
            await gate.wait()
            await original()

        socket.close = slow_close
    try:
        release = asyncio.create_task(provider.release_connections())
        await started.wait()
        release.cancel()
        gate.set()
        with pytest.raises(asyncio.CancelledError):
            await release
        assert [socket.close_code for socket in server.sockets] == [1000, 1000, 1000]
    finally:
        gate.set()
        await provider.close()


async def test_cancelled_response_drains_before_connection_reuse_without_mixing_text() -> None:
    server = _FakeServer(lambda _request: [])
    provider = _provider(server, _FakeSession(), max_connections=1)
    first = asyncio.create_task(_translate(provider, "first"))
    try:
        await _wait_for_requests(server, 1)
        socket = server.sockets[0]
        socket._queue.put_nowait(json.dumps({"type": "response.output_text.delta", "delta": "old"}))
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert server.closed == 0

        server.script = _completed("new")
        second = asyncio.create_task(_translate(provider, "second"))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(second), timeout=0.02)
        assert len(server.requests) == 1
        socket._queue.put_nowait(
            json.dumps({"type": "response.output_text.delta", "delta": " tail"})
        )
        socket._queue.put_nowait(json.dumps({"type": "response.completed"}))

        assert await asyncio.wait_for(second, timeout=1) == "new"
        assert len(server.sockets) == 1
        assert server.closed == 0
    finally:
        await provider.close()
    assert server.closed == 1


@pytest.mark.parametrize("failure", ["timeout", "error"])
async def test_cancelled_response_failure_frees_pool_slot(failure: str) -> None:
    server = _FakeServer(lambda _request: [])
    provider = _provider(server, _FakeSession(), max_connections=1, request_timeout_s=0.1)
    first = asyncio.create_task(_translate(provider))
    try:
        await _wait_for_requests(server, 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        server.script = _completed("next")
        second = asyncio.create_task(_translate(provider))
        if failure == "error":
            server.sockets[0]._queue.put_nowait(
                json.dumps({"type": "response.failed", "response": {"error": {"code": "failed"}}})
            )
        assert await asyncio.wait_for(second, timeout=1) == "next"
        assert server.sockets[0].close_code == 1000
        assert len(server.sockets) == 2
    finally:
        await provider.close()


@pytest.mark.parametrize("shutdown", ["release", "close"])
async def test_shutdown_retires_draining_connection(shutdown: str) -> None:
    server = _FakeServer(lambda _request: [])
    provider = _provider(server, _FakeSession(), max_connections=1)
    first = asyncio.create_task(_translate(provider))
    try:
        await _wait_for_requests(server, 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        if shutdown == "close":
            await asyncio.wait_for(provider.close(), timeout=1)
            assert server.closed == 1
            with pytest.raises(RuntimeError, match="closed"):
                await _translate(provider)
        else:
            await provider.release_connections()
            server.sockets[0]._queue.put_nowait(
                json.dumps({"type": "response.output_text.delta", "delta": "old"})
            )
            server.sockets[0]._queue.put_nowait(json.dumps({"type": "response.completed"}))
            server.script = _completed("next")
            assert await asyncio.wait_for(_translate(provider), timeout=1) == "next"
            assert server.sockets[0].close_code == 1000
            assert len(server.sockets) == 2
    finally:
        await provider.close()


async def test_cancelled_pool_waiter_never_sends_an_abandoned_request() -> None:
    server = _FakeServer(lambda _request: [])
    provider = _provider(server, _FakeSession(), max_connections=1)
    first = asyncio.create_task(_translate(provider, "first"))
    try:
        await _wait_for_requests(server, 1)
        abandoned = asyncio.create_task(_translate(provider, "abandoned"))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(abandoned), timeout=0.02)
        abandoned.cancel()
        with pytest.raises(asyncio.CancelledError):
            await abandoned
        server.sockets[0]._queue.put_nowait(
            json.dumps({"type": "response.output_text.delta", "delta": "first"})
        )
        server.sockets[0]._queue.put_nowait(json.dumps({"type": "response.completed"}))
        assert await asyncio.wait_for(first, timeout=1) == "first"
        server.script = _completed("last")
        assert await asyncio.wait_for(_translate(provider, "last"), timeout=1) == "last"
        assert len(server.requests) == 2
        assert len(server.sockets) == 1
    finally:
        await provider.close()
