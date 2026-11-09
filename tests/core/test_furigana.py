from dataclasses import replace
from uuid import uuid4

import pytest

from puripuly_heart.config.overlay_calibration import OverlayCalibration
from puripuly_heart.config.settings_vnext.schema import AppSettingsVNext
from puripuly_heart.config.settings_vnext.serialization import from_dict, to_dict
from puripuly_heart.core.overlay.furigana import has_kanji, japanese_readings
from puripuly_heart.core.overlay.presenter import OverlayPresenter
from puripuly_heart.core.overlay.protocol import OverlayPresentationBlock
from puripuly_heart.core.overlay.sink import SelfActiveUpdate


@pytest.mark.parametrize(
    "text",
    [
        "今日も元気です。",
        "東京で食べる。",
        "漢字とカタカナとEnglish123。",
        "𠮷野家 👋",
        "  読む\n漢字  ",
    ],
)
def test_readings_preserve_original_and_annotate_every_kanji(text):
    segments = japanese_readings(text, "ja")
    assert "".join(segment.text for segment in segments) == text
    assert all(segment.reading for segment in segments if has_kanji(segment.text))
    assert all(not has_kanji(segment.reading) for segment in segments)


def test_reading_attaches_to_kanji_without_repeating_kana_ending():
    segments = japanese_readings("食べる", "ja")
    assert [(s.text, s.reading) for s in segments] == [("食", "た"), ("べる", "")]


def test_english_and_kana_only_need_no_annotations():
    assert japanese_readings("Hello 東京!", "en") == ()
    assert japanese_readings("ひらがなとカタカナ", "ja") == ()


def test_ruby_protocol_preserves_original_and_rejects_invalid_readings():
    block = OverlayPresentationBlock(
        "self:1",
        "self:1",
        1,
        "self",
        "finalized",
        "東京",
        "Tokyo",
        True,
        primary_language="ja",
        secondary_language="en",
        primary_ruby=japanese_readings("東京", "ja"),
    )
    assert OverlayPresentationBlock.from_dict(block.to_dict()) == block
    for ruby in [[{"text": "大阪", "reading": "おおさか"}], [{"text": "東京", "reading": "Tokyo"}]]:
        with pytest.raises(ValueError):
            OverlayPresentationBlock.from_dict(block.to_dict() | {"primary_ruby": ruby})


def test_settings_persist_furigana_with_safe_default():
    settings = AppSettingsVNext()
    assert not settings.intent.overlay.japanese_furigana
    settings = replace(
        settings,
        intent=replace(
            settings.intent, overlay=replace(settings.intent.overlay, japanese_furigana=True)
        ),
    )
    assert from_dict(to_dict(settings)).intent.overlay.japanese_furigana


@pytest.mark.parametrize(
    "source,primary,target,secondary,ruby_field",
    [
        ("ja", "東京で食べる。", "en", "Eating in Tokyo.", "primary_ruby"),
        ("en", "Eating in Tokyo.", "ja", "東京で食べる。", "secondary_ruby"),
    ],
)
async def test_presenter_annotates_originals_and_translations_without_changing_text(
    source, primary, target, secondary, ruby_field
):
    presenter = OverlayPresenter(OverlayCalibration())
    event = SelfActiveUpdate(
        event_id="self:test",
        seq=1,
        utterance_id=uuid4(),
        channel="self",
        created_at=presenter.clock.now(),
        occupant_key="test",
        text=primary,
        secondary_text=secondary,
        source_language=source,
        target_language=target,
    )
    try:
        await presenter.emit(event)
        assert not getattr(presenter.snapshot().blocks[0], ruby_field)
        await presenter.update_display_preferences(
            show_translation=True, show_peer_original=True, japanese_furigana=True
        )
        block = presenter.snapshot().blocks[0]
        assert (block.primary_text, block.secondary_text) == (primary, secondary)
        assert getattr(block, ruby_field)
        await presenter.update_display_preferences(
            show_translation=True, show_peer_original=True, japanese_furigana=False
        )
        assert not getattr(presenter.snapshot().blocks[0], ruby_field)
    finally:
        await presenter.close()


def test_dictionary_failure_keeps_original_and_marks_unknown_readings(monkeypatch):
    from puripuly_heart.core.overlay import furigana

    class FailedDictionary:
        def __call__(self, text):
            raise RuntimeError("dictionary unavailable")

    monkeypatch.setattr(furigana, "_converter", FailedDictionary())
    text = "未登録の漢字です。"
    result = japanese_readings(text, "ja")
    assert "".join(segment.text for segment in result) == text
    assert all(segment.reading == "？" for segment in result if has_kanji(segment.text))
    japanese_readings.cache_clear()
