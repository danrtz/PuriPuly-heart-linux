import json

from puripuly_heart.core.clock import FakeClock
from puripuly_heart.core.overlay.bridge_mailbox import OverlayBridgeMailbox
from puripuly_heart.core.overlay.protocol import (
    OverlayPresentationBlock,
    OverlayPresentationSnapshot,
)


def _block(block_id: str) -> OverlayPresentationBlock:
    return OverlayPresentationBlock(
        id=block_id,
        occupant_key=block_id,
        appearance_seq=1,
        channel="peer",
        block_variant="finalized",
        primary_text=block_id,
        secondary_text="",
        secondary_enabled=True,
        speaker_style="gray",
    )


def _mailbox(clock: FakeClock) -> OverlayBridgeMailbox:
    return OverlayBridgeMailbox(
        initial_snapshot=OverlayPresentationSnapshot(),
        clock=clock,
        scene_byte_limit=1 << 20,
        control_byte_limit=1 << 16,
        control_slot_limit=8,
        delivery_receipt_limit=8,
    )


def test_divider_is_replayed_while_both_blocks_are_current_and_dropped_after_expiry() -> None:
    clock = FakeClock(_now=10.0)
    mailbox = _mailbox(clock)
    snapshot = OverlayPresentationSnapshot(
        revision=1,
        blocks=[_block("peer:e"), _block("peer:f")],
        speaker_divider=True,
    )
    envelope = mailbox.make_scene(snapshot, {"peer:e": 12.0, "peer:f": None})

    current = json.loads(mailbox.revalidated_scene_message(envelope))["payload"]
    assert current["speaker_divider"] is True
    assert [block["id"] for block in current["blocks"]] == ["peer:e", "peer:f"]

    clock.advance(5.0)
    expired = json.loads(mailbox.revalidated_scene_message(envelope))["payload"]
    assert [block["id"] for block in expired["blocks"]] == ["peer:f"]
    assert "speaker_divider" not in expired
