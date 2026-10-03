import argparse
import asyncio
import json
import os
import pathlib
import subprocess
import tempfile

import websockets

repo = pathlib.Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser(
    description="Test native subtitles against a separate simulated Monado headset; never changes your active VR runtime."
)
parser.add_argument(
    "--binary", type=pathlib.Path, default=repo / "target/debug/PuriPulyHeartOverlay"
)
parser.add_argument("--output", type=pathlib.Path, default=repo / "diagnostics/linux-overlay")
args = parser.parse_args()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=True)


async def run():
    with tempfile.TemporaryDirectory(prefix="puripuly-xr-") as directory:
        env = dict(
            os.environ,
            XDG_RUNTIME_DIR=directory,
            XR_RUNTIME_JSON="/usr/share/openxr/1/openxr_monado.json",
            SIMULATED_ENABLE="1",
            XRT_COMPOSITOR_NULL="1",
            XRT_NO_STDIN="1",
            STEAMVR_LH_ENABLE="0",
            XRT_DEBUG_GUI="0",
        )
        env.pop("LISTEN_FDS", None)
        env.pop("LISTEN_PID", None)
        service_log = (out / "monado-simulated.log").open("w")
        service = subprocess.Popen(
            ["/usr/bin/monado-service"],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=service_log,
            stderr=subprocess.STDOUT,
        )
        child = None
        seen = []
        try:
            for _ in range(100):
                if service.poll() is not None:
                    raise RuntimeError("Simulated Monado exited; inspect log")
                if list(pathlib.Path(directory).glob("*ipc*")):
                    break
                await asyncio.sleep(0.05)
            else:
                raise RuntimeError("Simulated Monado socket timeout")

            async def bridge(ws):
                auth = json.loads(await ws.recv())
                assert auth["type"] == "auth"
                block = {
                    "id": "smoke-self",
                    "occupant_key": "smoke-self",
                    "appearance_seq": 1,
                    "channel": "self",
                    "block_variant": "finalized",
                    "primary_text": "Linux VR subtitles · 日本語 · 한국어",
                    "secondary_text": "Native OpenXR and Vulkan",
                    "secondary_enabled": True,
                }
                await ws.send(
                    json.dumps({"type": "snapshot", "payload": {"revision": 1, "blocks": [block]}})
                )

                async def updates():
                    await asyncio.sleep(2)
                    await ws.send(
                        json.dumps(
                            {
                                "type": "snapshot",
                                "payload": {
                                    "revision": 2,
                                    "calibration": {"anchor": "spatial_locked", "offset_y": -0.25},
                                    "blocks": [
                                        dict(
                                            block,
                                            primary_text="Spatial calibration and text update",
                                        )
                                    ],
                                },
                            }
                        )
                    )
                    await asyncio.sleep(2)
                    await ws.send(
                        json.dumps({"type": "snapshot", "payload": {"revision": 3, "blocks": []}})
                    )
                    await asyncio.sleep(0.75)
                    await ws.send(
                        json.dumps(
                            {"type": "snapshot", "payload": {"revision": 4, "blocks": [block]}}
                        )
                    )
                    await asyncio.sleep(1)
                    await ws.send(json.dumps({"type": "shutdown"}))

                updater = asyncio.create_task(updates())
                try:
                    async for message in ws:
                        event = json.loads(message)
                        seen.append(event)
                finally:
                    updater.cancel()

            async with websockets.serve(bridge, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
                manifest = pathlib.Path(directory) / "manifest.json"
                manifest.write_text(
                    json.dumps(
                        {
                            "contract_version": 15,
                            "app_version": "2.7.0",
                            "overlay_instance_id": "linux-integration-test",
                            "bridge_url": f"ws://127.0.0.1:{port}",
                            "session_token": "isolated-test",
                            "parent_pid": os.getpid(),
                            "startup_deadline_ms": 10000,
                            "log_dir": str(out),
                            "log_level": "INFO",
                            "locale": "en",
                        }
                    )
                )
                child = await asyncio.create_subprocess_exec(
                    str(args.binary.resolve()),
                    "--config",
                    str(manifest),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                output, _ = await asyncio.wait_for(child.communicate(), 20)
                (out / "overlay-smoke.log").write_bytes(output)
                result = {"exit_code": child.returncode, "bridge_events": seen}
                (out / "result.json").write_text(json.dumps(result, indent=2))
                assert child.returncode == 0, output.decode(errors="replace")
                assert any(e.get("type") == "overlay_ready" for e in seen)
                assert '"type":"shutdown_complete"' in output.decode()
                status = [e for e in seen if e.get("type") == "owner_status"]
                for revision in (1, 2, 4):
                    assert any(
                        e.get("latest_handoff_revision") == revision
                        and e.get("observed_runtime_visible") is True
                        for e in status
                    ), (revision, status)
                assert any(
                    e.get("latest_applied_revision") == 3
                    and e.get("classification") == "no_drawable_content"
                    for e in status
                )
                print(
                    json.dumps(
                        {
                            "passed": True,
                            "exit_code": child.returncode,
                            "rendered_revisions": [1, 2, 4],
                            "idle_revision": 3,
                            "runtime": "isolated Monado simulated headset",
                            "output": str(out),
                        }
                    )
                )
        finally:
            if child and child.returncode is None:
                child.kill()
                await child.wait()
            service.terminate()
            try:
                service.wait(timeout=3)
            except subprocess.TimeoutExpired:
                service.kill()
                service.wait()
            service_log.close()


asyncio.run(run())
