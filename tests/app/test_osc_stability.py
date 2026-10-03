from __future__ import annotations

import asyncio
import socket
from uuid import uuid4

import pytest

from puripuly_heart.app.ports.oscquery import OscQueryServiceInfo
from puripuly_heart.app.services.vrc_mic_sync import VrcMicSyncOwner
from puripuly_heart.config.settings_vnext.schema import AppSettingsVNext
from puripuly_heart.core.clock import FakeClock
from puripuly_heart.core.osc.chatbox_paginator import ChatboxPaginator
from puripuly_heart.core.osc.receiver import VrcMicState, VrcOscReceiver
from puripuly_heart.core.osc.udp_sender import VrchatOscUdpSender
from puripuly_heart.core.runtime.output import OutputRuntime
from tests.app.test_osc_control_runtime import (
    DelayedDiscoveryService,
    FakeReceiverOwner,
    FakeSender,
    FakeService,
    _integration,
)


def _socket() -> socket.socket:
    endpoint = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    endpoint.bind(("127.0.0.1", 0))
    endpoint.setblocking(False)
    return endpoint


def _packets(endpoint: socket.socket) -> list[bytes]:
    messages = []
    while True:
        try:
            messages.append(endpoint.recvfrom(65535)[0])
        except BlockingIOError:
            return messages


def _receiver(errors: list[str]) -> VrcMicSyncOwner:
    state = VrcMicState()
    return VrcMicSyncOwner(
        state_provider=lambda: state,
        gate_provider=lambda: None,
        receiver_factory=VrcOscReceiver,
        diagnostics_sink=lambda *_args: None,
        error_sink=errors.append,
        host="127.0.0.1",
        port=0,
    )


@pytest.mark.asyncio
async def test_manual_receiver_recovers_when_contended_port_becomes_free() -> None:
    destination, occupied = _socket(), _socket()
    destination_port = destination.getsockname()[1]
    receiver_port = occupied.getsockname()[1]
    sender = VrchatOscUdpSender(port=destination_port)
    errors: list[str] = []
    receiver = _receiver(errors)
    owner = _integration(AppSettingsVNext(), receiver, sender, FakeService(None))
    try:
        await owner.configure_connection(
            mode="manual", send_port=destination_port, receive_port=receiver_port
        )
        assert errors
        assert owner.output_snapshot()["local_availability"] == "receiver_unavailable"
        occupied.close()
        await owner.configure_connection(
            mode="manual", send_port=destination_port, receive_port=receiver_port
        )
        assert owner.output_snapshot()["local_availability"] == "available"
        assert receiver.effective_port == receiver_port
    finally:
        occupied.close()
        await owner.close()
        sender.close()
        destination.close()


@pytest.mark.asyncio
async def test_close_cancels_inflight_automatic_discovery() -> None:
    service = DelayedDiscoveryService(None)
    service.block_discovery = True
    owner = _integration(AppSettingsVNext(), FakeReceiverOwner(), FakeSender(), service)
    try:
        await owner.configure_connection(mode="automatic", send_port=45101, receive_port=45102)
        await asyncio.wait_for(service.discovery_started.wait(), 1)
        await asyncio.wait_for(owner.close(), 0.5)
        assert service.stopped == 1
        assert owner.query_runtime.started is False
    finally:
        service.discovery_gate.set()
        await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["off", "manual"])
async def test_inflight_discovery_cannot_restore_a_retired_destination(mode: str) -> None:
    previous, following = _socket(), _socket()
    old_port, new_port = previous.getsockname()[1], following.getsockname()[1]
    sender = VrchatOscUdpSender(port=old_port, enabled=False)
    service = DelayedDiscoveryService(
        OscQueryServiceInfo(
            service_id="VRChat-retired-test",
            host="127.0.0.1",
            osc_send_port=old_port,
            is_vrchat=True,
        )
    )
    service.block_discovery = True
    owner = _integration(AppSettingsVNext(), FakeReceiverOwner(), sender, service)
    try:
        await owner.configure_connection(mode="automatic", send_port=old_port, receive_port=45102)
        await asyncio.wait_for(service.discovery_started.wait(), 1)
        await owner.configure_connection(mode=mode, send_port=new_port, receive_port=45102)
        service.discovery_gate.set()
        await asyncio.sleep(0)
        _packets(following)
        sender.send_chatbox("after transition")
        assert not _packets(previous)
        packets = _packets(following)
        if mode == "off":
            assert not sender.enabled
            assert not packets
        else:
            assert sender.enabled
            assert len(packets) == 1
            assert b"after transition" in packets[0]
    finally:
        service.discovery_gate.set()
        await owner.close()
        sender.close()
        previous.close()
        following.close()


@pytest.mark.asyncio
async def test_rapid_mode_switches_drop_stale_pages_and_never_send_peer_chatbox() -> None:
    destination, reserve = _socket(), _socket()
    destination_port, receiver_port = destination.getsockname()[1], reserve.getsockname()[1]
    reserve.close()
    sender = VrchatOscUdpSender(port=destination_port, enabled=False)
    clock = FakeClock(_now=1.0)
    queue = ChatboxPaginator(sender=sender, clock=clock)
    output = OutputRuntime(chatbox=queue, clock=clock)
    receiver = _receiver([])
    service = FakeService(
        OscQueryServiceInfo(
            service_id="VRChat-isolated-test",
            host="127.0.0.1",
            osc_send_port=destination_port,
            is_vrchat=True,
        )
    )
    owner = _integration(AppSettingsVNext(), receiver, sender, service)

    async def publish(text: str, channel: str = "self"):
        return await output.publish_chatbox(
            publication_id=uuid4(),
            channel=channel,
            transcript_text=text,
            translation_text=None,
            include_source=False,
        )

    try:
        await output.start()
        for iteration in range(20):
            mode = "manual" if iteration % 2 else "automatic"
            await owner.configure_connection(
                mode=mode, send_port=destination_port, receive_port=receiver_port
            )
            await owner.wait_automatic_query_start()
            assert sender.port == destination_port
            assert receiver.receiver is not None
            _packets(destination)
            peer = await publish("private peer subtitle", "peer")
            assert peer.decision.decision == "denied"
            assert not _packets(destination)
            await publish("old caption " * 60)
            assert any(packet.startswith(b"/chatbox/input\0") for packet in _packets(destination))
            await owner.configure_connection(
                mode="off", send_port=destination_port, receive_port=receiver_port
            )
            await publish("private self subtitle")
            await publish("private peer subtitle", "peer")
            clock.advance(60)
            queue.process_due()
            assert not _packets(destination)
            assert not queue._pending_pages and not queue._pending_messages
            await owner.configure_connection(
                mode="manual", send_port=destination_port, receive_port=receiver_port
            )
            _packets(destination)
            queue.process_due()
            assert not _packets(destination)
            await publish(f"fresh caption {iteration}")
            packets = _packets(destination)
            assert len(packets) == 1
            assert f"fresh caption {iteration}".encode() in packets[0]
    finally:
        await owner.close()
        await output.close()
        sender.close()
        destination.close()
