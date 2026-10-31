"""Windows desktop driver: Windows UI Automation via pywinauto (BSD-3), screenshots via mss (MIT).

Prefers accessibility actions (Invoke/Value/Toggle/Select patterns) over mouse
coordinates; coordinates are only used by the explicit click_at fallback.

NOT YET RUN ON WINDOWS: written against pywinauto 0.6.9's documented API and
syntax-checked in a Linux workspace. Verify with the Batch 3 checklist in
docs/DESKTOP.md before relying on it.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from claw.computer.driver import ControlInfo, DesktopDriver, DesktopUnavailable, WindowInfo

_user32 = ctypes.windll.user32  # type: ignore[attr-defined]
_kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

# Key names accepted by the tools → pywinauto send_keys syntax.
_MODIFIERS = {"ctrl": "^", "alt": "%", "shift": "+"}
_NAMED = {
    "enter": "{ENTER}", "tab": "{TAB}", "escape": "{ESC}", "backspace": "{BACKSPACE}", "delete": "{DELETE}",
    "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}", "home": "{HOME}", "end": "{END}",
    "pageup": "{PGUP}", "pagedown": "{PGDN}", "space": " ", **{f"f{i}": f"{{F{i}}}" for i in range(1, 13)},
}
_ESCAPE = {c: "{" + c + "}" for c in "+^%~(){}[]"}


def _process_name(pid: int) -> str:
    handle = _kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def _rect(w) -> tuple[int, int, int, int]:
    try:
        r = w.rectangle()
        return (r.left, r.top, r.right, r.bottom)
    except Exception:  # noqa: BLE001
        return (0, 0, 0, 0)


class WindowsUIADriver(DesktopDriver):
    name = "windows-uia"

    def __init__(self):
        self._desktop = None
        self._elements: list = []

    # Everything below runs on the single desktop worker thread.
    def _d(self):
        if self._desktop is None:
            from pywinauto import Desktop  # noqa: PLC0415 — imported on the worker thread (COM apartment)

            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]  # match screenshot pixels
            except Exception:  # noqa: BLE001
                pass
            self._desktop = Desktop(backend="uia")
        return self._desktop

    def available(self):
        desk = _user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if not desk:
            return False, "Windows is locked. Desktop steps can't run on a locked screen (browser steps still can)."
        _user32.CloseDesktop(desk)
        return True, ""

    def _check(self):
        ok, reason = self.available()
        if not ok:
            raise DesktopUnavailable(reason)

    def _info(self, w, active_handle: int) -> WindowInfo:
        try:
            pid = w.process_id()
        except Exception:  # noqa: BLE001
            pid = 0
        try:
            dialog = bool(w.is_dialog())
        except Exception:  # noqa: BLE001 — not every wrapper knows
            dialog = False
        return WindowInfo(
            handle=int(w.handle or 0), title=w.window_text(), process=_process_name(pid) if pid else "",
            active=int(w.handle or 0) == active_handle, rect=_rect(w), dialog=dialog,
        )

    def list_windows(self) -> list[WindowInfo]:
        self._check()
        active = int(_user32.GetForegroundWindow() or 0)
        out = []
        for w in self._d().windows():
            try:
                if w.window_text().strip() and w.is_visible():
                    out.append(self._info(w, active))
            except Exception:  # noqa: BLE001 — windows can close while we look
                continue
        return out

    def _window(self, handle: int):
        return self._d().window(handle=handle).wrapper_object()

    def active_window(self) -> WindowInfo | None:
        self._check()
        h = int(_user32.GetForegroundWindow() or 0)
        if not h:
            return None
        try:
            return self._info(self._window(h), h)
        except Exception:  # noqa: BLE001
            return None

    def focus_window(self, handle: int) -> WindowInfo:
        self._check()
        w = self._window(handle)
        if w.is_minimized() if hasattr(w, "is_minimized") else False:
            w.restore()
        try:
            w.set_focus()
        except Exception:  # noqa: BLE001 - fall through to the stronger way below
            pass
        if int(_user32.GetForegroundWindow() or 0) != handle:
            bring_to_front(handle)
        return self._info(w, int(_user32.GetForegroundWindow() or 0))

    def launch(self, target: str) -> None:
        self._check()
        if target.startswith("shell:AppsFolder\\"):
            # A Start-menu app (Store apps such as WhatsApp included), started as the Start menu does.
            import subprocess

            subprocess.Popen(["explorer.exe", target])  # noqa: S603,S607 - target came from Get-StartApps
            return
        os.startfile(target)  # type: ignore[attr-defined]  # target already resolved and checked by the launcher

    def controls(self, handle: int, limit: int) -> list[ControlInfo]:
        self._check()
        win = self._window(handle)
        self._elements = []
        out: list[ControlInfo] = []
        for el in win.descendants():
            if len(out) >= limit:
                break
            try:
                info = el.element_info
                role = info.control_type or ""
                name = (info.name or "").strip()
                if role in ("Pane", "Group", "Custom", "Separator", "Image", "ScrollBar", "Thumb", "TitleBar") and not name:
                    continue
                if not el.is_visible():
                    continue
                value = ""
                if role in ("Edit", "Document", "ComboBox"):
                    value = self._value(el)[:200]
                self._elements.append(el)
                out.append(ControlInfo(
                    index=len(out), role=role, name=name[:120], automation_id=(info.automation_id or "")[:60],
                    value=value, enabled=el.is_enabled(), rect=_rect(el),
                ))
            except Exception:  # noqa: BLE001 — skip controls that vanish mid-scan
                continue
        return out

    def _el(self, index: int):
        if not 0 <= index < len(self._elements):
            raise DesktopUnavailable(f"There is no control number {index}. Look at the window again first.")
        return self._elements[index]

    @staticmethod
    def _value(el) -> str:
        for getter in ("get_value", "window_text"):
            try:
                v = getattr(el, getter)()
                if isinstance(v, str) and v:
                    return v
            except Exception:  # noqa: BLE001
                continue
        try:
            return str(el.legacy_properties().get("Value") or "")
        except Exception:  # noqa: BLE001
            return ""

    def invoke(self, index: int) -> None:
        self._check()
        el = self._el(index)
        role = el.element_info.control_type
        for action in ("invoke", "toggle", "select", "expand"):
            if role in ("CheckBox", "RadioButton") and action == "invoke":
                continue
            fn = getattr(el, action, None)
            if fn is None:
                continue
            try:
                fn()
                return
            except Exception:  # noqa: BLE001 — pattern not supported; try the next one
                continue
        el.click_input()  # last resort: a real mouse click on the control's centre

    def set_text(self, index: int, text: str) -> None:
        self._check()
        el = self._el(index)
        try:
            el.set_edit_text(text)
            return
        except Exception:  # noqa: BLE001
            pass
        el.set_focus()
        self.type_keys(text)

    def type_keys(self, text: str) -> None:
        self._check()
        from pywinauto.keyboard import send_keys  # noqa: PLC0415

        escaped = "".join(_ESCAPE.get(c, c) for c in text)
        send_keys(escaped, with_spaces=True, with_tabs=True, with_newlines=True, pause=0.01)

    def send_keys(self, keys: list[str]) -> None:
        self._check()
        from pywinauto.keyboard import send_keys  # noqa: PLC0415

        mods = "".join(_MODIFIERS[k] for k in keys if k in _MODIFIERS)
        main = [k for k in keys if k not in _MODIFIERS]
        token = _NAMED.get(main[0], main[0]) if main else ""
        send_keys(mods + token, pause=0.05)

    def read(self, index: int) -> str:
        self._check()
        return self._value(self._el(index))

    def screenshot(self, handle: int | None) -> bytes:
        self._check()
        import mss  # noqa: PLC0415
        import mss.tools  # noqa: PLC0415

        with mss.mss() as sct:
            if handle is None:
                region = sct.monitors[1]
            else:
                left, top, right, bottom = _rect(self._window(handle))
                if right <= left or bottom <= top:
                    region = sct.monitors[1]
                else:
                    region = {"left": left, "top": top, "width": right - left, "height": bottom - top}
            shot = sct.grab(region)
            return mss.tools.to_png(shot.rgb, shot.size)

    def click_at(self, x: int, y: int) -> None:
        self._check()
        from pywinauto import mouse  # noqa: PLC0415

        mouse.click(button="left", coords=(int(x), int(y)))

    def scroll(self, handle: int, down: bool, clicks: int) -> None:
        self._check()
        from pywinauto import mouse  # noqa: PLC0415

        left, top, right, bottom = _rect(self._window(handle))
        if right <= left or bottom <= top:
            raise DesktopUnavailable("That window has no visible area to scroll.")
        mouse.scroll(coords=((left + right) // 2, (top + bottom) // 2), wheel_dist=-clicks if down else clicks)

    def menu_select(self, handle: int, path: list[str]) -> None:
        self._check()
        self._d().window(handle=handle).menu_select("->".join(path))

    def screen_size(self) -> tuple[int, int]:
        return int(_user32.GetSystemMetrics(0)), int(_user32.GetSystemMetrics(1))



def bring_to_front(handle: int) -> None:
    """Make a window the one that gets the keyboard, even when Windows refuses at first.

    Ported from Windows-MCP (MIT, (c) 2025 Jeomon George), desktop/service.py
    bring_window_to_top. Windows only hands focus to a process that "received the last
    input"; joining this thread's input to both the current foreground window's thread
    and the target's lets the switch through, so typing lands in the right app.
    """
    import ctypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    if not user32.IsWindow(handle):
        return
    if user32.IsIconic(handle):
        user32.ShowWindow(handle, 9)  # SW_RESTORE
    fg = user32.GetForegroundWindow()
    me = kernel32.GetCurrentThreadId()
    pid = ctypes.c_ulong()
    fg_thread = user32.GetWindowThreadProcessId(fg, ctypes.byref(pid)) if fg else 0
    target_thread = user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    user32.AllowSetForegroundWindow(-1)
    attached = []
    try:
        for t in {fg_thread, target_thread}:
            if t and t != me and user32.AttachThreadInput(me, t, True):
                attached.append(t)
        user32.BringWindowToTop(handle)
        user32.SetForegroundWindow(handle)
    finally:
        for t in attached:
            user32.AttachThreadInput(me, t, False)
