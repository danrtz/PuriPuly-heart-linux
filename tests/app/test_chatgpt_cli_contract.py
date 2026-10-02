from __future__ import annotations

import json
from dataclasses import replace

import pytest

from puripuly_heart.app.ports.chatgpt_account import ChatGptConnectResult, ChatGptSignOutResult
from puripuly_heart.composition.headless_application import compose_headless_application
from puripuly_heart.config.settings_vnext.schema import AppSettingsVNext, SecretsIntent
from puripuly_heart.config.settings_vnext.serialization import to_dict


def _isolated_settings(path) -> None:
    settings = AppSettingsVNext()
    settings = replace(
        settings,
        intent=replace(
            settings.intent,
            secrets=SecretsIntent(backend="encrypted_file", encrypted_file_path="secrets.json"),
            osc=replace(settings.intent.osc, connection_mode="off"),
        ),
    )
    path.write_text(json.dumps(to_dict(settings)), encoding="utf-8")


@pytest.mark.asyncio
async def test_luna_defaults_to_chatgpt_and_reports_required_sign_in(tmp_path, monkeypatch):
    monkeypatch.setenv("PURIPULY_HEART_SECRETS_PASSPHRASE", "isolated-test-passphrase")
    path = tmp_path / "settings.json"
    _isolated_settings(path)
    app = compose_headless_application(path)
    try:
        await app.start()
        control = app.control()
        control.bind_instance("chatgpt-status")
        before = (await control.query("auth.status", {}))["chatgpt"]
        assert before == {"signed_in": False, "in_progress": False, "sign_in_required": False}

        submitted = await control.submit(
            "settings.apply",
            {"changes": {"translation.model": "gpt_6_luna"}},
            request_id="select-luna",
        )
        assert (await control.wait(submitted["operation_id"], timeout=10))["status"] in {
            "applied",
            "degraded",
        }
        translation = (await control.query("settings.current", {}))["settings"]["intent"][
            "translation"
        ]
        assert translation["connection"] == "chatgpt"
        after = (await control.query("auth.status", {}))["chatgpt"]
        assert after == {"signed_in": False, "in_progress": False, "sign_in_required": True}
        assert "email" not in after
    finally:
        await app.stop()


@pytest.mark.asyncio
async def test_cli_chatgpt_login_and_logout_report_outcomes(tmp_path, monkeypatch):
    monkeypatch.setenv("PURIPULY_HEART_SECRETS_PASSPHRASE", "isolated-test-passphrase")
    path = tmp_path / "settings.json"
    _isolated_settings(path)
    app = compose_headless_application(path)
    calls: list[dict[str, object]] = []

    async def connect_chatgpt(*, open_browser, authorization_url_sink):
        calls.append({"open_browser": open_browser})
        authorization_url_sink("https://auth.openai.com/api/accounts/authorize?state=x")
        return ChatGptConnectResult(succeeded=True, first_sign_in=True, email="u@example.com")

    async def sign_out_chatgpt():
        return ChatGptSignOutResult(remote_revoked=False)

    monkeypatch.setattr(app, "connect_chatgpt", connect_chatgpt)
    monkeypatch.setattr(app, "sign_out_chatgpt", sign_out_chatgpt)
    try:
        await app.start()
        control = app.control()
        control.bind_instance("chatgpt-cli")

        rejected = await control.submit(
            "auth.login",
            {"provider": "chatgpt", "referral_id": "PASS-1234"},
            request_id="chatgpt-referral",
        )
        assert (await control.wait(rejected["operation_id"], timeout=5))["status"] == "rejected"
        assert calls == []

        login = await control.submit(
            "auth.login", {"provider": "chatgpt"}, request_id="chatgpt-login"
        )
        result = await control.wait(login["operation_id"], timeout=5)
        assert result["status"] == "applied"
        assert result["provider"] == "chatgpt"
        assert result["first_sign_in"] is True
        assert "email" not in result
        assert calls == [{"open_browser": False}]

        logout = await control.submit(
            "auth.logout", {"provider": "chatgpt"}, request_id="chatgpt-logout"
        )
        signed_out = await control.wait(logout["operation_id"], timeout=5)
        assert signed_out["status"] == "applied"
        assert signed_out["scope"] == "local_only"
    finally:
        await app.stop()


@pytest.mark.asyncio
async def test_cli_chatgpt_login_failure_is_not_reported_as_success(tmp_path, monkeypatch):
    monkeypatch.setenv("PURIPULY_HEART_SECRETS_PASSPHRASE", "isolated-test-passphrase")
    path = tmp_path / "settings.json"
    _isolated_settings(path)
    app = compose_headless_application(path)

    async def connect_chatgpt(*, open_browser, authorization_url_sink):
        return ChatGptConnectResult(succeeded=False, failure_code="access_denied")

    monkeypatch.setattr(app, "connect_chatgpt", connect_chatgpt)
    try:
        await app.start()
        control = app.control()
        control.bind_instance("chatgpt-cli-denied")
        login = await control.submit(
            "auth.login", {"provider": "chatgpt"}, request_id="chatgpt-denied"
        )
        result = await control.wait(login["operation_id"], timeout=5)
        assert result["status"] == "rejected"
        assert result["reason"] == "access_denied"
    finally:
        await app.stop()


@pytest.mark.asyncio
async def test_selecting_chatgpt_translation_switches_to_luna_on_chatgpt(tmp_path, monkeypatch):
    monkeypatch.setenv("PURIPULY_HEART_SECRETS_PASSPHRASE", "isolated-test-passphrase")
    path = tmp_path / "settings.json"
    _isolated_settings(path)
    app = compose_headless_application(path)
    try:
        await app.start()
        control = app.control()
        control.bind_instance("chatgpt-select")
        before = (await control.query("settings.current", {}))["settings"]["intent"]["translation"]
        assert (before["model"], before["connection"]) != ("gpt_6_luna", "chatgpt")

        await app.select_chatgpt_translation()

        translation = (await control.query("settings.current", {}))["settings"]["intent"][
            "translation"
        ]
        assert translation["model"] == "gpt_6_luna"
        assert translation["connection"] == "chatgpt"
        assert translation["connection_history"]["gpt_6_luna"] == "chatgpt"
        assert (await control.query("auth.status", {}))["chatgpt"]["sign_in_required"] is True
    finally:
        await app.stop()
