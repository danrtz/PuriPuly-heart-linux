"""Isolated real-host CLI failure and operation evidence for issue 193.

Run with ``uv run --no-sync python -m puripuly_heart.release_evidence.cli_control_failures
--report C:\\private\\cli-failures.json``. The report path must be outside the checkout.
No ambient capture, account mutation, terms acceptance, or secret echo is attempted.
An owned zero-PCM renderer uses VB Cable; a cancelled model install uses a
temporary LOCALAPPDATA so it cannot write the user's installed-model directory.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

from puripuly_heart.cli.transport import ControlTransportError, follow, request
from puripuly_heart.config.settings_vnext import compat
from puripuly_heart.config.settings_vnext.defaults import new_settings_for_first_run
from puripuly_heart.config.settings_vnext.schema import SecretsIntent, with_telemetry_enabled
from puripuly_heart.core.control_instance import discover

CREDENTIAL_PROBE = "invalid-controlled-probe-credential"


def restore_env(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


class SettingsReplacementLock:
    """Open our throwaway settings file without FILE_SHARE_DELETE on Windows."""

    def __init__(self, path: Path) -> None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel = kernel
        self.handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
        if self.handle in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        self.kernel.CloseHandle(self.handle)


async def cli(config: Path, *args: str, stdin: str | None = None, timeout: float = 35) -> dict:
    argv = [
        sys.executable,
        "-m",
        "puripuly_heart.main",
        "cli",
        "--config",
        str(config),
        "--timeout",
        str(timeout),
        *args,
    ]
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            process.communicate(stdin.encode() if stdin is not None else None), timeout + 10
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        return {"exit": -1, "status": "client_process_timeout", "command": list(args)}
    try:
        data = json.loads(out or err)
    except ValueError:
        data = {"error": {"code": "invalid_json"}}
    return {
        "command": list(args),
        "exit": process.returncode,
        "status": data.get("status"),
        "error_code": data.get("error", {}).get("code"),
        "operation_id": data.get("operation_id"),
        "instance_id": data.get("instance_id"),
        "revision": data.get("revision"),
        "action": data.get("action"),
        "transaction_status": data.get("transaction", {}).get("status"),
        "transaction_code": (data.get("transaction", {}).get("diagnostics") or {}).get("code"),
        "cancellation": data.get("cancellation"),
        "protected_input_exposed": (
            CREDENTIAL_PROBE.encode() in out + err if stdin is not None else None
        ),
        "soniox_secret_present": data.get("presence", {}).get("soniox_api_key"),
        "target_selected_is_default": (
            data.get("selected") == "device:" if "selected" in data else None
        ),
        "target_selected_is_unavailable_probe": (
            data.get("selected") == "unavailable-controlled-target-193"
            if "selected" in data
            else None
        ),
        "model_integrities": sorted(
            {
                item.get("integrity")
                for item in (data.get("state") or {}).get("models", [])
                if isinstance(item, dict) and isinstance(item.get("integrity"), str)
            }
        ),
        "model_cpu_required_available": (
            all(
                item.get("integrity") == "ready"
                for item in (data.get("state") or {}).get("models", [])
                if isinstance(item, dict)
                and item.get("model_id")
                in (data.get("state") or {}).get("required_cpu_model_ids", [])
            )
            if (data.get("state") or {}).get("required_cpu_model_ids")
            else None
        ),
        "channels": {
            key: {
                field: value.get(field)
                for field in (
                    "selected_provider",
                    "runtime_provider",
                    "capture_attached_provider",
                    "desired_active",
                    "effective_active",
                    "pending_handoff",
                )
            }
            | {"failure_present": value.get("failure_reason") is not None}
            for key, value in data.get("channels", {}).items()
            if key in ("self", "peer") and isinstance(value, dict)
        },
        "channel": (
            {
                field: data.get("channel", {}).get(field)
                for field in (
                    "selected_provider",
                    "runtime_provider",
                    "capture_attached_provider",
                    "desired_active",
                    "effective_active",
                    "pending_handoff",
                    "provider_status",
                )
            }
            if isinstance(data.get("channel"), dict)
            else None
        ),
    }


async def cmd(
    config: Path,
    name: str,
    values: dict,
    root: Path,
    *,
    request_id: str | None = None,
    no_wait: bool = False,
) -> dict:
    path = root / "command-values.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    try:
        argv = ["command", name, "--file", str(path)]
        if request_id is not None:
            argv.extend(("--request-id", request_id))
        if no_wait:
            argv.append("--no-wait")
        return await cli(config, *argv)
    finally:
        path.unlink(missing_ok=True)


async def host_start(config: Path, root: Path) -> tuple[subprocess.Popen, object]:
    log = (root / "host-stderr.log").open("ab")
    process = subprocess.Popen(
        [sys.executable, "-m", "puripuly_heart.main", "run-headless", "--config", str(config)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=log,
    )
    log.close()
    for _ in range(240):
        record = discover(config)
        if record is not None:
            return process, record
        if process.poll() is not None:
            raise RuntimeError(f"host_start_exit_{process.returncode}")
        await asyncio.sleep(0.1)
    process.terminate()
    process.wait(timeout=10)
    raise RuntimeError("host_start_timeout")


async def host_stop(config: Path, process: subprocess.Popen) -> dict:
    if process.poll() is not None:
        return {"exit": process.returncode, "status": "host_already_exited"}
    result = await cli(config, "app", "stop", timeout=30)
    try:
        await asyncio.to_thread(process.wait, 35)
    except TimeoutError:
        process.terminate()
        try:
            await asyncio.to_thread(process.wait, 10)
        except TimeoutError:
            process.kill()
            await asyncio.to_thread(process.wait, 10)
        result["cleanup_forced"] = True
    result["host_exit"] = process.returncode
    return result


async def lost_process_target(root: Path, settings: object, cases: dict) -> None:
    from puripuly_heart.config.paths import default_settings_path

    profile_path = default_settings_path()
    if (
        not profile_path.is_file()
        or json.loads(profile_path.read_text(encoding="utf-8"))
        .get("state", {})
        .get("peer_translation", {})
        .get("eula_accepted")
        is not True
    ):
        cases["lost_target"] = {
            "result": "blocked",
            "reason": "preexisting_peer_consent_unavailable",
        }
        return
    try:
        import sounddevice as sd

        routes = [
            index
            for index, device in enumerate(sd.query_devices())
            if device["max_output_channels"] > 0
            and "CABLE Input(VB-Audio Virtual Cable)" in device["name"]
            and sd.query_hostapis(device["hostapi"])["name"] == "Windows DirectSound"
        ]
    except ImportError, OSError:
        routes = []
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if len(routes) != 1 or not pythonw.is_file():
        cases["lost_target"] = {
            "result": "blocked",
            "reason": "dedicated_vb_cable_or_pythonw_unavailable",
        }
        return
    config = root / "consented-settings.json"
    consented = replace(
        settings,
        state=replace(
            settings.state,
            peer_translation=replace(settings.state.peer_translation, eula_accepted=True),
        ),
    )
    saved = compat.save_vnext_settings(config, consented)
    if not saved.ok:
        cases["lost_target"] = {
            "result": "blocked",
            "reason": "isolated_consent_settings_save_failed",
        }
        return
    script = root / "silent-render.py"
    ready = root / "silent-render.ready"
    script.write_text(
        "import sys, time, sounddevice as sd\n"
        "from pathlib import Path\n"
        "def zero(outdata, frames, timing, status):\n"
        "    outdata.fill(0)\n"
        "with sd.OutputStream(device=int(sys.argv[1]), channels=1, callback=zero):\n"
        "    Path(sys.argv[2]).write_text('ready')\n"
        "    time.sleep(90)\n",
        encoding="utf-8",
    )
    renderer = subprocess.Popen(
        [str(pythonw), str(script), str(routes[0]), str(ready)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    host = None
    try:
        for _ in range(100):
            if ready.is_file():
                break
            if renderer.poll() is not None:
                raise RuntimeError("isolated_silent_renderer_failed")
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("isolated_silent_renderer_timeout")
        host, record = await host_start(config, root)
        options = await request(record, "query", {"name": "audio.processes", "values": {}})
        cases["owned_target_inventory"] = {
            "option_count": len(options.get("options", [])),
            "pythonw_candidates": sum(
                "pythonw" in str(item.get("value", "")).casefold()
                for item in options.get("options", [])
                if isinstance(item, dict)
            ),
            "candidate_value_types": sorted(
                {
                    type(item.get("value")).__name__
                    for item in options.get("options", [])
                    if isinstance(item, dict)
                }
            ),
        }
        cases["owned_target_inventory"]["pythonw_shapes"] = [
            {
                "process_prefix": item["value"].startswith("process:"),
                "pythonw_suffix": item["value"].casefold().endswith("\\pythonw.exe"),
                "disabled": item.get("disabled"),
                "value_length": len(item["value"]),
            }
            for item in options.get("options", [])
            if isinstance(item, dict)
            and isinstance(item.get("value"), str)
            and "pythonw" in item["value"].casefold()
        ]
        matches = [
            item["value"]
            for item in options.get("options", [])
            if isinstance(item, dict)
            and isinstance(item.get("value"), str)
            and item["value"].casefold() == ("process:generic:" + str(pythonw)).casefold()
            and item.get("disabled") is not True
        ]
        if len(matches) != 1:
            cases["lost_target"] = {
                "result": "blocked",
                "reason": "owned_process_target_unavailable",
            }
            return
        cases["consented_target_selection"] = await cmd(
            config, "audio.target.set", {"value": matches[0]}, root
        )
        cases["consented_translation_off"] = await cli(config, "translation", "set", "off")
        activation_start = time.monotonic()
        cases["consented_capture_start"] = await cli(config, "capture", "set", "peer", "on")
        activation_return = time.monotonic()
        before = await request(record, "query", {"name": "providers.status", "values": {}})
        channels_at_return = await request(
            record, "query", {"name": "capture.channels", "values": {}}
        )
        cases["capture_response_timing"] = {
            "duration_seconds": round(activation_return - activation_start, 4),
            "queries_after_response_seconds": round(time.monotonic() - activation_return, 4),
            "provider_effective": before.get("channels", {})
            .get("peer", {})
            .get("effective_active"),
            "capture_effective": channels_at_return.get("channels", {})
            .get("peer", {})
            .get("effective_active"),
        }
        peer_before = before.get("channels", {}).get("peer", {})
        renderer.terminate()
        await asyncio.to_thread(renderer.wait, 10)
        after = peer_before
        for _ in range(100):
            await asyncio.sleep(0.1)
            snapshot = await request(record, "query", {"name": "providers.status", "values": {}})
            after = snapshot.get("channels", {}).get("peer", {})
            if after.get("effective_active") is False or after.get(
                "failure_reason"
            ) != peer_before.get("failure_reason"):
                break
        cases["lost_target"] = {
            "result": "observed" if peer_before.get("effective_active") is True else "blocked",
            "reason": (
                None
                if peer_before.get("effective_active") is True
                else "capture_never_effectively_attached"
            ),
            "selected_before": peer_before.get("selected_provider"),
            "runtime_before": peer_before.get("runtime_provider"),
            "attached_before": peer_before.get("capture_attached_provider"),
            "provider_status_before": peer_before.get("provider_status"),
            "desired_before": peer_before.get("desired_active"),
            "effective_before": peer_before.get("effective_active"),
            "desired_after": after.get("desired_active"),
            "effective_after": after.get("effective_active"),
            "failure_after_present": after.get("failure_reason") is not None,
            "renderer_exit": renderer.returncode,
        }
    except (OSError, RuntimeError, ControlTransportError) as exc:
        cases["lost_target"] = {"result": "blocked", "reason": type(exc).__name__}
    finally:
        if renderer.poll() is None:
            renderer.terminate()
            await asyncio.to_thread(renderer.wait, 10)
        if host is not None:
            cases["lost_target_host_stop"] = await host_stop(config, host)
        script.unlink(missing_ok=True)
        ready.unlink(missing_ok=True)


async def isolated_install_cancellation(root: Path, settings: object, cases: dict) -> None:
    localappdata = root / "private-localappdata"
    localappdata.mkdir()
    config = root / "cancellation-settings.json"
    if not compat.save_vnext_settings(config, settings).ok:
        cases["supported_cancel"] = {"result": "blocked", "reason": "isolated_settings_save_failed"}
        return
    previous = os.environ.get("LOCALAPPDATA")
    os.environ["LOCALAPPDATA"] = str(localappdata)
    host = None
    try:
        host, record = await host_start(config, root)
        accepted = await cmd(config, "models.install", {"backend": "gpu"}, root, no_wait=True)
        cases["supported_cancel_acceptance"] = accepted
        operation_id = accepted.get("operation_id")
        if accepted.get("status") not in ("accepted", "running") or not isinstance(
            operation_id, str
        ):
            cases["supported_cancel"] = {"result": "blocked", "reason": "install_not_accepted"}
            return
        deadline = time.monotonic() + 8
        active = False
        while time.monotonic() < deadline:
            snapshot = await request(record, "query", {"name": "models.status", "values": {}})
            active = bool(snapshot.get("state", {}).get("activities"))
            if active:
                break
            current = await request(record, "operation", {"operation_id": operation_id})
            if current.get("status") in ("failed", "cancelled", "applied", "degraded"):
                break
            await asyncio.sleep(0.05)
        started = time.monotonic()
        cases["query_under_install"] = await cli(config, "app", "status", timeout=5)
        cases["query_under_install_seconds"] = round(time.monotonic() - started, 4)
        pending = await cmd(
            config,
            "settings.apply",
            {"changes": {"locale": "ja"}},
            root,
            request_id="timeout-" + secrets.token_hex(12),
            no_wait=True,
        )
        cases["timeout_accepted_mutation"] = pending
        pending_id = pending.get("operation_id")
        if (
            active
            and pending.get("status") in ("accepted", "running")
            and isinstance(pending_id, str)
        ):
            cases["short_wait_no_replay"] = await cli(
                config, "operation", "wait", pending_id, timeout=0.01
            )
        cases["supported_cancel"] = await cli(
            config, "operation", "cancel", operation_id, timeout=30
        )
        cases["supported_cancel"]["install_active_at_cancel"] = active
        cases["supported_cancel_followup"] = await cli(config, "operation", "status", operation_id)
        cases["supported_cancel_models"] = await cli(config, "query", "models.status")
        if isinstance(pending_id, str):
            cases["accepted_mutation_after_cancel"] = await cli(
                config, "operation", "wait", pending_id
            )
        second = await cmd(config, "models.install", {"backend": "gpu"}, root, no_wait=True)
        cases["stop_under_install_acceptance"] = second
        for _ in range(40):
            current_models = await request(record, "query", {"name": "models.status", "values": {}})
            if current_models.get("state", {}).get("activities"):
                cases["stop_during_install_active"] = True
                break
            await asyncio.sleep(0.05)
        else:
            cases["stop_during_install_active"] = False
        started = time.monotonic()
        cases["stop_during_install"] = await host_stop(config, host)
        cases["stop_during_install_seconds"] = round(time.monotonic() - started, 4)
        host = None
    except (OSError, RuntimeError, ControlTransportError) as exc:
        cases["supported_cancel"] = {"result": "blocked", "reason": type(exc).__name__}
    finally:
        if host is not None:
            cases["supported_cancel_host_stop"] = await host_stop(config, host)
        if previous is None:
            del os.environ["LOCALAPPDATA"]
        else:
            os.environ["LOCALAPPDATA"] = previous


async def isolated_subscriber_progress(root: Path, settings: object, cases: dict) -> None:
    config = root / "subscriber-settings.json"
    if not compat.save_vnext_settings(config, settings).ok:
        cases["slow_subscriber"] = {"result": "blocked", "reason": "isolated_settings_save_failed"}
        return
    host = None
    writer = None
    try:
        host, record = await host_start(config, root)
        reader, writer = await asyncio.open_connection("127.0.0.1", record.port)
        writer.write(
            (
                json.dumps(
                    {
                        "protocol": 1,
                        "instance_id": record.instance_id,
                        "token": record.token,
                        "request_id": secrets.token_hex(12),
                        "method": "subscribe",
                        "arguments": {"topics": ["operation", "settings", "gap"]},
                    }
                )
                + "\n"
            ).encode()
        )
        await writer.drain()
        await reader.readline()
        started = time.monotonic()
        latest_id = None
        for index in range(145):
            receipt = await request(
                record,
                "submit",
                {
                    "name": "settings.apply",
                    "values": {"changes": {"locale": "ja" if index % 2 == 0 else "en"}},
                    "request_id": secrets.token_hex(16),
                },
            )
            latest_id = receipt["operation_id"]
            result = await request(record, "wait", {"operation_id": latest_id, "timeout": 15})
            if result.get("status") != "applied":
                cases["slow_subscriber"] = {
                    "first_nonapplied_index": index,
                    "status": result.get("status"),
                    "error_code": (result.get("error") or {}).get("code"),
                }
                break
        else:
            cases["slow_subscriber_mutations"] = 145
        cases["slow_subscriber_query"] = await cli(config, "app", "status")
        cases["slow_subscriber_elapsed_s"] = round(time.monotonic() - started, 3)
        resumed = follow(record, {"topics": ["gap"], "after": 0})
        try:
            gap = await asyncio.wait_for(anext(resumed), timeout=5)
            cases["bounded_subscriber_gap"] = {
                "topic": gap.get("topic"),
                "snapshot_required": gap.get("snapshot_required"),
                "oldest_after_zero": gap.get("sequence", 0) > 0,
            }
        except TimeoutError:
            cases["bounded_subscriber_gap"] = {"result": "timeout"}
        finally:
            await resumed.aclose()
        if latest_id is not None:
            cases["cancel_committed"] = await cli(config, "operation", "cancel", latest_id)
        cases["stop_while_subscriber_connected"] = await host_stop(config, host)
        host = None
    except (OSError, RuntimeError, ControlTransportError) as exc:
        cases["slow_subscriber"] = {"result": "blocked", "reason": type(exc).__name__}
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        if host is not None:
            cases["slow_subscriber_host_stop"] = await host_stop(config, host)


async def run(report: Path) -> dict:
    if os.name != "nt":
        raise RuntimeError("Windows control host is required")
    if report.resolve().is_relative_to(Path.cwd().resolve()):
        raise ValueError("Evidence report must live outside the checkout")
    evidence = {
        "schema": "puripuly-heart/cli-control-failures/v1",
        "environment": "Windows development interpreter; isolated encrypted-file secrets",
        "cases": {},
    }
    with (
        tempfile.TemporaryDirectory(prefix="puripuly-control-failure-") as temp,
        ExitStack() as cleanup,
    ):
        root = Path(temp)
        config = root / "settings.json"
        settings = new_settings_for_first_run("en-US")
        settings = replace(
            settings,
            intent=replace(
                settings.intent,
                secrets=SecretsIntent("encrypted_file", "isolated-secrets.json"),
                osc=replace(settings.intent.osc, connection_mode="off"),
            ),
        )
        settings = with_telemetry_enabled(settings, False)
        saved = compat.save_vnext_settings(config, settings)
        if not saved.ok:
            raise RuntimeError("isolated_settings_save_failed")
        passphrase_name = "PURIPULY_HEART_SECRETS_PASSPHRASE"
        previous_passphrase = os.environ.get(passphrase_name)
        cleanup.callback(restore_env, passphrase_name, previous_passphrase)
        os.environ[passphrase_name] = secrets.token_urlsafe(48)
        evidence["isolation"] = {
            "temp_config": True,
            "secret_backend": "encrypted_file",
            "new_account": False,
            "consent_accepted": False,
            "ambient_capture": False,
        }
        process = None
        try:
            process, original = await host_start(config, root)
            cases = evidence["cases"]
            cases["initial_status"] = await cli(config, "app", "status")
            cases["initial_models"] = await cli(config, "query", "models.status")
            cases["initial_audio_target"] = await cli(config, "audio", "target", "status")
            cases["peer_consent"] = await cli(config, "capture", "set", "peer", "on")
            cases["isolated_secret_set"] = await cli(
                config, "secrets", "set", "soniox_api_key", "--stdin", stdin=CREDENTIAL_PROBE + "\n"
            )
            cases["isolated_secret_presence"] = await cli(config, "secrets", "presence")
            cases["secret_plaintext_in_settings"] = CREDENTIAL_PROBE.encode() in config.read_bytes()
            secret_file = root / "isolated-secrets.json"
            cases["secret_file_exists"] = secret_file.is_file()
            cases["secret_plaintext_in_encrypted_store"] = (
                CREDENTIAL_PROBE.encode() in secret_file.read_bytes()
                if secret_file.is_file()
                else None
            )
            cases["isolated_secret_delete"] = await cli(
                config, "secrets", "delete", "soniox_api_key"
            )
            cases["isolated_secret_absent"] = await cli(config, "secrets", "presence")
            cases["invalid_target"] = await cmd(
                config, "audio.target.set", {"value": "unavailable-controlled-target-193"}, root
            )
            cases["target_after_failure"] = await cli(config, "audio", "target", "status")
            cases["missing_models_prepare"] = await cmd(
                config, "models.prepare", {"backend": "cpu", "verify_checksums": False}, root
            )
            cases["model_after_prepare"] = await cli(config, "query", "models.status")
            cases["gpu_model_inspection"] = await cmd(
                config, "models.prepare", {"backend": "gpu", "verify_checksums": False}, root
            )
            cases["model_after_gpu_inspection"] = await cli(config, "query", "models.status")
            cases["missing_gpu_provider_apply"] = await cli(
                config, "asr", "set", "--channel", "self", "--provider", "local_qwen_gpu"
            )
            cases["missing_gpu_provider_snapshot"] = await cli(config, "asr", "status")
            before = config.read_bytes()
            lock = SettingsReplacementLock(config)
            try:
                cases["persistence_lock"] = await cmd(
                    config, "settings.apply", {"changes": {"locale": "ja"}}, root
                )
            finally:
                lock.close()
            cases["persistence_file_unchanged"] = before == config.read_bytes()
            cases["persistence_following_query"] = await cli(config, "settings", "current")
            rid = "disconnect-" + secrets.token_hex(12)
            _reader, writer = await asyncio.open_connection("127.0.0.1", original.port)
            payload = {
                "protocol": 1,
                "instance_id": original.instance_id,
                "token": original.token,
                "request_id": secrets.token_hex(12),
                "method": "submit",
                "arguments": {
                    "name": "settings.apply",
                    "values": {"changes": {"locale": "en"}},
                    "request_id": rid,
                },
            }
            writer.write((json.dumps(payload) + "\n").encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.6)
            replay = await request(original, "submit", payload["arguments"])
            complete = await request(
                original, "wait", {"operation_id": replay["operation_id"], "timeout": 15}
            )
            cases["disconnect_dedupe"] = {
                "resubmission_explicit": True,
                "status": complete.get("status"),
                "receipt_status": replay.get("status"),
                "same_operation_id": replay.get("operation_id") == complete.get("operation_id"),
                "revision": complete.get("revision"),
            }
            cases["first_host_stop"] = await host_stop(config, process)
            process = None
            cases["old_endpoint_after_stop"] = await cli(config, "app", "status")
            process, replacement = await host_start(config, root)
            cases["host_restarted"] = {
                "new_instance": replacement.instance_id != original.instance_id
            }
            try:
                await request(original, "query", {"name": "app.status", "values": {}})
            except ControlTransportError as exc:
                cases["old_endpoint"] = {"error_code": exc.code}
            from puripuly_heart.core.control_instance import InstanceRecord

            stale = InstanceRecord(replacement.port, original.token, original.instance_id)
            try:
                await request(stale, "query", {"name": "app.status", "values": {}})
            except ControlTransportError as exc:
                cases["old_session"] = {"error_code": exc.code}
            try:
                await request(replacement, "operation", {"operation_id": replay["operation_id"]})
            except ControlTransportError as exc:
                cases["old_operation"] = {"error_code": exc.code}
            fresh = await request(replacement, "submit", payload["arguments"])
            finished = await request(
                replacement, "wait", {"operation_id": fresh["operation_id"], "timeout": 20}
            )
            cases["request_id_after_restart"] = {
                "status": finished.get("status"),
                "fresh_operation": fresh["operation_id"] != replay["operation_id"],
            }
        finally:
            if process is not None:
                evidence["cases"]["final_stop"] = await host_stop(config, process)
            await isolated_subscriber_progress(root, settings, evidence["cases"])
            await lost_process_target(root, settings, evidence["cases"])
            await isolated_install_cancellation(root, settings, evidence["cases"])
            evidence["cases"]["credential_probe_in_host_stderr"] = (
                (CREDENTIAL_PROBE.encode() in (root / "host-stderr.log").read_bytes())
                if (root / "host-stderr.log").exists()
                else None
            )
            (root / "host-stderr.log").unlink(missing_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.report))
    print(
        json.dumps({"report": str(args.report), "cases": list(result["cases"])}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
