from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from puripuly_heart.core.llm.fallback_racing import FallbackRacingLLMProvider, LLMProviderAttempt
from puripuly_heart.core.llm.latency import (
    current_attempt,
    current_request,
    observe_attempt,
    observe_request,
)
from puripuly_heart.core.llm.provider import SemaphoreLLMProvider
from puripuly_heart.domain.models import Translation


class _Sink:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def emit_translation_latency(self, message: str) -> bool:
        self.messages.append(message)
        return True

    def rows(self) -> list[dict[str, str]]:
        rows = []
        for message in self.messages:
            event, *fields = message.removeprefix("[Diagnostic][LlmLatency] ").split()
            rows.append({"event": event, **dict(field.split("=", 1) for field in fields)})
        return rows


class _Clock:
    value = 0.0

    def __call__(self) -> float:
        return self.value


def _request(sink, *, utterance_id=None, clock=None):
    kwargs = {} if clock is None else {"clock": clock}
    return observe_request(
        sink=sink,
        utterance_id=utterance_id or uuid4(),
        channel="self",
        kind="manual",
        source_language="ko",
        target_language="en",
        provider_generation=3,
        input_chars=17,
        prompt_chars=20,
        context_chars=0,
        **kwargs,
    )


def test_first_text_timing_ignores_later_deltas_and_distinguishes_network_from_attempt() -> None:
    sink = _Sink()
    clock = _Clock()
    with _request(sink, clock=clock):
        clock.value = 0.2
        with observe_attempt(provider="chatgpt", model="gpt-6-luna") as attempt:
            clock.value = 0.5
            attempt.mark_sent()
            clock.value = 0.9
            attempt.mark_first_text()
            clock.value = 2.0
            attempt.mark_first_text()
            clock.value = 2.5

    attempt_row, request_row = sink.rows()
    assert attempt_row["attempt_ms"] == "2300"
    assert attempt_row["network_ms"] == "2000"
    assert attempt_row["ttft_ms"] == "400"
    assert attempt_row["first_text_to_done_ms"] == "1600"
    assert request_row["request_ms"] == "2500"
    assert attempt_row["request_id"] == request_row["request_id"]


def test_missing_and_invalid_metrics_are_not_synthesized_or_confused_with_real_zero() -> None:
    sink = _Sink()
    with _request(sink):
        with observe_attempt(provider="openrouter", model="google/gemma-4") as attempt:
            attempt.mark_sent()
            attempt.record_openai_response(
                {
                    "usage": {
                        "prompt_tokens": True,
                        "completion_tokens": -1,
                        "prompt_cache_hit_tokens": 99,
                        "prompt_tokens_details": {"cached_tokens": 0},
                        "reasoning_tokens": "10",
                    }
                }
            )
            attempt.record_server_timings(
                prompt_ms=float("nan"), generation_ms=-1, generation_tps=0.0
            )

    row = sink.rows()[0]
    assert row["ttft_ms"] == "none"
    assert row["first_text_to_done_ms"] == "none"
    assert row["input_tokens"] == row["output_tokens"] == row["reasoning_tokens"] == "none"
    assert row["cached_input_tokens"] == "0"
    assert "server_prompt_ms" not in row
    assert "server_generation_ms" not in row
    assert row["server_generation_tps"] == "0.000"


def test_disabled_nested_observation_does_not_inherit_or_destroy_parent_scope() -> None:
    sink = _Sink()
    with _request(sink) as request:
        with observe_attempt(provider="openai", model="test") as attempt:
            with _request(None):
                assert current_request() is None
                assert current_attempt() is None
                with observe_attempt(provider="disabled", model="test") as disabled:
                    assert disabled is None
            assert current_request() is request
            assert current_attempt() is attempt
    assert [row["event"] for row in sink.rows()] == ["attempt_end", "request_end"]
    assert current_request() is None
    assert current_attempt() is None


def test_sink_failure_does_not_replace_original_cancellation_or_exception() -> None:
    class BrokenSink:
        def emit_translation_latency(self, message: str) -> bool:
            raise OSError("file unavailable")

    error = ValueError("private request and credential")
    with pytest.raises(ValueError) as raised:
        with _request(BrokenSink()):
            with observe_attempt(provider="openai", model="test"):
                raise error
    assert raised.value is error

    cancellation = asyncio.CancelledError("original cancellation")
    with pytest.raises(asyncio.CancelledError) as raised:
        with _request(BrokenSink()):
            with observe_attempt(provider="openai", model="test"):
                raise cancellation
    assert raised.value is cancellation
    assert current_request() is None
    assert current_attempt() is None


class _Provider:
    def __init__(self, *, blocked_id: UUID | None = None, fail_after_release=False) -> None:
        self.blocked_id = blocked_id
        self.fail_after_release = fail_after_release
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def translate(self, *, utterance_id: UUID, text: str, **kwargs) -> Translation:
        self.started.set()
        if utterance_id == self.blocked_id:
            await self.release.wait()
            if self.fail_after_release:
                raise RuntimeError("private prompt Authorization=secret")
        return Translation(
            utterance_id=utterance_id,
            text="fallback" if self.blocked_id is None else "primary",
            source_text=text,
            source_language=kwargs["source_language"],
            target_language=kwargs["target_language"],
        )

    async def close(self) -> None:
        pass


async def _translate(provider, sink, utterance_id, *, clock=None):
    with _request(sink, utterance_id=utterance_id, clock=clock):
        return await provider.translate(
            utterance_id=utterance_id,
            text="synthetic private input",
            system_prompt="synthetic private prompt",
            source_language="ko",
            target_language="en",
        )


@pytest.mark.asyncio
async def test_concurrent_races_isolate_ids_and_log_only_started_attempts() -> None:
    sink = _Sink()
    blocked_id, fast_id = uuid4(), uuid4()
    primary = _Provider(blocked_id=blocked_id, fail_after_release=True)
    provider = FallbackRacingLLMProvider(
        attempts=(
            LLMProviderAttempt(primary, provider_name="openai", model="primary"),
            LLMProviderAttempt(
                _Provider(),
                start_after_ms=10_000,
                start_on_primary_error=True,
                provider_name="openrouter",
                model="google/gemma-4",
            ),
        )
    )
    blocked = asyncio.create_task(_translate(provider, sink, blocked_id))
    try:
        await asyncio.wait_for(primary.started.wait(), timeout=1)
        fast = await asyncio.wait_for(_translate(provider, sink, fast_id), timeout=1)
        primary.release.set()
        fallback = await asyncio.wait_for(blocked, timeout=1)
        assert fast.text == "primary"
        assert fallback.text == "fallback"
    finally:
        primary.release.set()
        await provider.close()
        await asyncio.gather(blocked, return_exceptions=True)

    rows = sink.rows()
    requests = {row["utterance_id"]: row for row in rows if row["event"] == "request_end"}
    fast_request, blocked_request = requests[str(fast_id)], requests[str(blocked_id)]
    assert fast_request["request_id"] != blocked_request["request_id"]
    assert fast_request["attempts"] == "1"
    assert fast_request["winner_attempt"] == "0"
    assert blocked_request["attempts"] == "2"
    assert blocked_request["winner_attempt"] == "1"
    attempts_by_request = {
        request["request_id"]: [
            (row["attempt"], row["status"]) for row in rows
            if row["event"] == "attempt_end" and row["request_id"] == request["request_id"]
        ]
        for request in requests.values()
    }
    assert attempts_by_request[fast_request["request_id"]] == [("0", "success")]
    assert attempts_by_request[blocked_request["request_id"]] == [("0", "error"), ("1", "success")]
    failed = next(row for row in rows if row["status"] == "error")
    assert failed["error_type"] == "RuntimeError"
    assert not any("private" in message or "Authorization" in message for message in sink.messages)


@pytest.mark.asyncio
async def test_hedge_loser_cancellation_remains_correlated_after_request_end() -> None:
    sink = _Sink()
    utterance_id = uuid4()
    primary = _Provider(blocked_id=utterance_id)
    provider = FallbackRacingLLMProvider(
        attempts=(
            LLMProviderAttempt(primary, provider_name="openai", model="primary"),
            LLMProviderAttempt(_Provider(), start_after_ms=1, provider_name="openrouter"),
        ),
        loser_grace_ms=0,
    )
    try:
        result = await asyncio.wait_for(_translate(provider, sink, utterance_id), timeout=1)
        assert result.text == "fallback"
    finally:
        await provider.close()
    rows = sink.rows()
    request = next(row for row in rows if row["event"] == "request_end")
    attempts = [row for row in rows if row["event"] == "attempt_end"]
    assert request["attempts"] == "2"
    assert request["winner_attempt"] == "1"
    assert {(row["attempt"], row["status"]) for row in attempts} == {
        ("0", "cancelled"), ("1", "success")
    }
    assert all(row["request_id"] == request["request_id"] for row in attempts)


@pytest.mark.asyncio
async def test_cancelled_semaphore_wait_records_queue_time_without_fake_attempt() -> None:
    sink = _Sink()
    clock = _Clock()
    provider = SemaphoreLLMProvider(inner=_Provider(), semaphore=asyncio.Semaphore(0))
    task = asyncio.create_task(_translate(provider, sink, uuid4(), clock=clock))
    await asyncio.sleep(0)
    clock.value = 0.25
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    row, = sink.rows()
    assert row["event"] == "request_end"
    assert row["status"] == "cancelled"
    assert row["queue_ms"] == "250"
    assert row["attempts"] == "0"
    assert row["winner_attempt"] == "none"
