from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import UUID

from puripuly_heart.core.messages import UserErrorReport, UserMessageRef
from puripuly_heart.domain.events import STTSessionState, UIEvent, UIEventType
from puripuly_heart.domain.models import OSCMessage, Transcript, Translation


@dataclass(slots=True)
class ControlEvents:
    """One consumer of the runtime queue; independent bounded subscriber projections."""

    history: deque[dict] = field(default_factory=lambda: deque(maxlen=256))
    subscribers: set[asyncio.Queue[int]] = field(default_factory=set)
    sequence: int = 0

    def publish(self, event: dict) -> None:
        self.sequence += 1
        entry = {"sequence": self.sequence, **event}
        self.history.append(entry)
        for subscriber in self.subscribers:
            if subscriber.empty():
                subscriber.put_nowait(self.sequence)

    def publish_ui(self, event: UIEvent) -> None:
        payload = event.payload
        kind = {
            UIEventType.TRANSCRIPT_PARTIAL: "transcript",
            UIEventType.TRANSCRIPT_FINAL: "transcript",
            UIEventType.TRANSLATION_DONE: "translation",
        }.get(event.type, event.type.value.lower())
        item: dict = {"topic": kind, "channel": event.channel, "source": event.source}
        if event.type == UIEventType.ERROR:
            message = payload.message if isinstance(payload, UserErrorReport) else payload
            item["error"] = {
                "code": message.key if isinstance(message, UserMessageRef) else "runtime_error"
            }
        elif event.type in {
            UIEventType.TRANSCRIPT_PARTIAL,
            UIEventType.TRANSCRIPT_FINAL,
            UIEventType.TRANSLATION_DONE,
        }:
            content = (
                isinstance(payload, Transcript)
                if event.type in {UIEventType.TRANSCRIPT_PARTIAL, UIEventType.TRANSCRIPT_FINAL}
                else isinstance(payload, Translation)
            )
            if content:
                item["text"] = payload.text
            utterance_id = payload.utterance_id if content else event.utterance_id
            item["utterance_id"] = str(utterance_id) if isinstance(utterance_id, UUID) else ""
        elif event.type == UIEventType.SESSION_STATE_CHANGED:
            if isinstance(payload, STTSessionState):
                item["state"] = payload.value
        elif event.type == UIEventType.OSC_SENT:
            utterance_id = event.utterance_id
            if utterance_id is None and isinstance(payload, OSCMessage):
                utterance_id = payload.utterance_id
            if isinstance(utterance_id, UUID):
                item["utterance_id"] = str(utterance_id)
        self.publish(item)

    async def subscribe(
        self,
        *,
        topics: list[str],
        channel: str | None,
        include_transcripts: bool,
        include_translations: bool,
        after: int | None,
    ) -> AsyncIterator[dict]:
        queue: asyncio.Queue[int] = asyncio.Queue(maxsize=32)
        self.subscribers.add(queue)
        cursor = self.sequence if after is None else after
        try:
            while True:
                oldest = self.history[0]["sequence"] if self.history else self.sequence + 1
                if cursor < oldest - 1:
                    yield {"sequence": oldest - 1, "topic": "gap", "after": cursor, "snapshot_required": True}
                    cursor = oldest - 1
                    continue
                if cursor < self.sequence:
                    pending = tuple(
                        self.history[sequence - oldest]
                        for sequence in range(cursor + 1, self.sequence + 1)
                    )
                    for entry in pending:
                        sequence = entry["sequence"]
                        if sequence <= cursor:
                            continue
                        cursor = sequence
                        if topics and entry.get("topic") not in topics:
                            continue
                        if channel is not None and entry.get("channel") not in (None, channel):
                            continue
                        projected = dict(entry)
                        if not ((entry.get("topic") == "transcript" and include_transcripts) or (entry.get("topic") == "translation" and include_translations)):
                            projected.pop("text", None)
                        yield projected
                await queue.get()
        finally:
            self.subscribers.discard(queue)


class ObservedEventQueue:
    """Observe dequeue without competing with the UI event bridge."""

    def __init__(self, queue: asyncio.Queue, events: ControlEvents) -> None:
        self._queue = queue
        self._events = events

    async def get(self) -> UIEvent:
        event = await self._queue.get()
        self._events.publish_ui(event)
        return event

    def task_done(self) -> None:
        self._queue.task_done()
