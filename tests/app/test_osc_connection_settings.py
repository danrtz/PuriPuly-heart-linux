from dataclasses import replace

import pytest

from puripuly_heart.app.ports.settings_view import OscConnectionSettingsIntent
from puripuly_heart.app.services.settings.settings_application import (
    materialize_immediate_settings_intent,
)
from puripuly_heart.config.settings_vnext.schema import AppSettingsVNext, OscIntent


@pytest.mark.parametrize(
    ("previous", "requested", "expected"),
    [(9000, 45123, 45123), (45123, 45124, 45124), (45123, 9000, 9000), (45123, None, 45123)],
)
def test_osc_connection_change_keeps_legacy_and_effective_destination_in_sync(
    previous: int, requested: int | None, expected: int
) -> None:
    settings = AppSettingsVNext()
    settings = replace(
        settings,
        intent=replace(settings.intent, osc=OscIntent(port=previous, send_port=previous)),
    )
    updated = materialize_immediate_settings_intent(
        settings, OscConnectionSettingsIntent("manual", requested, 45125)
    )
    assert updated.intent.osc.port == updated.intent.osc.send_port == expected
    assert updated.intent.osc.receive_port == 45125
    assert settings.intent.osc.send_port == previous


@pytest.mark.asyncio
async def test_off_blocks_all_udp_and_manual_or_automatic_reenable_restores_chatbox() -> None:
    import socket
    from uuid import uuid4

    from puripuly_heart.app.ports.oscquery import OscQueryServiceInfo
    from puripuly_heart.core.clock import SystemClock
    from puripuly_heart.core.osc.chatbox_paginator import ChatboxPaginator
    from puripuly_heart.core.osc.udp_sender import VrchatOscUdpSender
    from puripuly_heart.core.runtime.output import OutputRuntime
    from tests.app.test_osc_control_runtime import FakeReceiverOwner, FakeService, _integration

    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server.settimeout(0.05)
    port = server.getsockname()[1]
    sender = VrchatOscUdpSender(port=port)
    clock = SystemClock()
    queue = ChatboxPaginator(sender=sender, clock=clock)
    output = OutputRuntime(chatbox=queue, clock=clock)
    service = FakeService(
        OscQueryServiceInfo(
            service_id="VRChat-test", host="127.0.0.1", osc_send_port=port, is_vrchat=True
        )
    )
    owner = _integration(AppSettingsVNext(), FakeReceiverOwner(), sender, service)

    async def publish(text: str):
        return await output.publish_chatbox(
            publication_id=uuid4(),
            channel="self",
            transcript_text=text,
            translation_text=None,
            include_source=False,
        )

    try:
        await output.start()
        for mode in ("manual", "automatic"):
            await owner.configure_connection(mode="off", send_port=port, receive_port=45125)
            result = await publish("private manual text while off")
            assert result.decision.reason == "destination_disabled"
            sender.send_typing(True)
            sender.send_message("/avatar/parameters/test", True)
            with pytest.raises(socket.timeout):
                server.recvfrom(65535)

            await owner.configure_connection(mode=mode, send_port=port, receive_port=45125)
            await owner.wait_automatic_query_start()
            server.setblocking(False)
            while True:
                try:
                    server.recvfrom(65535)
                except BlockingIOError:
                    break
            server.settimeout(0.05)
            result = await publish("こんにちは")
            assert result.decision.decision == "published"
            packet, _ = server.recvfrom(65535)
            assert packet.startswith(b"/chatbox/input\0")
            assert "こんにちは".encode() in packet
            await publish("Long caption " * 50)
            server.recvfrom(65535)
            await owner.configure_connection(mode="off", send_port=port, receive_port=45125)
            assert not queue._pending_pages
            assert not queue._pending_messages
    finally:
        await owner.close()
        await output.close()
        sender.close()
        server.close()


@pytest.mark.asyncio
async def test_retarget_suspends_inflight_text_until_new_destination_is_ready() -> None:
    import asyncio
    import socket

    from puripuly_heart.core.osc.udp_sender import VrchatOscUdpSender
    from tests.app.test_osc_control_runtime import FakeReceiverOwner, FakeService, _integration

    class DelayedReceiver(FakeReceiverOwner):
        def __init__(self) -> None:
            super().__init__()
            self.block = False
            self.entered = asyncio.Event()
            self.resume = asyncio.Event()

        async def configure_control(self, **kwargs: object) -> None:
            await super().configure_control(**kwargs)
            if self.block and kwargs["active"]:
                self.entered.set()
                await self.resume.wait()

    previous = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    following = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for server in (previous, following):
        server.bind(("127.0.0.1", 0))
        server.settimeout(0.05)
    old_port, new_port = previous.getsockname()[1], following.getsockname()[1]
    sender = VrchatOscUdpSender(port=old_port)
    receiver = DelayedReceiver()
    owner = _integration(AppSettingsVNext(), receiver, sender, FakeService(None))

    def drain(server: socket.socket) -> None:
        server.setblocking(False)
        while True:
            try:
                server.recvfrom(65535)
            except BlockingIOError:
                break
        server.settimeout(0.05)

    transition = None
    try:
        await owner.configure_connection(mode="manual", send_port=old_port, receive_port=45125)
        drain(previous)
        receiver.block = True
        transition = asyncio.create_task(
            owner.configure_connection(mode="manual", send_port=new_port, receive_port=45125)
        )
        await asyncio.wait_for(receiver.entered.wait(), 1)
        sender.send_chatbox("Do not send this in-flight caption to the old destination")
        for server in (previous, following):
            with pytest.raises(socket.timeout):
                server.recvfrom(65535)
        receiver.resume.set()
        await transition
        drain(following)
        sender.send_chatbox("New destination")
        packet, _ = following.recvfrom(65535)
        assert packet.startswith(b"/chatbox/input\0")
        assert b"New destination" in packet
        with pytest.raises(socket.timeout):
            previous.recvfrom(65535)
    finally:
        receiver.resume.set()
        if transition is not None:
            await transition
        await owner.close()
        sender.close()
        previous.close()
        following.close()
