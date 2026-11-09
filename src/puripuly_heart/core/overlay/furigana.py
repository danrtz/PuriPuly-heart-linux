from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class RubySegment:
    text: str
    reading: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"text": self.text, "reading": self.reading}


def has_kanji(text: str) -> bool:
    return any(
        "\u3400" <= char <= "\u4dbf"
        or "\u4e00" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
        or "\U00020000" <= char <= "\U000323af"
        or char in "々〻"
        for char in text
    )


_lock = threading.Lock()
_converter = None
_logger = logging.getLogger(__name__)


def _hiragana(text: str) -> bool:
    return bool(text) and all("ぁ" <= char <= "ゖ" or char in "ゝゞー" for char in text)


@lru_cache(maxsize=512)
def japanese_readings(text: str, language: str | None) -> tuple[RubySegment, ...]:
    if (language or "").lower().replace("_", "-").split("-")[0] != "ja" or not has_kanji(text):
        return ()
    global _converter
    try:
        with _lock:
            if _converter is None:
                from fugashi import Tagger

                _converter = Tagger()
            tokens = [(word.surface, word.feature.kana or "") for word in _converter(text)]
    except Exception:
        _logger.warning("Japanese reading dictionary unavailable; marking unknown readings")
        return tuple(RubySegment(char, "？" if has_kanji(char) else "") for char in text)
    segments: list[RubySegment] = []
    offset = 0
    for index, (base, reading) in enumerate(tokens):
        if base == "日本" and index + 1 < len(tokens) and tokens[index + 1][0] in {"語", "人"}:
            reading = "ニホン"
        start = text.find(base, offset)
        if start > offset:
            segments.append(RubySegment(text[offset:start]))
        offset = start + len(base)
        reading = "".join(
            chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char for char in reading
        )
        if not has_kanji(base):
            segments.append(RubySegment(base))
            continue
        prefix, suffix = "", ""
        while base and reading and not has_kanji(base[0]) and base[0] == reading[0]:
            prefix += base[0]
            base, reading = base[1:], reading[1:]
        while base and reading and not has_kanji(base[-1]) and base[-1] == reading[-1]:
            suffix = base[-1] + suffix
            base, reading = base[:-1], reading[:-1]
        if prefix:
            segments.append(RubySegment(prefix))
        segments.append(RubySegment(base, reading if _hiragana(reading) else "？"))
        if suffix:
            segments.append(RubySegment(suffix))
    if offset < len(text):
        segments.append(RubySegment(text[offset:]))
    if "".join(segment.text for segment in segments) != text:
        return tuple(RubySegment(char, "？" if has_kanji(char) else "") for char in text)
    return tuple(segments)


def ruby_from_payload(value: object, text: str) -> tuple[RubySegment, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("ruby segments must be an array")
    segments = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise ValueError("ruby segment must contain text")
        reading = item.get("reading", "")
        if not isinstance(reading, str) or reading and reading != "？" and not _hiragana(reading):
            raise ValueError("ruby reading must be hiragana")
        segments.append(RubySegment(item["text"], reading))
    if segments and "".join(segment.text for segment in segments) != text:
        raise ValueError("ruby segments must preserve caption text")
    return tuple(segments)
