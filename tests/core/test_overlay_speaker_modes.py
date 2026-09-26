from uuid import uuid4

import pytest

from puripuly_heart.core.clock import FakeClock
from puripuly_heart.core.overlay.presenter import OverlayPresenter
from puripuly_heart.core.overlay.sink import OverlayEventAdapter
from puripuly_heart.domain.models import (
    SpeakerAssignment,
    SpeakerAttribution,
    SpeakerKey,
    Transcript,
)
from puripuly_heart.ui.overlay_calibration import OverlayCalibration


def _assignment(scope: str, speaker: str | None, order: int, index: int | None):
    attribution = SpeakerAttribution(
        "identified" if speaker is not None else "missing",
        SpeakerKey("soniox", scope, speaker) if speaker is not None else None,
        "soniox",
        scope,
    )
    return SpeakerAssignment(attribution, (1, order, 0), index)


def _peer_event(adapter, turn_id, text, assignment):
    return adapter.translation_final(
        utterance_id=turn_id,
        channel="peer",
        text=text,
        source_text=text,
        source_language="en",
        target_language="ko",
        applied_context_mode="integrated",
        speaker_assignment=assignment,
    )


@pytest.mark.asyncio
async def test_first_readable_color_is_immutable_across_updates_self_and_replay() -> None:
    clock = FakeClock(_now=20.0)
    adapter = OverlayEventAdapter(clock=clock)
    presenter = OverlayPresenter(calibration=OverlayCalibration(), clock=clock)
    turn, self_turn = uuid4(), uuid4()
    await presenter.emit(_peer_event(adapter, turn, "first", _assignment("scope", None, 1, None)))
    visible_since = presenter._entries[("peer", turn)].visible_since
    assert presenter.snapshot().blocks[0].speaker_style == "gray"
    await presenter.emit(_peer_event(adapter, turn, "revised", _assignment("scope", "A", 1, 0)))
    await presenter.emit(
        adapter.transcript_final(
            Transcript(self_turn, "self", True, channel="self"),
            source_language="en",
            target_language="ko",
        )
    )
    blocks = {block.id: block for block in presenter.snapshot().blocks}
    assert blocks[f"peer:{turn}"].speaker_style == "gray"
    assert blocks[f"self:{self_turn}"].speaker_style is None
    assert presenter._entries[("peer", turn)].visible_since == visible_since
    assert presenter.snapshot().to_dict()["blocks"][0]["speaker_style"] == "gray"
    await presenter.close()


@pytest.mark.asyncio
async def test_scope_handoff_keeps_old_color_and_grays_new_until_old_leaves() -> None:
    clock = FakeClock(_now=30.0)
    adapter = OverlayEventAdapter(clock=clock)
    presenter = OverlayPresenter(calibration=OverlayCalibration(), clock=clock)
    old, new, later = uuid4(), uuid4(), uuid4()
    await presenter.emit(_peer_event(adapter, old, "old readable", _assignment("old", "A", 1, 0)))
    await presenter.emit(_peer_event(adapter, new, "new readable", _assignment("new", "A", 2, 0)))
    blocks = {block.id: block for block in presenter.snapshot().blocks}
    assert blocks[f"peer:{old}"].speaker_style == "gold"
    assert blocks[f"peer:{new}"].speaker_style == "gray"
    clock.advance(1)
    await presenter.emit(_peer_event(adapter, later, "new later", _assignment("new", "A", 3, 0)))
    assert presenter.snapshot().blocks[-1].speaker_style == "gold"
    assert presenter._entries[("peer", new)].speaker_style == "gray"
    await presenter.close()


@pytest.mark.asyncio
async def test_late_old_scope_result_cannot_reclaim_new_palette() -> None:
    clock = FakeClock(_now=40.0)
    adapter = OverlayEventAdapter(clock=clock)
    presenter = OverlayPresenter(calibration=OverlayCalibration(), clock=clock)
    new, old = uuid4(), uuid4()
    await presenter.emit(_peer_event(adapter, new, "new", _assignment("new", "A", 3, 0)))
    await presenter.emit(_peer_event(adapter, old, "late old", _assignment("old", "A", 2, 0)))
    blocks = {block.id: block for block in presenter.snapshot().blocks}
    assert blocks[f"peer:{new}"].speaker_style == "gold"
    assert blocks[f"peer:{old}"].speaker_style == "gray"
    await presenter.close()
