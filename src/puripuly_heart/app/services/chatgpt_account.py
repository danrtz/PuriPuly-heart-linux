from __future__ import annotations

import asyncio
import contextlib
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from puripuly_heart.app.ports.chatgpt_account import (
    ChatGptAccountSnapshot,
    ChatGptConnectResult,
    ChatGptSignOutResult,
)
from puripuly_heart.core.chatgpt.loopback import (
    ChatGptOAuthLoopbackClosedError,
    ChatGptOAuthLoopbackListener,
    bind_chatgpt_loopback,
)
from puripuly_heart.core.chatgpt.oauth import (
    ChatGptAuthError,
    ChatGptIdTokenVerifier,
    build_authorization_request,
    exchange_authorization_code,
    token_set_from_response,
)
from puripuly_heart.core.chatgpt.session import ChatGptSession

CHATGPT_SIGN_IN_TIMEOUT_S = 600.0


@dataclass(slots=True)
class ChatGptAccountOwner:
    session: ChatGptSession
    locale_provider: Callable[[], str | None] = lambda: None
    browser_opener: Callable[[str], object] = webbrowser.open
    listener_factory: Callable[..., ChatGptOAuthLoopbackListener] = bind_chatgpt_loopback
    verifier_factory: Callable[[httpx.AsyncClient], ChatGptIdTokenVerifier] = ChatGptIdTokenVerifier
    timeout_s: float = CHATGPT_SIGN_IN_TIMEOUT_S
    _listener: ChatGptOAuthLoopbackListener | None = field(init=False, default=None, repr=False)
    _authorization_url: str | None = field(init=False, default=None, repr=False)

    @property
    def in_progress(self) -> bool:
        return self._listener is not None

    def snapshot(self) -> ChatGptAccountSnapshot:
        status = self.session.status()
        return ChatGptAccountSnapshot(
            signed_in=status.signed_in,
            email=status.email,
            in_progress=self.in_progress,
        )

    def reopen_authorization_url(self) -> bool:
        url = self._authorization_url
        if url is None:
            return False
        self.browser_opener(url)
        return True

    async def connect(
        self,
        *,
        open_browser: bool = True,
        authorization_url_sink: Callable[[str], None] | None = None,
    ) -> ChatGptConnectResult:
        if self._listener is not None:
            self.reopen_authorization_url()
            return ChatGptConnectResult(succeeded=False, failure_code="in_progress")
        try:
            return await self._connect(
                open_browser=open_browser,
                authorization_url_sink=authorization_url_sink,
            )
        except ChatGptAuthError as exc:
            return ChatGptConnectResult(succeeded=False, failure_code=exc.code)
        except ChatGptOAuthLoopbackClosedError:
            return ChatGptConnectResult(succeeded=False, failure_code="cancelled")
        except TimeoutError:
            return ChatGptConnectResult(succeeded=False, failure_code="timeout")
        except OSError:
            return ChatGptConnectResult(succeeded=False, failure_code="loopback_unavailable")
        except httpx.HTTPError:
            return ChatGptConnectResult(succeeded=False, failure_code="network_error")

    async def sign_out(self) -> ChatGptSignOutResult:
        return ChatGptSignOutResult(remote_revoked=await self.session.sign_out())

    def cancel(self) -> None:
        listener = self._listener
        if listener is not None:
            listener.close()

    async def close(self) -> None:
        self.cancel()
        await self.session.close()

    async def _connect(
        self,
        *,
        open_browser: bool,
        authorization_url_sink: Callable[[str], None] | None,
    ) -> ChatGptConnectResult:
        saved_client_id = self.session.client_id()
        listener = self.listener_factory(locale=self.locale_provider())
        self._listener = listener
        try:
            request = build_authorization_request(
                redirect_uri=listener.redirect_uri,
                host_id=self.session.host_id(),
                client_id=saved_client_id,
                login_hint=self.session.login_hint() if saved_client_id else None,
            )
            self._authorization_url = request.url
            if authorization_url_sink is not None:
                authorization_url_sink(request.url)
            if open_browser:
                self.browser_opener(request.url)
            callback = await asyncio.to_thread(listener.wait, self.timeout_s)
        finally:
            self._listener = None
            self._authorization_url = None
            with contextlib.suppress(Exception):
                listener.close()

        if callback.state != request.state:
            raise ChatGptAuthError("state_mismatch")
        if callback.error is not None:
            raise ChatGptAuthError(
                "access_denied" if callback.error == "access_denied" else "authorization_failed"
            )
        if callback.code is None:
            raise ChatGptAuthError("authorization_failed")
        if saved_client_id is None:
            client_id = callback.client_id
            if not client_id:
                raise ChatGptAuthError("registration_incomplete")
        else:
            if callback.client_id and callback.client_id != saved_client_id:
                raise ChatGptAuthError("client_mismatch")
            client_id = saved_client_id

        http = self.session.http()
        payload = await exchange_authorization_code(
            http,
            client_id=client_id,
            code=callback.code,
            code_verifier=request.code_verifier,
            redirect_uri=request.redirect_uri,
        )
        tokens = token_set_from_response(payload)
        if tokens.id_token is None:
            raise ChatGptAuthError("invalid_id_token")
        identity = await self.verifier_factory(http).verify(
            tokens.id_token, client_id=client_id, nonce=request.nonce
        )
        if not tokens.plan_usage_granted:
            raise ChatGptAuthError("plan_scope_missing")
        await asyncio.to_thread(
            self.session.store_sign_in,
            client_id=client_id,
            tokens=tokens,
            identity=identity,
        )
        return ChatGptConnectResult(
            succeeded=True,
            first_sign_in=saved_client_id is None,
            email=identity.email,
        )


__all__ = [
    "CHATGPT_SIGN_IN_TIMEOUT_S",
    "ChatGptAccountOwner",
]
