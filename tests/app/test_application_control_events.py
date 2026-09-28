from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from puripuly_heart.app.services.application_control_events import ControlEvents
from puripuly_heart.domain.events import UIEvent, UIEventType
from puripuly_heart.domain.models import OSCMessage, Transcript, Translation


@pytest.mark.parametrize(
    ("event_count", "after", "expected_gap"),
    ((256, 0, None), (257, 0, 1), (257, 1, None)),
)
async def test_replay_window_and_gap_boundary(event_count, after, expected_gap):
    events = ControlEvents()
    for index in range(event_count):
        events.publish({"topic": "state", "index": index})

    stream = events.subscribe(
        topics=[],
        channel=None,
        include_transcripts=False,
        include_translations=False,
        after=after,
    )
    items = [await anext(stream) for _ in range(event_count - after + (expected_gap is not None))]
    await stream.aclose()

    gaps = [item for item in items if item["topic"] == "gap"]
    assert len(gaps) == (expected_gap is not None)
    if expected_gap is not None:
        assert gaps == [
            {
                "sequence": expected_gap,
                "topic": "gap",
                "after": after,
                "snapshot_required": True,
            }
        ]
    replayed = [item for item in items if item["topic"] != "gap"]
    oldest = max(1, event_count - 255)
    assert [item["sequence"] for item in replayed] == list(range(max(after + 1, oldest), event_count + 1))
    assert [item["index"] for item in replayed] == list(range(max(after, oldest - 1), event_count))


@pytest.mark.asyncio
async def test_slow_subscriber_gets_gap_then_retained_events_in_order():
    events = ControlEvents()
    stream = events.subscribe(
        topics=["capture"],
        channel=None,
        include_transcripts=False,
        include_translations=False,
        after=0,
    )
    first = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)

    for index in range(300):
        events.publish({"topic": "capture", "index": index})

    gap = await asyncio.wait_for(first, timeout=1)
    replayed = [await anext(stream) for _ in range(256)]
    await stream.aclose()

    assert gap == {
        "sequence": 44,
        "topic": "gap",
        "after": 0,
        "snapshot_required": True,
    }
    assert [item["sequence"] for item in replayed] == list(range(45, 301))
    assert [item["index"] for item in replayed] == list(range(44, 300))
    assert events.subscribers == set()


@pytest.mark.asyncio
async def test_filters_content_opt_ins_and_osc_privacy_are_independent():
    events = ControlEvents()
    transcript_id = UUID("00000000-0000-0000-0000-000000000001")
    peer_id = UUID("00000000-0000-0000-0000-000000000002")
    translation_id = UUID("00000000-0000-0000-0000-000000000003")
    osc_id = UUID("00000000-0000-0000-0000-000000000004")
    events.publish_ui(
        UIEvent(
            UIEventType.TRANSCRIPT_FINAL,
            payload=Transcript(transcript_id, "transcript private", True, channel="self"),
            source="capture",
        )
    )
    events.publish_ui(
        UIEvent(
            UIEventType.TRANSCRIPT_FINAL,
            payload=Transcript(peer_id, "peer private", True, channel="peer"),
            source="capture",
        )
    )
    events.publish({"topic": "settings", "channel": "self"})
    events.publish_ui(
        UIEvent(
            UIEventType.TRANSLATION_DONE,
            payload=Translation(translation_id, "translation private", channel="self"),
            source="translation",
        )
    )
    events.publish_ui(
        UIEvent(
            UIEventType.OSC_SENT,
            payload=OSCMessage(osc_id, "chatbox private", 1.0),
            source="osc",
        )
    )

    transcript_stream = events.subscribe(
        topics=["transcript"],
        channel="self",
        include_transcripts=True,
        include_translations=False,
        after=0,
    )
    transcript = await anext(transcript_stream)
    await transcript_stream.aclose()
    assert transcript["sequence"] == 1
    assert transcript["text"] == "transcript private"

    translation_stream = events.subscribe(
        topics=["translation"],
        channel="self",
        include_transcripts=False,
        include_translations=True,
        after=0,
    )
    translation = await anext(translation_stream)
    await translation_stream.aclose()
    assert translation["sequence"] == 4
    assert translation["text"] == "translation private"

    projected_stream = events.subscribe(
        topics=["transcript", "translation", "osc_sent"],
        channel="self",
        include_transcripts=True,
        include_translations=False,
        after=0,
    )
    projected = [await anext(projected_stream) for _ in range(3)]
    await projected_stream.aclose()

    assert [item["sequence"] for item in projected] == [1, 4, 5]
    assert projected[0]["text"] == "transcript private"
    assert "text" not in projected[1]
    assert "text" not in projected[2]
    assert "chatbox private" not in repr(projected)

    private_stream = events.subscribe(
        topics=["transcript", "translation"],
        channel="self",
        include_transcripts=False,
        include_translations=False,
        after=0,
    )
    private = [await anext(private_stream) for _ in range(2)]
    await private_stream.aclose()
    assert [item["sequence"] for item in private] == [1, 4]
    assert all("text" not in item for item in private)


@pytest.mark.asyncio
async def test_subscriber_projection_is_copy_isolated_and_unsubscribe_cleans_up():
    events = ControlEvents()
    published = {"topic": "state", "channel": "self"}
    events.publish(published)
    published["topic"] = "changed"

    first_stream = events.subscribe(
        topics=[], channel=None, include_transcripts=False, include_translations=False, after=0
    )
    first_task = asyncio.create_task(anext(first_stream))
    await asyncio.sleep(0)
    first = await first_task
    assert len(events.subscribers) == 1
    first["topic"] = "changed by subscriber"
    await first_stream.aclose()
    assert events.subscribers == set()

    second_stream = events.subscribe(
        topics=[], channel=None, include_transcripts=False, include_translations=False, after=0
    )
    second = await anext(second_stream)
    await second_stream.aclose()

    assert second == {"sequence": 1, "topic": "state", "channel": "self"}
    assert events.history[0]["topic"] == "state"
