from __future__ import annotations

from collections import OrderedDict

from puripuly_heart.core.stt.backend import STTRecognitionUnit, STTRecognitionUnitTerminal
from puripuly_heart.domain.models import Transcript
from puripuly_heart.domain.recognition import RecognitionStreamIdentity, RecognitionTextOrigin


class RecognitionConsumptionLedger:
    def __init__(self) -> None:
        self._receipt_sequences: OrderedDict[RecognitionStreamIdentity, int] = OrderedDict()

    def consume(self, terminal: STTRecognitionUnitTerminal) -> bool:
        identity = terminal.unit.identity
        previous = self._receipt_sequences.get(identity.stream, 0)
        if identity.receipt_sequence <= previous:
            return False
        self._receipt_sequences[identity.stream] = identity.receipt_sequence
        self._receipt_sequences.move_to_end(identity.stream)
        while len(self._receipt_sequences) > 4096:
            self._receipt_sequences.popitem(last=False)
        return terminal.outcome in {"final", "empty"}


def recognition_transcript(
    unit: STTRecognitionUnit, *, created_at: float, publication_order: int | None = None
) -> Transcript:
    return Transcript(
        utterance_id=unit.identity.unit_id,
        text=unit.text,
        is_final=True,
        created_at=created_at,
        channel=unit.identity.stream.channel,
        final_language_runs=unit.final_language_runs,
        final_speaker_runs=unit.final_speaker_runs,
        publication_generation=(
            unit.identity.stream.activation_generation if publication_order is not None else None
        ),
        source_order=publication_order,
        recognition_origins=(
            RecognitionTextOrigin(unit.identity, 0, len(unit.text), unit.provenance.transcription),
        ),
    )
