from dataclasses import replace

import pytest

from puripuly_heart.app.adapters.linux_process_priority import LinuxProcessPriority
from puripuly_heart.app.ports.settings_view import HighPrioritySettingsIntent
from puripuly_heart.app.services.settings.settings_application import (
    materialize_immediate_settings_intent,
    settings_view_surface_snapshots,
)
from puripuly_heart.config.settings_vnext.schema import AppSettingsVNext, PerformanceIntent
from puripuly_heart.config.settings_vnext.serialization import from_dict, to_dict


def test_priority_persists_without_changing_models_or_audio():
    initial = AppSettingsVNext()
    changed = materialize_immediate_settings_intent(initial, HighPrioritySettingsIntent(True))
    restored = from_dict(to_dict(changed))
    assert restored.intent.performance.high_priority
    assert replace(restored.intent, performance=initial.intent.performance) == initial.intent
    assert settings_view_surface_snapshots(restored)[1].high_priority
    assert not materialize_immediate_settings_intent(
        restored, HighPrioritySettingsIntent(False)
    ).intent.performance.high_priority


@pytest.mark.parametrize("value", ["true", 1, None])
def test_priority_rejects_non_boolean_settings(value):
    with pytest.raises(ValueError):
        PerformanceIntent(high_priority=value)


@pytest.mark.asyncio
async def test_normal_mode_needs_no_systemd_session(monkeypatch):
    controller = LinuxProcessPriority()

    async def fail(*args):
        raise AssertionError("Normal mode should not contact systemd")

    monkeypatch.setattr(controller, "_run", fail)
    await controller.set_enabled(False)
    assert not controller.enabled and controller.unit is None


@pytest.mark.asyncio
async def test_denied_priority_is_reported_and_retryable(monkeypatch):
    controller = LinuxProcessPriority()

    async def denied(*args):
        raise RuntimeError("systemd session unavailable")

    monkeypatch.setattr(controller, "_run", denied)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="unavailable"):
            await controller.set_enabled(True)
        assert not controller.enabled and controller.unit is None
    await controller.set_enabled(False)
