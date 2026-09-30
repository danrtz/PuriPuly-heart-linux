from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RecognitionStreamIdentity:
    channel: Literal["self", "peer"]
    activation_generation: int
    capture_epoch: int
    provider_epoch_id: str
    settings_scope: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class RecognitionUnitIdentity:
    stream: RecognitionStreamIdentity
    unit_id: UUID
    receipt_sequence: int


@dataclass(frozen=True, slots=True)
class NativeTranscriptionEvidence:
    finished: bool | None = None
    language_code: str | None = None
    speaker_label: str | None = None
    words: tuple[tuple[str | None, str | None, str | None], ...] = ()


@dataclass(frozen=True, slots=True)
class RecognitionTextOrigin:
    identity: RecognitionUnitIdentity
    text_start: int
    text_end: int
    native: NativeTranscriptionEvidence | None = None
    source_binding: Literal["stream_scoped"] = "stream_scoped"
    order_basis: Literal["provider_receipt"] = "provider_receipt"


def slice_recognition_origins(
    origins: tuple[RecognitionTextOrigin, ...], start: int, end: int
) -> tuple[RecognitionTextOrigin, ...]:
    return tuple(
        RecognitionTextOrigin(
            origin.identity,
            max(origin.text_start, start) - start,
            min(origin.text_end, end) - start,
            origin.native,
        )
        for origin in origins
        if origin.text_start < end and origin.text_end > start
    )
