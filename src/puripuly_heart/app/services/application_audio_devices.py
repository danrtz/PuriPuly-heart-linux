from __future__ import annotations

from puripuly_heart.config.audio_host_api import normalize_input_host_api


def enumerate_audio_devices(settings: object | None) -> dict:
    """Enumerate actual input and loopback devices; report unavailable backends explicitly."""
    result: dict = {"host_apis": [], "microphones": [], "loopback_outputs": [], "errors": {}}
    host_api = getattr(
        getattr(getattr(settings, "intent", None), "audio", None), "input_host_api", ""
    )
    result["selected_input_host_api"] = host_api
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
