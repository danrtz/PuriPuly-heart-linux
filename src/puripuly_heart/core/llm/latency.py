from __future__ import annotations

import asyncio
import math
import re
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from itertools import count
from typing import Protocol
from uuid import UUID

_PREFIX = "[Diagnostic][LlmLatency] "
_LABEL = re.compile(r"[A-Za-z0-9_./:+-]{1,128}\Z")
_FIELDS = frozenset(
    "request_id utterance_id parent_utterance_id channel kind source_language target_language "
    "provider_generation input_chars prompt_chars context_chars status request_ms queue_ms "
    "attempts winner_attempt attempt provider model actual_model transport attempt_ms network_ms "
    "ttft_ms first_text_to_done_ms auth_ms connection_wait_ms connect_ms connection_reused "
    "input_tokens output_tokens cached_input_tokens reasoning_tokens requested_tier actual_tier "
    "server_prompt_ms server_generation_ms server_generation_tps error_type http_status".split()
)
_REQUEST_IDS = count(1)


class TranslationLatencySink(Protocol):
    def emit_translation_latency(self, message: str) -> bool: ...


def _label(value: str | None) -> str:
    return value if value is not None and _LABEL.fullmatch(value) else "none"


def _milliseconds(start: float | None, end: float) -> int | None:
    return None if start is None else max(0, round((end - start) * 1000))


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if value >= 0 and math.isfinite(value) else None


def _format(event: str, values: Mapping[str, object]) -> str:
    parts = [_PREFIX + event]
    for key, value in values.items():
        if value is None:
            rendered = "none"
        elif isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, str):
            rendered = _label(value)
        elif isinstance(value, float):
            rendered = f"{value:.3f}" if math.isfinite(value) else "none"
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return " ".join(parts)


def is_translation_latency_summary(message: str) -> bool:
    if not message.startswith(_PREFIX):
        return False
    tokens = message[len(_PREFIX) :].split()
    if not tokens or tokens[0] not in {"request_end", "attempt_end"}:
        return False
    seen: set[str] = set()
    for token in tokens[1:]:
        key, separator, value = token.partition("=")
        if not separator or key not in _FIELDS or key in seen or not _LABEL.fullmatch(value):
            return False
        seen.add(key)
    return bool(seen)


@dataclass(slots=True)
class RequestLatency:
    sink: TranslationLatencySink
    utterance_id: UUID
    channel: str
    kind: str
    source_language: str
    target_language: str
    provider_generation: int
    input_chars: int
    prompt_chars: int
    context_chars: int
    clock: Callable[[], float]
    parent_utterance_id: UUID | None = None
    request_id: int = field(default_factory=lambda: next(_REQUEST_IDS))
    started_at: float = field(init=False)
    queue_ms: int = 0
    attempts: int = 0
    winner_attempt: int | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        self.started_at = self.clock()

    def emit(self, event: str, values: Mapping[str, object]) -> None:
        try:
            self.sink.emit_translation_latency(_format(event, values))
        except Exception:
            return

    def finish(self, status: str) -> None:
        self.emit(
            "request_end",
            {
                "request_id": self.request_id,
                "utterance_id": str(self.utterance_id),
                "parent_utterance_id": str(self.parent_utterance_id) if self.parent_utterance_id else None,
                "channel": self.channel,
                "kind": self.kind,
                "source_language": self.source_language,
                "target_language": self.target_language,
                "provider_generation": self.provider_generation,
                "input_chars": self.input_chars,
                "prompt_chars": self.prompt_chars,
                "context_chars": self.context_chars,
                "status": self.status or status,
                "request_ms": _milliseconds(self.started_at, self.clock()),
                "queue_ms": self.queue_ms,
                "attempts": self.attempts,
                "winner_attempt": self.winner_attempt,
            },
        )


@dataclass(slots=True)
class AttemptLatency:
    request: RequestLatency
    provider: str
    model: str | None
    attempt: int
    started_at: float = field(init=False)
    sent_at: float | None = None
    first_text_at: float | None = None
    transport: str | None = None
    actual_model: str | None = None
    auth_ms: int | None = None
    connection_wait_ms: int | None = None
    connect_ms: int | None = None
    connection_reused: bool | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    requested_tier: str | None = None
    actual_tier: str | None = None
    server_prompt_ms: float | None = None
    server_generation_ms: float | None = None
    server_generation_tps: float | None = None

    def __post_init__(self) -> None:
        self.started_at = self.request.clock()
        self.request.attempts += 1

    def mark_sent(self) -> None:
        self.sent_at = self.request.clock()
        self.first_text_at = None

    def mark_first_text(self) -> None:
        if self.first_text_at is None:
            self.first_text_at = self.request.clock()

    def record_usage(
        self,
        *,
        input_tokens: object = None,
        output_tokens: object = None,
        cached_input_tokens: object = None,
        reasoning_tokens: object = None,
    ) -> None:
        self.input_tokens = _count(input_tokens)
        self.output_tokens = _count(output_tokens)
        self.cached_input_tokens = _count(cached_input_tokens)
        self.reasoning_tokens = _count(reasoning_tokens)

    def record_openai_response(self, response: object) -> None:
        if not isinstance(response, Mapping):
            return
        model = response.get("model")
        tier = response.get("service_tier")
        self.actual_model = model if isinstance(model, str) else None
        self.actual_tier = tier if isinstance(tier, str) else None
        usage = response.get("usage")
        if not isinstance(usage, Mapping):
            return
        input_details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details")
        output_details = usage.get("output_tokens_details") or usage.get("completion_tokens_details")
        self.record_usage(
            input_tokens=usage.get("input_tokens", usage.get("prompt_tokens")),
            output_tokens=usage.get("output_tokens", usage.get("completion_tokens")),
            cached_input_tokens=(
                input_details.get("cached_tokens", usage.get("prompt_cache_hit_tokens"))
                if isinstance(input_details, Mapping)
                else usage.get("prompt_cache_hit_tokens")
            ),
            reasoning_tokens=(
                output_details.get("reasoning_tokens", usage.get("reasoning_tokens"))
                if isinstance(output_details, Mapping)
                else usage.get("reasoning_tokens")
            ),
        )

    def record_server_timings(
        self,
        *,
        prompt_ms: object = None,
        generation_ms: object = None,
        generation_tps: object = None,
    ) -> None:
        self.server_prompt_ms = _number(prompt_ms)
        self.server_generation_ms = _number(generation_ms)
        self.server_generation_tps = _number(generation_tps)

    def finish(self, status: str, error: BaseException | None) -> None:
        ended_at = self.request.clock()
        values: dict[str, object] = {
            "request_id": self.request.request_id,
            "attempt": self.attempt,
            "provider": self.provider,
            "model": self.model,
            "actual_model": self.actual_model,
            "transport": self.transport,
            "status": status,
            "attempt_ms": _milliseconds(self.started_at, ended_at),
            "network_ms": _milliseconds(self.sent_at, ended_at),
            "ttft_ms": _milliseconds(self.sent_at, self.first_text_at) if self.first_text_at is not None else None,
            "first_text_to_done_ms": _milliseconds(self.first_text_at, ended_at),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }
        for key in (
            "auth_ms", "connection_wait_ms", "connect_ms", "connection_reused",
            "requested_tier", "actual_tier", "server_prompt_ms", "server_generation_ms",
            "server_generation_tps",
        ):
            value = getattr(self, key)
            if value is not None:
                values[key] = value
        if error is not None:
            values["error_type"] = type(error).__name__
            values["http_status"] = _count(getattr(error, "status_code", None))
        self.request.emit("attempt_end", values)


_REQUEST: ContextVar[RequestLatency | None] = ContextVar("translation_request_latency", default=None)
_ATTEMPT: ContextVar[AttemptLatency | None] = ContextVar("translation_attempt_latency", default=None)


def current_request() -> RequestLatency | None:
    return _REQUEST.get()


def current_attempt() -> AttemptLatency | None:
    return _ATTEMPT.get()


@contextmanager
def observe_request(
    *,
    sink: TranslationLatencySink | None,
    utterance_id: UUID,
    channel: str,
    kind: str,
    source_language: str,
    target_language: str,
    provider_generation: int,
    input_chars: int,
    prompt_chars: int,
    context_chars: int,
    parent_utterance_id: UUID | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[RequestLatency | None]:
    if sink is None:
        token = _REQUEST.set(None)
        attempt_token = _ATTEMPT.set(None)
        try:
            yield None
        finally:
            _ATTEMPT.reset(attempt_token)
            _REQUEST.reset(token)
        return
    observation = RequestLatency(
        sink, utterance_id, channel, kind, source_language, target_language,
        provider_generation, input_chars, prompt_chars, context_chars, clock,
        parent_utterance_id,
    )
    token = _REQUEST.set(observation)
    status = "success"
    try:
        yield observation
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    except BaseException:
        status = "error"
        raise
    finally:
        _REQUEST.reset(token)
        observation.finish(status)


@contextmanager
def observe_attempt(
    *, provider: str, model: str | None, attempt_index: int = 0,
) -> Iterator[AttemptLatency | None]:
    request = current_request()
    if request is None:
        yield None
        return
    observation = AttemptLatency(request, provider, model, attempt_index)
    token = _ATTEMPT.set(observation)
    status = "success"
    error: BaseException | None = None
    try:
        yield observation
    except asyncio.CancelledError as exc:
        status = "cancelled"
        error = exc
        raise
    except BaseException as exc:
        status = "error"
        error = exc
        raise
    finally:
        _ATTEMPT.reset(token)
        observation.finish(status, error)
