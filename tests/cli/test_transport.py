from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import pytest

from puripuly_heart.app.services.application_control import UnknownOperationError
from puripuly_heart.cli.transport import (
    MAX_REQUEST_BYTES,
    ControlServer,
    ControlTransportError,
    follow,
    request,
)


@dataclass(frozen=True)
class _Record:
    port: int
    instance_id: str = "correct-instance"
    token: str = "local-secret-token"


class _Control:
    def __init__(self):
        self.calls = 0

    def capabilities(self):
        self.calls += 1
        return {"queries": ["app.status"]}

    async def query(self, name, arguments):
        self.calls += 1
        return {"status": "ready", "name": name}

    async def submit(self, name, arguments, *, request_id, expected_revision=None):
        self.calls += 1
        return {"instance_id": "correct-instance", "operation_id": request_id, "status": "accepted"}


async def _raw(port: int, message: bytes):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(message)
        await writer.drain()
        return json.loads(await reader.readline())
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_security_checks_precede_application_dispatch():
    control = _Control()
    server = ControlServer(control, instance_id="correct-instance", token="local-secret-token")
    port = await server.start()
    try:
        base = {
            "protocol": 1,
            "instance_id": "correct-instance",
            "token": "local-secret-token",
            "method": "capabilities",
            "arguments": {},
        }
        for change, code in [
            ({"protocol": 2}, "unsupported_protocol"),
            ({"instance_id": "previous-instance"}, "stale_instance"),
            ({"token": "incorrect-token"}, "unauthorized"),
            ({"method": "__dict__"}, "unknown_method"),
        ]:
            response = await _raw(port, json.dumps(base | change).encode() + b"\n")
            assert response["error"]["code"] == code
        response = await _raw(port, b"{" + b"a" * (MAX_REQUEST_BYTES + 1) + b"\n")
        assert response["error"]["code"] == "request_too_large"
        for arguments in (
            {"topics": ["transcript"], "include_transcripts": "true"},
            {"topics": ["operation"], "after": "0"},
            {"topics": ["operation"], "channel": "other"},
        ):
            response = await _raw(
                port,
                json.dumps(base | {"method": "subscribe", "arguments": arguments}).encode() + b"\n",
            )
            assert response["error"]["code"] == "malformed_request"
        assert control.calls == 0
        assert (await request(_Record(port), "capabilities"))["queries"] == ["app.status"]
        assert control.calls == 1
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_stale_endpoint_and_ingress_freeze_do_not_replay_mutation():
    control = _Control()
    server = ControlServer(control, instance_id="correct-instance", token="local-secret-token")
    port = await server.start()
    try:
        with pytest.raises(ControlTransportError, match="rediscover") as error:
            await request(
                _Record(port, instance_id="previous-instance"),
                "submit",
                {"name": "capture.set", "values": {"enabled": True}, "request_id": "once"},
            )
        assert error.value.code == "stale_instance"
        assert control.calls == 0
        server.freeze()
        with pytest.raises(ControlTransportError):
            await request(_Record(port), "query", {"name": "app.status"})
        assert control.calls == 0
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_client_timeout_does_not_cancel_accepted_server_execution():
    class SlowControl(_Control):
        def __init__(self):
            super().__init__()
            self.completed = asyncio.Event()

        async def submit(self, name, arguments, *, request_id, expected_revision=None):
            self.calls += 1
            await asyncio.sleep(0.15)
            self.completed.set()
            return {
                "instance_id": "correct-instance",
                "operation_id": request_id,
                "status": "accepted",
            }

    control = SlowControl()
    server = ControlServer(control, instance_id="correct-instance", token="local-secret-token")
    port = await server.start()
    try:
        with pytest.raises(ControlTransportError) as error:
            await request(
                _Record(port),
                "submit",
                {
                    "name": "capture.set",
                    "values": {"channel": "self", "enabled": False},
                    "request_id": "do-not-replay",
                },
                timeout=0.02,
            )
        assert error.value.code == "unknown_execution"
        await asyncio.wait_for(control.completed.wait(), 1)
        assert control.calls == 1
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_shutdown_waits_until_stop_receipt_is_consumed():
    class StopControl(_Control):
        def __init__(self):
            super().__init__()
            self.stop_requested = asyncio.Event()

        async def submit(self, name, arguments, *, request_id, expected_revision=None):
            self.stop_requested.set()
            return {
                "instance_id": "correct-instance",
                "operation_id": request_id,
                "status": "accepted",
            }

    control = StopControl()
    server = ControlServer(control, instance_id="correct-instance", token="local-secret-token")
    port = await server.start()

    async def shutdown():
        await control.stop_requested.wait()
        await server.wait_for_idle()
        await server.close()

    task = asyncio.create_task(shutdown())
    try:
        result = await request(
            _Record(port), "submit", {"name": "app.stop", "values": {}, "request_id": "stop-once"}
        )
        assert result["status"] == "accepted"
        await asyncio.wait_for(task, 1)
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_event_follow_reports_host_loss_instead_of_success():
    class EventControl(_Control):
        def subscribe(self, *, topics, channel, include_transcripts, include_translations, after):
            async def stream():
                yield {"topic": "operation", "sequence": 1, "status": "applied"}
                await asyncio.Event().wait()

            return stream()

    server = ControlServer(
        EventControl(), instance_id="correct-instance", token="local-secret-token"
    )
    port = await server.start()
    stream = follow(_Record(port), {"topics": ["operation"]})
    try:
        event = await anext(stream)
        assert event["status"] == "applied"
        closing = asyncio.create_task(server.close())
        with pytest.raises(ControlTransportError) as error:
            await asyncio.wait_for(anext(stream), 2)
        assert error.value.code == "connection_lost"
        await asyncio.wait_for(closing, 2)
    finally:
        await stream.aclose()
        await server.close()


@pytest.mark.asyncio
async def test_expired_operation_identity_has_specific_error_without_dispatch_details():
    class ExpiredControl(_Control):
        async def operation(self, operation_id):
            raise UnknownOperationError("private application detail")

    server = ControlServer(
        ExpiredControl(), instance_id="correct-instance", token="local-secret-token"
    )
    port = await server.start()
    try:
        with pytest.raises(ControlTransportError) as error:
            await request(_Record(port), "operation", {"operation_id": "prior-host-operation"})
        assert error.value.code == "unknown_or_expired_operation"
        assert "private application detail" not in str(error.value)
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_client_rejects_oversized_request_before_dispatch():
    control = _Control()
    server = ControlServer(control, instance_id="correct-instance", token="local-secret-token")
    port = await server.start()
    try:
        with pytest.raises(ControlTransportError) as error:
            await request(
                _Record(port),
                "submit",
                {
                    "name": "text.submit",
                    "values": {"text": "x" * MAX_REQUEST_BYTES},
                    "request_id": "oversized",
                },
            )
        assert error.value.code == "request_too_large"
        assert control.calls == 0
    finally:
        await server.close()
