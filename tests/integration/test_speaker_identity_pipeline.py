from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from puripuly_heart.core.audio.ownership import (
    AudioSegmentIdentity,
    AudioSegmentSettingsSnapshot,
    AudioSegmentSnapshot,
    AudioSegmentTerminalReceipt,
)
from puripuly_heart.core.clock import FakeClock
from puripuly_heart.core.overlay.presenter import OverlayPresenter
from puripuly_heart.core.stt.backend import STTProviderTurnIdentity, STTProviderTurnTerminal
from puripuly_heart.core.stt.scoped_normalizer import STTScopedTurnNormalizer
from puripuly_heart.domain.models import Translation
from puripuly_heart.providers.stt.soniox import _FinalizeRequest, _SonioxSession
from puripuly_heart.ui.overlay_calibration import OverlayCalibration
from tests.helpers.fakes import RecordingOscQueue
from tests.helpers.translation_owners import compose_translation_test_harness


@dataclass(slots=True)
class _IndexedTranslationProvider:
    calls: list[str] = field(default_factory=list)
    response_mode: str = "valid"

    async def translate(
        self,
        *,
        utterance_id,
        text: str,
        system_prompt: str,
        source_language: str,
        target_language: str,
        context: str = "",
        scene_participant_count: int | None = None,
    ) -> Translation:
        self.calls.append(text)
        if text.startswith('{"segments":'):
            segments = json.loads(text)["segments"]
            translations = {
                "Alice ": "Hello",
                "Beto ": "World",
                "Beto": "World",
                "Alice": "Again",
                "alpha ": "First",
                "beta": "Second",
            }
            items = [
                {"index": item["index"], "text": translations[item["text"]]}
                for item in reversed(segments)
            ]
            if self.response_mode == "missing":
                items.pop()
            if self.response_mode == "duplicate":
                items[-1]["index"] = items[0]["index"]
            rendered = json.dumps({"segments": items})
        else:
            rendered = {"self": "manual"}[text]
        return Translation(
            utterance_id=utterance_id,
            text=rendered,
            source_text=text,
            source_language=source_language,
            target_language=target_language,
            channel="peer",
        )

    async def close(self) -> None:
        return None


@dataclass(slots=True)
class _FailingSelectedTranslationProvider(_IndexedTranslationProvider):
    async def translate(self, **kwargs) -> Translation:
        raise RuntimeError("selected translation failure")


@dataclass(slots=True)
class _StallingBatchTranslationProvider(_IndexedTranslationProvider):
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)

    async def translate(self, **kwargs) -> Translation:
        text = kwargs["text"]
        self.calls.append(text)
        if text.startswith('{"segments":'):
            self.entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()
        return Translation(
            utterance_id=kwargs["utterance_id"],
            text="Later",
            source_text=text,
            source_language=kwargs["source_language"],
            target_language=kwargs["target_language"],
            channel="peer",
        )


@dataclass(slots=True)
class _RecordingOverlaySink:
    presenter: OverlayPresenter
    events: list[object] = field(default_factory=list)

    async def emit(self, event: object) -> None:
        self.events.append(event)
        await self.presenter.emit(event)  # type: ignore[arg-type]


def _soniox_session() -> _SonioxSession:
    return _SonioxSession(
        api_key="test",
        model="stt-rt-v5",
        endpoint="wss://example.invalid",
        sample_rate_hz=16000,
        language_hints=["en"],
        context_terms=[],
        keepalive_interval_s=10.0,
        trailing_silence_ms=100,
        connect_timeout_s=1.0,
        enable_language_identification=True,
        enable_speaker_diarization=True,
    )


def _settings() -> AudioSegmentSettingsSnapshot:
    return AudioSegmentSettingsSnapshot(
        provider_id="soniox",
        provider_signature=("soniox",),
        runtime_signature=("soniox",),
        source_mode="desktop",
        source_language="en",
        expected_languages=("en",),
        target_sample_rate_hz=16000,
        vad_speech_threshold=0.4,
        vad_hangover_ms=800,
        vad_pre_roll_ms=500,
    )


async def _terminal_from_soniox_tokens(
    session: _SonioxSession,
    *,
    speaker: str,
    text: str,
    start_ms: int,
    tokens: list[dict[str, object]] | None = None,
    end_ms: int,
    generation: int,
    order: int,
) -> tuple[AudioSegmentTerminalReceipt, STTProviderTurnTerminal]:
    await session.on_speech_end(trailing_silence_ms=500)
    assert isinstance(await session._audio_q.get(), _FinalizeRequest)
    message_tokens = (
        tokens
        if tokens is not None
        else [
            {
                "text": text,
                "language": "en",
                "speaker": speaker,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "confidence": 0.97,
                "is_final": True,
            }
        ]
    )
    session._handle_message(
        json.dumps(
            {
                "tokens": message_tokens + [{"text": "<fin>", "is_final": True}],
            }
        )
    )
    event = session._event_projection._legacy_events.get_nowait()
    segment_id = uuid4()
    segment_identity = AudioSegmentIdentity(generation, order, segment_id, 1)
    provider_identity = STTProviderTurnIdentity(
        segment=segment_identity,
        provider_epoch_id=f"epoch-{generation}",
        provider_turn_id=f"turn-{generation}-{order}",
    )
    snapshot = AudioSegmentSnapshot(
        identity=segment_identity,
        settings=_settings(),
        content_ranges=(),
        context_ranges=(),
        failed_ranges=(),
        content_sample_count=0,
        context_sample_count=0,
        failed_normalized_sample_count=0,
        failed_source_sample_count=0,
        prefix_context_sample_count=0,
        synthetic_context_sample_count=0,
        genuine_onset=True,
        state="terminal",
        opened_at_monotonic_s=0.0,
        sealed_at_monotonic_s=0.0,
        seal_reason="silence",
    )
    receipt = AudioSegmentTerminalReceipt(
        identity=segment_identity,
        outcome="final",
        segment=snapshot,
        terminal_at_monotonic_s=0.0,
        provider_epoch_id=provider_identity.provider_epoch_id,
        provider_turn_id=provider_identity.provider_turn_id,
        text_authority="authoritative",
    )
    terminal = STTScopedTurnNormalizer(provider_identity).apply_terminal(
        STTProviderTurnTerminal(
            identity=provider_identity,
            outcome="final",
            text=event.text,
            final_language_runs=event.final_language_runs,
            final_speaker_runs=event.final_speaker_runs,
            text_authority="authoritative",
        )
    )
    return receipt, terminal


@pytest.mark.asyncio
async def test_soniox_batch_preserves_attribution_through_output_and_presenter() -> None:
    clock = FakeClock(_now=100.0)

    async def advance(seconds: float) -> None:
        await asyncio.sleep(seconds)
        clock.advance(seconds)

    presenter = OverlayPresenter(calibration=OverlayCalibration(), clock=clock, sleep=advance)
    provider = _IndexedTranslationProvider()
    overlay = _RecordingOverlaySink(presenter)
    harness = compose_translation_test_harness(
        stt=None,
        llm=provider,
        osc=RecordingOscQueue(),
        peer_translation_enabled=True,
        overlay_sink=overlay,
        clock=clock,
    )
    session = _soniox_session()
    harness.output_runtime.activate_peer_generation(1)
    await harness.start()
    try:
        tokens = [
            {
                "text": word,
                "language": language,
                "speaker": speaker,
                "start_ms": index * 100,
                "end_ms": index * 100 + 90,
                "confidence": 0.01,
                "is_final": True,
            }
            for index, (word, language, speaker) in enumerate(
                [("Alice ", "en", "A"), ("Beto ", "es", "B"), ("Alice", "en", "A")],
                start=1,
            )
        ]
        receipt, terminal = await _terminal_from_soniox_tokens(
            session,
            speaker="A",
            text="",
            start_ms=100,
            end_ms=390,
            tokens=tokens,
            generation=1,
            order=1,
        )
        assert terminal.text == "Alice Beto Alice"
        assert [run.attribution.state for run in terminal.final_speaker_runs] == [
            "identified",
            "identified",
            "identified",
        ]
        harness.record_peer_speech_end_for_test(receipt.identity.segment_id)
        await harness.peer_owner.handle_provider_turn_terminal(receipt, terminal)
        await harness.peer_owner.translation_turns.wait_for_idle()
        await harness.output_runtime.wait_for_peer_output_idle()
        assert len(provider.calls) == 1
        submitted = json.loads(provider.calls[0])["segments"]
        assert [part["text"] for part in submitted] == ["Alice ", "Beto ", "Alice"]
        events = [
            event for event in overlay.events if getattr(event, "type", None) == "translation_final"
        ]
        assert [event.source_text for event in events] == ["Alice ", "Beto ", "Alice"]
        assert [event.text for event in events] == ["Hello", "World", "Again"]
        assert [event.speaker_assignment.palette_index for event in events] == [0, 1, 0]
        assert [event.speaker_assignment.source_text_range for event in events] == [
            (0, 6),
            (6, 11),
            (11, 16),
        ]
        latest = presenter.snapshot().blocks
        assert latest[-1].speaker_style == "gold"
        assert latest[-1].primary_text == "Again"
        assert latest[-1].secondary_text == "Alice"
    finally:
        await harness.stop()
        await presenter.close()


@pytest.mark.parametrize("response_mode", ("missing", "duplicate"))
@pytest.mark.asyncio
async def test_bad_batch_response_keeps_every_source_fragment(response_mode: str) -> None:
    clock = FakeClock(_now=100.0)
    presenter = OverlayPresenter(calibration=OverlayCalibration(), clock=clock)
    provider = _IndexedTranslationProvider(response_mode=response_mode)
    overlay = _RecordingOverlaySink(presenter)
    harness = compose_translation_test_harness(
        stt=None,
        llm=provider,
        osc=RecordingOscQueue(),
        peer_translation_enabled=True,
        overlay_sink=overlay,
        clock=clock,
    )
    session = _soniox_session()
    harness.output_runtime.activate_peer_generation(1)
    await harness.start()
    try:
        receipt, terminal = await _terminal_from_soniox_tokens(
            session,
            speaker="A",
            text="",
            start_ms=100,
            end_ms=290,
            tokens=[
                {
                    "text": word,
                    "speaker": speaker,
                    "language": "en",
                    "start_ms": index * 100,
                    "end_ms": index * 100 + 90,
                    "is_final": True,
                }
                for index, (word, speaker) in enumerate(
                    [("alpha ", "A"), ("beta", "B")],
                    start=1,
                )
            ],
            generation=1,
            order=1,
        )
        harness.record_peer_speech_end_for_test(receipt.identity.segment_id)
        await harness.peer_owner.handle_provider_turn_terminal(receipt, terminal)
        await harness.peer_owner.translation_turns.wait_for_idle()
        await harness.output_runtime.wait_for_peer_output_idle()
        assert len(provider.calls) == 1
        original = [
            event.text
            for event in overlay.events
            if getattr(event, "type", None) == "peer_transcript_final"
        ]
        assert original == ["alpha ", "beta"]
        assert not any(
            getattr(event, "type", None) == "translation_final" for event in overlay.events
        )
    finally:
        await harness.stop()
        await presenter.close()


@pytest.mark.asyncio
async def test_parent_admission_allocates_every_speaker_before_child_ui_yields() -> None:
    harness = compose_translation_test_harness(
        stt=None,
        llm=None,
        osc=RecordingOscQueue(),
        peer_translation_enabled=False,
    )
    session = _soniox_session()
    entered = asyncio.Event()
    second_created = asyncio.Event()
    release = asyncio.Event()
    original_child_created = harness.translation_turns.on_child_created
    observed: dict[str, int | None] = {}

    async def block_after_first_child(child):
        if child.transcript.text == "Cora":
            assignment = harness.peer_owner._speaker_identities.assignment_for(child.utterance_id)
            observed[child.transcript.text] = (
                None if assignment is None else assignment.palette_index
            )
            second_created.set()
        await original_child_created(child)
        assignment = harness.peer_owner._speaker_identities.assignment_for(child.utterance_id)
        observed[child.transcript.text] = None if assignment is None else assignment.palette_index
        if child.transcript.text == "Alice ":
            entered.set()
            await release.wait()

    harness.translation_turns.on_child_created = block_after_first_child
    harness.output_runtime.activate_peer_generation(1)
    await harness.start()
    try:
        first_receipt, first_terminal = await _terminal_from_soniox_tokens(
            session,
            speaker="A",
            text="",
            start_ms=100,
            end_ms=290,
            generation=1,
            order=1,
            tokens=[
                {
                    "text": text,
                    "speaker": speaker,
                    "language": "en",
                    "is_final": True,
                    "start_ms": index * 100,
                    "end_ms": index * 100 + 90,
                }
                for index, (text, speaker) in enumerate((("Alice ", "A"), ("Beto", "B")), start=1)
            ],
        )
        second_receipt, second_terminal = await _terminal_from_soniox_tokens(
            session,
            speaker="C",
            text="Cora",
            start_ms=300,
            end_ms=390,
            generation=1,
            order=2,
        )
        harness.record_peer_speech_end_for_test(first_receipt.identity.segment_id)
        harness.record_peer_speech_end_for_test(second_receipt.identity.segment_id)
        first = asyncio.create_task(
            harness.peer_owner.handle_provider_turn_terminal(first_receipt, first_terminal)
        )
        await asyncio.wait_for(entered.wait(), 2)
        second = asyncio.create_task(
            harness.peer_owner.handle_provider_turn_terminal(second_receipt, second_terminal)
        )
        await asyncio.wait_for(second_created.wait(), 2)
        assert observed == {"Alice ": 0, "Cora": 2}
        release.set()
        await asyncio.wait_for(first, 2)
        await asyncio.wait_for(second, 2)
        await asyncio.wait_for(harness.translation_turns.wait_for_idle(), 4)
        assert observed["Beto"] == 1
    finally:
        release.set()
        await harness.stop()


@pytest.mark.asyncio
async def test_stalled_peer_batch_times_out_and_releases_source_order() -> None:
    clock = FakeClock(_now=100.0)
    presenter = OverlayPresenter(calibration=OverlayCalibration(), clock=clock)
    provider = _StallingBatchTranslationProvider()
    overlay = _RecordingOverlaySink(presenter)
    harness = compose_translation_test_harness(
        stt=None,
        llm=provider,
        osc=RecordingOscQueue(),
        peer_translation_enabled=True,
        overlay_sink=overlay,
        clock=clock,
    )
    session = _soniox_session()
    harness.translation_turns.child_watchdog_s = 0.08
    harness.output_runtime.activate_peer_generation(1)
    await harness.start()
    try:
        first_receipt, first_terminal = await _terminal_from_soniox_tokens(
            session,
            speaker="A",
            text="",
            start_ms=100,
            end_ms=290,
            generation=1,
            order=1,
            tokens=[
                {
                    "text": text,
                    "speaker": speaker,
                    "language": "en",
                    "is_final": True,
                    "start_ms": index * 100,
                    "end_ms": index * 100 + 90,
                }
                for index, (text, speaker) in enumerate((("alpha ", "A"), ("beta", "B")), start=1)
            ],
        )
        second_receipt, second_terminal = await _terminal_from_soniox_tokens(
            session,
            speaker="C",
            text="Cora",
            start_ms=300,
            end_ms=390,
            generation=1,
            order=2,
        )
        harness.record_peer_speech_end_for_test(first_receipt.identity.segment_id)
        harness.record_peer_speech_end_for_test(second_receipt.identity.segment_id)
        await harness.peer_owner.handle_provider_turn_terminal(first_receipt, first_terminal)
        await asyncio.wait_for(provider.entered.wait(), 2)
        await harness.peer_owner.handle_provider_turn_terminal(second_receipt, second_terminal)
        await asyncio.wait_for(harness.translation_turns.wait_for_idle(), 2)
        await asyncio.wait_for(harness.output_runtime.wait_for_peer_output_idle(), 2)
        assert provider.cancelled.is_set()
        assert len(provider.calls) == 2
        assert provider.calls[1] == "Cora"
        events = [
            (event.type, event.text)
            for event in overlay.events
            if getattr(event, "type", None) in {"peer_transcript_final", "translation_final"}
        ]
        assert events == [
            ("peer_transcript_final", "alpha "),
            ("peer_transcript_final", "beta"),
            ("translation_final", "Later"),
        ]
    finally:
        await harness.stop()
        await presenter.close()
