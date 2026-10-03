from __future__ import annotations

from Xlib import X, Xatom, display, error, protocol
from Xlib.ext import shape

from puripuly_heart.ui.desktop_window_zorder import (
    _WS_EX_TOPMOST,
    _WS_EX_TRANSPARENT,
    WindowEnumerationResult,
    WindowsWindowZOrderPort,
)


class X11WindowApi:
    def __init__(self) -> None:
        self._display = display.Display()
        self._root = self._display.screen().root

    def _window(self, xid):
        return self._display.create_resource_object("window", xid)

    def _property(self, window, name):
        prop = window.get_full_property(self._display.intern_atom(name), X.AnyPropertyType)
        return prop.value if prop is not None else None

    def all_top_level_windows_for_process(self, pid: int) -> WindowEnumerationResult:
        windows = []
        pending = [(self._root, 0)]
        while pending:
            parent, depth = pending.pop()
            try:
                for window in parent.query_tree().children:
                    value = self._property(window, "_NET_WM_PID")
                    if value is not None and len(value) and int(value[0]) == pid:
                        windows.append(window.id)
                    elif depth < 2:
                        pending.append((window, depth + 1))
            except error.BadWindow:
                continue
        return WindowEnumerationResult(windows=tuple(windows))

    def top_level_windows_for_process(self, pid: int) -> WindowEnumerationResult:
        return WindowEnumerationResult(
            windows=tuple(
                xid
                for xid in self.all_top_level_windows_for_process(pid).windows
                if self.is_window_visible(xid)
            )
        )

    def is_window(self, xid: int) -> bool:
        try:
            self._window(xid).get_attributes()
            return True
        except error.BadWindow:
            return False

    def is_window_visible(self, xid: int) -> bool:
        try:
            return self._window(xid).get_attributes().map_state == X.IsViewable
        except error.BadWindow:
            return False

    def window_title(self, xid: int) -> str:
        try:
            window = self._window(xid)
            value = self._property(window, "_NET_WM_NAME")
            if value is None:
                value = window.get_wm_name() or ""
            return (
                value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
            )
        except error.BadWindow:
            return ""

    def window_bounds(self, xid: int) -> tuple[int, int, int, int] | None:
        try:
            window = self._window(xid)
            geometry = window.get_geometry()
            position = self._root.translate_coords(window, 0, 0)
            return (position.x, position.y, geometry.width, geometry.height)
        except error.BadWindow:
            return None

    def process_id(self, xid: int) -> int | None:
        try:
            value = self._property(self._window(xid), "_NET_WM_PID")
            return int(value[0]) if value is not None and len(value) else None
        except error.BadWindow:
            return None

    def extended_style(self, xid: int) -> int:
        window = self._window(xid)
        states = self._property(window, "_NET_WM_STATE")
        above = self._display.intern_atom("_NET_WM_STATE_ABOVE")
        result = (
            _WS_EX_TOPMOST
            if (
                window.get_attributes().override_redirect
                or (states is not None and above in states)
            )
            else 0
        )
        if self._display.has_extension("SHAPE"):
            rectangles = window.shape_get_rectangles(shape.SK.Input).rectangles
            if not rectangles:
                result |= _WS_EX_TRANSPARENT
        return result

    def set_click_through(self, xid: int, enabled: bool) -> None:
        window = self._window(xid)
        geometry = window.get_geometry()
        was_visible = self.is_window_visible(xid)
        if bool(window.get_attributes().override_redirect) != enabled:
            window.unmap()
            window.change_attributes(override_redirect=enabled)
            if was_visible:
                window.map()
        rectangles = [] if enabled else [(0, 0, geometry.width, geometry.height)]
        window.shape_rectangles(shape.SO.Set, shape.SK.Input, X.Unsorted, 0, 0, rectangles)
        self._display.sync()

    def set_topmost_no_activate(self, xid: int) -> tuple[bool, int | None]:
        window = self._window(xid)
        if window.get_attributes().override_redirect:
            window.configure(stack_mode=X.Above)
            self._display.sync()
            return True, None
        event = protocol.event.ClientMessage(
            window=xid,
            client_type=self._display.intern_atom("_NET_WM_STATE"),
            data=(32, [1, self._display.intern_atom("_NET_WM_STATE_ABOVE"), 0, 1, 0]),
        )
        self._root.send_event(
            event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask
        )
        self._display.flush()
        return True, None

    def show(self, xid) -> None:
        self._window(xid).map()
        self._display.sync()

    def apply_bounds(self, xid, bounds) -> None:
        window = self._window(xid)
        if not self.is_window_visible(xid):
            window.change_property(
                self._display.intern_atom("_NET_WM_WINDOW_TYPE"),
                Xatom.ATOM,
                32,
                [self._display.intern_atom("_NET_WM_WINDOW_TYPE_UTILITY")],
            )
        x, y, width, height = bounds
        window.configure(x=x, y=y, width=width, height=height)
        self._display.sync()

    def close(self) -> None:
        self._display.close()


class LinuxWindowZOrderPort(WindowsWindowZOrderPort):
    def __init__(self, *, api=None, **kwargs) -> None:
        super().__init__(api=api or X11WindowApi(), **kwargs)

    def set_click_through(self, enabled: bool) -> None:
        if self._closed or self._pid is None:
            return
        for xid in self._api.top_level_windows_for_process(self._pid).windows:
            self._api.set_click_through(xid, enabled)

    async def reassert_topmost_after_click_through(self):
        self.set_click_through(True)
        return await super().reassert_topmost_after_click_through()

    async def _apply_bounds(self, expected_title, bounds, *, show=False) -> None:
        import asyncio

        for _ in range(30):
            if self._closed or self._pid is None:
                return
            windows = self._api.all_top_level_windows_for_process(self._pid).windows
            matched = [xid for xid in windows if self._api.window_title(xid) == expected_title]
            if len(matched) == 1:
                if show:
                    self._api.show(matched[0])
                    await asyncio.sleep(0.1)
                self._api.apply_bounds(matched[0], bounds)
                return
            await asyncio.sleep(0.02)

    async def confirm_window_bounds(self, expected_title, *, x, y, width, height):
        await self._apply_bounds(expected_title, (x, y, width, height))
        return await super().confirm_window_bounds(
            expected_title, x=x, y=y, width=width, height=height
        )

    async def confirm_window_visible(
        self, expected_title, *, x, y, width, height, on_first_visible=None
    ):
        import asyncio

        await asyncio.sleep(0.1)
        await self._apply_bounds(expected_title, (x, y, width, height), show=True)
        return await super().confirm_window_visible(
            expected_title, x=x, y=y, width=width, height=height, on_first_visible=on_first_visible
        )

    def close(self) -> None:
        if self._closed:
            return
        super().close()
        self._api.close()
