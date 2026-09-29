from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from puripuly_heart.app.wiring.wiring_capture_runtime import CaptureDiagnosticsAdapter
from puripuly_heart.composition.application_runtime import _require_self_capture_owner
from puripuly_heart.core.self_capture import (
    SelfCaptureDiagnostic,
    SelfCaptureDiagnosticEvent,
    SelfCaptureFailureReason,
    SelfCaptureSessionState,
)


def test_reacquires_self_capture_with_direct_self_translation_owner() -> None:
    self_translation_channel = object()
    local_asr_runtime = object()
    audio_gate = object()
    created_owner = object()
    calls: list[tuple[object, object, object, object]] = []
    pipeline = SimpleNamespace(
        self_capture=None,
        self_translation_channel=self_translation_channel,
        local_asr_runtime=local_asr_runtime,
        vrc_mic_audio_gate=audio_gate,
    )

    class Factory:
        @staticmethod
        def compose_self(
            vad_runtime: object,
            provider_runtime: object,
            channel_reset: object,
            gate: object,
        ) -> object:
            calls.append((vad_runtime, provider_runtime, channel_reset, gate))
            return created_owner

    owner = _require_self_capture_owner(
        cast(Any, pipeline),
        cast(Any, Factory()),
    )
    reused = _require_self_capture_owner(
        cast(Any, pipeline),
        cast(Any, Factory()),
    )

    assert owner is created_owner
    assert reused is created_owner
    assert pipeline.self_capture is created_owner
    assert calls == [
        (
            self_translation_channel,
            local_asr_runtime,
            self_translation_channel,
            audio_gate,
        )
    ]


def test_self_capture_failure_emits_one_safe_diagnostic_with_terminal_identity() -> None:
    basic: list[str] = []
    diagnostic: list[str] = []
    adapter = CaptureDiagnosticsAdapter(
        debug_allowed=lambda: False,
        capture_fault_profile=lambda: "none",
        log_diagnostic=diagnostic.append,
        log_basic=basic.append,
    )
    utterance_id = uuid4()
    epoch = uuid4().hex
    turn = uuid4().hex
    adapter.self_capture(
        SelfCaptureDiagnostic(
            event=SelfCaptureDiagnosticEvent.FAILURE,
            generation=3,
            state=SelfCaptureSessionState.RUNNING,
            provider_id="soniox",
            reason=SelfCaptureFailureReason.SESSION_FAILED,
            detail="RuntimeError token=secret",
            recognition_reason="soniox_write_failed: transcript=secret",
            utterance_id=utterance_id,
            epoch=epoch,
            turn=turn,
            activation_generation=3,
            desired_active_before=True,
            desired_active_after=False,
            action="deactivate",
            target_state=SelfCaptureSessionState.FAULTED,
        )
    )
    assert len(basic) == 1
    assert diagnostic == []
    assert "secret" not in basic[0]
    fields = dict(token.split("=", 1) for token in basic[0].split()[2:])
    assert fields["recognition_reason"] == "soniox_write_failed"
    assert fields["utterance_id"] == str(utterance_id)
    assert fields["epoch"] == epoch
    assert fields["turn"] == turn
    assert fields["activation_generation"] == "3"
    assert fields["desired_active_before"] == "true"
    assert fields["desired_active_after"] == "false"
    assert fields["action"] == "deactivate"
    assert fields["target_state"] == "faulted"


def test_self_capture_failure_does_not_persist_external_fields() -> None:
    basic: list[str] = []
    adapter = CaptureDiagnosticsAdapter(
        debug_allowed=lambda: False,
        capture_fault_profile=lambda: "none",
        log_diagnostic=lambda _message: None,
        log_basic=basic.append,
    )
    adapter.self_capture(
        SelfCaptureDiagnostic(
            event=SelfCaptureDiagnosticEvent.FAILURE,
            generation=1,
            state=SelfCaptureSessionState.RUNNING,
            provider_id="soniox response=SECRET",
            reason=SelfCaptureFailureReason.SESSION_FAILED,
            detail="payload=SECRET",
            recognition_reason="provider_error: transcript=SECRET",
            epoch="epoch response=SECRET",
            turn="turn response=SECRET",
            action="deactivate response=SECRET",
        )
    )
    assert len(basic) == 1
    assert "SECRET" not in basic[0]
    fields = dict(token.split("=", 1) for token in basic[0].split()[2:])
    assert fields["provider"] == "unclassified"
    assert fields["recognition_reason"] == "unclassified"
    assert fields["epoch"] == "unclassified"
    assert fields["turn"] == "unclassified"
    assert fields["action"] == "none"
