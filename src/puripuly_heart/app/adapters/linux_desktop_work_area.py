from __future__ import annotations

import json
import os
import subprocess

from puripuly_heart.app.ports.desktop_overlay import DesktopWorkArea


def hyprland_work_area(monitors: list[dict]) -> DesktopWorkArea | None:
    usable = [monitor for monitor in monitors if not monitor.get("disabled", False)]
    if not usable:
        return None
    monitor = next((item for item in usable if item.get("focused")), usable[0])
    scale = float(monitor.get("scale", 1))
    if scale <= 0:
        return None
    width, height = int(monitor["width"]), int(monitor["height"])
    if int(monitor.get("transform", 0)) % 2:
        width, height = height, width
    left, top, right, bottom = monitor.get("reserved", [0, 0, 0, 0])
    return (
        int(monitor["x"] + left),
        int(monitor["y"] + top),
        max(1, round(width / scale) - left - right),
        max(1, round(height / scale) - top - bottom),
    )


class LinuxDesktopWorkAreaAdapter:
    def primary_work_area(self) -> DesktopWorkArea | None:
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            try:
                result = subprocess.run(
                    ["hyprctl", "-j", "monitors"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=True,
                )
                return hyprland_work_area(json.loads(result.stdout))
            except OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError:
                pass
        try:
            from Xlib import X, display

            connection = display.Display()
            try:
                root = connection.screen().root
                property = root.get_full_property(
                    connection.intern_atom("_NET_WORKAREA"), X.AnyPropertyType
                )
                if property is not None and len(property.value) >= 4:
                    return tuple(int(value) for value in property.value[:4])
                geometry = root.get_geometry()
                return 0, 0, geometry.width, geometry.height
            finally:
                connection.close()
        except Exception:
            return None
