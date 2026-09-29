from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final
from urllib.parse import parse_qs, urlsplit

from puripuly_heart.core.discord.oauth_callback_page import (
    render_oauth_callback_completion_page,
    resolve_oauth_callback_locale,
)

CHATGPT_OAUTH_LOOPBACK_HOST: Final = "127.0.0.1"
CHATGPT_OAUTH_LOOPBACK_PATH: Final = "/auth/callback"
CHATGPT_OAUTH_LOOPBACK_PORTS: Final[tuple[int, ...]] = (1455, 1456, 1457, 0)


@dataclass(frozen=True, slots=True)
class ChatGptOAuthCallback:
    state: str
    code: str | None
    client_id: str | None
    scope: str | None
    error: str | None


class ChatGptOAuthLoopbackClosedError(RuntimeError):
    pass


class _LoopbackServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self) -> None:
        exclusive_addr_use = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive_addr_use is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive_addr_use, 1)
        super().server_bind()


class ChatGptOAuthLoopbackListener:
    def __init__(self, port: int, *, locale: str | None = None) -> None:
        self.locale = resolve_oauth_callback_locale(locale)
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._result: ChatGptOAuthCallback | None = None
        self._closed = False
        self._server = _LoopbackServer((CHATGPT_OAUTH_LOOPBACK_HOST, port), _handler_for(self))
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"chatgpt-oauth-loopback-{self.port}",
            daemon=True,
        )
        self._thread.start()

    @property
    def redirect_uri(self) -> str:
        return f"http://{CHATGPT_OAUTH_LOOPBACK_HOST}:{self.port}{CHATGPT_OAUTH_LOOPBACK_PATH}"

    def wait(self, timeout: float | None = None) -> ChatGptOAuthCallback:
        if not self._event.wait(timeout):
            raise TimeoutError("timed out waiting for ChatGPT OAuth callback")
        if self._result is not None:
            return self._result
        raise ChatGptOAuthLoopbackClosedError("ChatGPT OAuth loopback listener was closed")

    def close(self) -> None:
        should_stop = False
        with self._lock:
            if not self._closed:
                self._closed = True
                should_stop = True
                self._event.set()
        if should_stop:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)

    def _complete(self, result: ChatGptOAuthCallback) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._result = result
            self._event.set()

    def _close_async(self) -> None:
        threading.Thread(
            target=self.close,
            name=f"chatgpt-oauth-loopback-{self.port}-closer",
            daemon=True,
        ).start()


def bind_chatgpt_loopback(*, locale: str | None = None) -> ChatGptOAuthLoopbackListener:
    last_error: OSError | None = None
    for port in CHATGPT_OAUTH_LOOPBACK_PORTS:
        try:
            return ChatGptOAuthLoopbackListener(port, locale=locale)
        except OSError as exc:
            last_error = exc
    raise OSError("no ChatGPT OAuth loopback port is available") from last_error


def _single(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values or len(values) != 1 or not values[0]:
        return None
    return values[0]


def _handler_for(listener: ChatGptOAuthLoopbackListener) -> type[BaseHTTPRequestHandler]:
    class ChatGptOAuthCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path != CHATGPT_OAUTH_LOOPBACK_PATH:
                self.send_error(404)
                return
            params = parse_qs(parsed.query, keep_blank_values=True)
            state = _single(params, "state")
            code = _single(params, "code")
            error = _single(params, "error")
            if state is None or (code is None and error is None):
                self.send_error(400)
                return
            listener._complete(
                ChatGptOAuthCallback(
                    state=state,
                    code=code,
                    client_id=_single(params, "client_id"),
                    scope=_single(params, "scope"),
                    error=error,
                )
            )
            try:
                body = render_oauth_callback_completion_page(listener.locale)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            finally:
                listener._close_async()

        def log_message(self, format: str, *args: object) -> None:
            _ = format, args

    return ChatGptOAuthCallbackHandler


__all__ = [
    "CHATGPT_OAUTH_LOOPBACK_HOST",
    "CHATGPT_OAUTH_LOOPBACK_PATH",
    "CHATGPT_OAUTH_LOOPBACK_PORTS",
    "ChatGptOAuthCallback",
    "ChatGptOAuthLoopbackClosedError",
    "ChatGptOAuthLoopbackListener",
    "bind_chatgpt_loopback",
]
