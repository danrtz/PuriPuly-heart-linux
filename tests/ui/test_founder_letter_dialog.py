from __future__ import annotations

import inspect

import pytest

from tests.helpers.flet_page import DialogTrackingPage as DummyPage

pytest.importorskip("flet")

from puripuly_heart.ui.components.founder_letter_dialog import (
    FOUNDER_LETTER_PARAGRAPH_KEYS,
    FounderLetterDialog,
)
from puripuly_heart.ui.i18n import set_locale, t


def _body_text_value(page: DummyPage) -> str:
    def walk(control):
        yield control
        nested_controls = getattr(control, "controls", None)
        if nested_controls:
            for nested in nested_controls:
                yield from walk(nested)
        nested_content = getattr(control, "content", None)
        if nested_content is not None:
            yield from walk(nested_content)

    for control in walk(page.dialog.content):
        if control.__class__.__name__ == "Text" and getattr(control, "selectable", False):
            return control.value
    raise AssertionError("dialog content did not include selectable body text")


def _dialog_with_readme_action(page: DummyPage, action) -> FounderLetterDialog:
    signature = inspect.signature(FounderLetterDialog)
    if "on_readme" not in signature.parameters:
        pytest.fail("FounderLetterDialog must expose an explicit on_readme callback")
    return FounderLetterDialog(
        page,
        on_readme=action,
        on_connect=lambda: pytest.fail("legacy on_connect must not be reused"),
        on_contact=lambda: pytest.fail("Founder Letter no longer uses contact action"),
    )


def test_founder_letter_dialog_opens_with_chatgpt_and_guide_actions() -> None:
    set_locale("ko")
    page = DummyPage()

    dialog = FounderLetterDialog(page)

    dialog.open()

    assert page.dialog is dialog._dialog
    assert dialog._cancel_button is None
    assert len(page.opened) == 1
    assert dialog._chatgpt_button is not None
    assert dialog._acknowledge_button is not None
    assert dialog._chatgpt_button.content == t("openrouter.handoff.chatgpt")
    assert dialog._acknowledge_button.content == t("openrouter.handoff.guide")


def test_founder_letter_dialog_chatgpt_action_closes_before_continuing() -> None:
    set_locale("ko")
    page = DummyPage()
    calls: list[bool] = []

    dialog = FounderLetterDialog(
        page,
        on_readme=lambda: pytest.fail("guide must not open"),
        on_chatgpt=lambda: calls.append(page.dialog is None),
    )
    dialog.open()

    assert dialog._chatgpt_button is not None
    dialog._chatgpt_button.on_click(None)

    assert calls == [True]
    assert page.closed == [dialog._dialog]


def test_founder_letter_dialog_uses_requested_letter_copy() -> None:
    set_locale("ko")
    page = DummyPage()

    FounderLetterDialog(page).open()

    expected_body = "\n\n".join(t(key) for key in FOUNDER_LETTER_PARAGRAPH_KEYS)
    assert _body_text_value(page) == expected_body


def test_founder_letter_dialog_dismisses_on_outside_click() -> None:
    set_locale("ko")
    page = DummyPage()

    dialog = FounderLetterDialog(page)

    dialog.open()

    assert dialog._dialog is not None
    assert dialog._dialog.modal is False


def test_founder_letter_dialog_guide_action_closes_before_opening_guide() -> None:
    set_locale("ko")
    page = DummyPage()
    readme_calls: list[bool] = []

    readme_dialog = _dialog_with_readme_action(
        page,
        lambda: readme_calls.append(page.dialog is None),
    )
    readme_dialog.open()

    assert readme_dialog._acknowledge_button is not None
    readme_dialog._acknowledge_button.on_click(None)

    assert readme_calls == [True]
    assert page.closed == [readme_dialog._dialog]
    assert page.dialog is None


def test_founder_letter_dialog_ignores_legacy_callbacks() -> None:
    set_locale("ko")
    page = DummyPage()

    legacy_dialog = FounderLetterDialog(
        page,
        on_connect=lambda: pytest.fail("legacy connect callback must stay ignored"),
        on_contact=lambda: pytest.fail("legacy contact callback must stay ignored"),
    )
    legacy_dialog.open()

    assert legacy_dialog._acknowledge_button is not None
    legacy_dialog._acknowledge_button.on_click(None)

    assert page.closed == [legacy_dialog._dialog]
    assert page.dialog is None
