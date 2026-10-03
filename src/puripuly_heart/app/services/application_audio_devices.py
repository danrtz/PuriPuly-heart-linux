from __future__ import annotations

import sys

from puripuly_heart.config.audio_host_api import normalize_input_host_api


def enumerate_audio_devices(settings: object | None) -> dict:
    """Enumerate actual input and loopback devices; report unavailable backends explicitly."""
    result: dict = {"host_apis": [], "microphones": [], "loopback_outputs": [], "errors": {}}
    host_api = getattr(
        getattr(getattr(settings, "intent", None), "audio", None), "input_host_api", ""
    )
    result["selected_input_host_api"] = host_api
    if sys.platform.startswith("linux"):
        from puripuly_heart.core.audio.linux_inventory import LINUX_AUDIO_HOST_API, audio_devices

        result["host_apis"] = [LINUX_AUDIO_HOST_API]
        result["selected_input_host_api"] = LINUX_AUDIO_HOST_API
        for outputs, key in ((False, "microphones"), (True, "loopback_outputs")):
            try:
                devices = audio_devices(outputs=outputs)
                result[key] = (
                    [device.name for device in devices]
                    if outputs
                    else [
                        {
                            "name": device.label,
                            "id": device.name,
                            "host_api": LINUX_AUDIO_HOST_API,
                            "selected_host_api": True,
                        }
                        for device in devices
                    ]
                )
                if outputs:
                    result["loopback_output_labels"] = {
                        device.name: device.label for device in devices
                    }
            except Exception as exc:
                result["errors"][key] = type(exc).__name__
        return result
    try:
        import sounddevice as sd

        apis = sd.query_hostapis()
        profile = normalize_input_host_api(host_api)
        result["host_apis"] = [str(api.get("name", "")) for api in apis]
        for device in sd.query_devices():
            if int(device.get("max_input_channels", 0) or 0) <= 0:
                continue
            index = int(device.get("hostapi", -1) or 0)
            api_name = str(apis[index].get("name", "")) if 0 <= index < len(apis) else ""
            result["microphones"].append(
                {
                    "name": str(device.get("name", "")),
                    "host_api": api_name,
                    "selected_host_api": not profile.actual_host_api
                    or api_name == profile.actual_host_api,
                }
            )
    except Exception as exc:
        result["errors"]["microphones"] = type(exc).__name__
    manager = None
    try:
        import pyaudiowpatch as pyaudio

        manager = pyaudio.PyAudio()
        result["loopback_outputs"] = sorted(
            {
                str(info.get("name", "")).strip()
                for info in manager.get_loopback_device_info_generator()
                if str(info.get("name", "")).strip()
            }
        )
    except Exception as exc:
        result["errors"]["loopback_outputs"] = type(exc).__name__
    finally:
        if manager is not None:
            manager.terminate()
    return result
