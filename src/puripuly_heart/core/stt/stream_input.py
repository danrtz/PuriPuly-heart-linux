from __future__ import annotations

from dataclasses import dataclass

from puripuly_heart.core.audio.format import AudioCaptureSpan


@dataclass(frozen=True, slots=True)
class STTStreamWrite:
    capture_epoch: int
    source_start: int
    source_end: int
    sample_count: int


class STTStreamInputMap:
    def __init__(self) -> None:
        self.sent_samples = 0
        self.sent_bytes = 0
        self._capture_epoch: int | None = None
        self._source_start: int | None = None
        self._source_frontier: int | None = None

    def prepare(
        self,
        pcm: bytes,
        ranges: tuple[AudioCaptureSpan, ...],
    ) -> tuple[bytes, STTStreamWrite | None]:
        if len(pcm) % 2 or sum(span.normalized_sample_count for span in ranges) * 2 != len(pcm):
            raise ValueError("stream PCM requires exact real source coverage")
        epoch = self._capture_epoch
        frontier = self._source_frontier
        first = None
        cursor = 0
        pieces: list[bytes] = []
        for span in ranges:
            start, end = span.normalized_start_sample, span.normalized_end_sample
            if start is None or end is None:
                raise ValueError("stream source must be normalized")
            if epoch is not None and span.capture_epoch != epoch:
                raise ValueError("stream capture epoch changed without retirement")
            epoch = span.capture_epoch
            if frontier is not None and start > frontier:
                raise ValueError("stream source discontinuity")
            left = start if frontier is None else max(start, frontier)
            if left < end:
                if first is None:
                    first = left
                pieces.append(pcm[(cursor + left - start) * 2 : (cursor + end - start) * 2])
                frontier = end
            cursor += end - start
        if first is None or epoch is None or frontier is None:
            return b"", None
        payload = pieces[0] if len(pieces) == 1 else b"".join(pieces)
        return payload, STTStreamWrite(epoch, first, frontier, len(payload) // 2)

    def commit(self, write: STTStreamWrite) -> None:
        if self._capture_epoch is None:
            self._capture_epoch = write.capture_epoch
            self._source_start = write.source_start
        if write.capture_epoch != self._capture_epoch:
            raise ValueError("stream capture epoch changed during write")
        self._source_frontier = write.source_end
        self.sent_samples += write.sample_count
        self.sent_bytes += write.sample_count * 2

    def covers(self, ranges: tuple[AudioCaptureSpan, ...]) -> bool:
        if not ranges or self._source_start is None or self._source_frontier is None:
            return False
        return all(
            span.capture_epoch == self._capture_epoch
            and span.normalized_start_sample is not None
            and span.normalized_end_sample is not None
            and self._source_start <= span.normalized_start_sample
            and span.normalized_end_sample <= self._source_frontier
            for span in ranges
        )
