from __future__ import annotations

import pytest

from puripuly_heart.app.adapters.linux_desktop_work_area import hyprland_work_area
from puripuly_heart.ui.desktop_window_zorder import WindowEnumerationResult
from puripuly_heart.ui.linux_window_zorder import LinuxWindowZOrderPort


def test_hyprland_work_area_uses_focused_monitor_scale_and_reserved_panel_space():
    monitors = [
        {"x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1},
        {
            "x": -1920,
            "y": 0,
            "width": 3840,
            "height": 2160,
            "scale": 2,
            "focused": True,
            "reserved": [0, 44, 0, 0],
        },
    ]
    assert hyprland_work_area(monitors) == (-1920, 44, 1920, 1036)


def test_hyprland_work_area_accounts_for_rotated_monitor():
    monitors = [
        {
            "x": 1920,
            "y": 0,
            "width": 2560,
            "height": 1440,
            "scale": 1,
            "transform": 1,
            "reserved": [0, 0, 0, 24],
        }
    ]
    assert hyprland_work_area(monitors) == (1920, 0, 1440, 2536)
    assert hyprland_work_area([]) is None
    assert hyprland_work_area([{"disabled": True}]) is None


class FakeLinuxApi:
    def __init__(self):
        self.bounds = (0, 0, 800, 600)
        self.visible = False
        self.closed = 0
        self.click_through = False
        self.actions = []

    def all_top_level_windows_for_process(self, pid):
        return WindowEnumerationResult(windows=(42,))

    def top_level_windows_for_process(self, pid):
        return WindowEnumerationResult(windows=(42,) if self.visible else ())

    def is_window(self, xid):
        return xid == 42

    def is_window_visible(self, xid):
        return self.visible

    def window_title(self, xid):
        return "PuriPuly Overlay"

    def process_id(self, xid):
        return 123

    def window_bounds(self, xid):
        return self.bounds

    def apply_bounds(self, xid, bounds):
        self.bounds = bounds

    def show(self, xid):
        self.visible = True

    def set_click_through(self, xid, enabled):
        self.click_through = enabled

    def extended_style(self, xid):
        return 0x28 if self.click_through else 0

    def set_topmost_no_activate(self, xid):
        return True, None

    def close(self):
        self.closed += 1


@pytest.mark.asyncio
async def test_native_overlay_confirms_actual_geometry_visibility_and_lock_state():
    api = FakeLinuxApi()
    port = LinuxWindowZOrderPort(api=api, bounds_retain_s=0, visibility_retain_s=0)
    port.bind_process(123)
    bounds = dict(x=300, y=700, width=1000, height=300)
    assert (await port.confirm_window_bounds("PuriPuly Overlay", **bounds)).confirmed
    assert (await port.confirm_window_visible("PuriPuly Overlay", **bounds)).confirmed
    result = await port.reassert_topmost_after_click_through()
    assert result.click_through_confirmed
    assert result.topmost_style_present
    port.set_click_through(False)
    assert not api.click_through
    port.close()
    port.close()
    assert api.closed == 1


@pytest.mark.asyncio
async def test_closed_native_port_does_not_move_or_show_another_window():
    api = FakeLinuxApi()
    port = LinuxWindowZOrderPort(api=api)
    port.bind_process(123)
    port.close()
    result = await port.confirm_window_bounds("PuriPuly Overlay", x=1, y=2, width=3, height=4)
    assert not result.confirmed
    assert api.bounds == (0, 0, 800, 600)
    assert not api.visible


@pytest.mark.parametrize("error_name", ["BadWindow", "BadDrawable"])
@pytest.mark.parametrize(
    "method,args,expected",
    [
        ("extended_style", (42,), 0),
        ("set_click_through", (42, True), None),
        ("set_topmost_no_activate", (42,), (False, None)),
        ("show", (42,), None),
        ("apply_bounds", (42, (0, 0, 100, 100)), None),
        ("window_bounds", (42,), None),
    ],
)
def test_native_calls_handle_a_window_destroyed_between_checks(error_name, method, args, expected):
    from Xlib import error

    from puripuly_heart.ui.linux_window_zorder import X11WindowApi

    failure_type = getattr(error, error_name)
    failure = failure_type.__new__(failure_type)
    failure._data = {}

    class DestroyedWindow:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise failure

            return fail

    api = object.__new__(X11WindowApi)
    from types import SimpleNamespace

    api._display = SimpleNamespace(intern_atom=lambda name: 1)
    api._window = lambda xid: DestroyedWindow()
    api.is_window_visible = lambda xid: True
    api._property = lambda *args: None
    assert getattr(api, method)(*args) == expected
