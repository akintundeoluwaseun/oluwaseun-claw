"""Desktop control on Linux (X11) and macOS.

Linux uses xdotool and wmctrl (the standard tools for this; MIT/GPL programs run as
commands, not linked). macOS uses its own `osascript` (System Events) and `open`.

What works on both: listing windows, bringing one to the front, opening apps, typing,
key combinations, screenshots. Linux also clicks and scrolls at a point. Reading the
buttons and boxes inside another app (Windows' UI Automation, which Claw's Windows
driver uses) is not done here yet: those steps say so plainly instead of guessing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from claw.computer.driver import ControlInfo, DesktopDriver, DesktopUnavailable, WindowInfo

NO_CONTROLS = ("Reading the buttons and boxes inside apps works on Windows only for now. "
               "Use keys, typing or the browser tools instead.")
_X_KEYS = {"enter": "Return", "return": "Return", "tab": "Tab", "esc": "Escape", "escape": "Escape",
           "backspace": "BackSpace", "delete": "Delete", "del": "Delete", "up": "Up", "down": "Down",
           "left": "Left", "right": "Right", "home": "Home", "end": "End", "pageup": "Prior",
           "pagedown": "Next", "space": "space", "win": "super", "windows": "super", "cmd": "super"}
_MAC_KEYCODES = {"enter": 36, "return": 36, "tab": 48, "esc": 53, "escape": 53, "backspace": 51, "delete": 117,
                 "up": 126, "down": 125, "left": 123, "right": 124, "home": 115, "end": 119, "space": 49,
                 "pageup": 116, "pagedown": 121}
_MAC_MODS = {"ctrl": "control down", "control": "control down", "alt": "option down", "option": "option down",
             "shift": "shift down", "cmd": "command down", "win": "command down", "command": "command down"}


def _run(args: list[str], timeout: float = 10.0, input_text: str | None = None) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, input=input_text, check=False)
    except FileNotFoundError as exc:
        raise DesktopUnavailable(f"{args[0]} is not installed.") from exc
    except subprocess.TimeoutExpired as exc:
        raise DesktopUnavailable(f"{args[0]} did not answer in time.") from exc
    if r.returncode != 0:
        raise DesktopUnavailable((r.stderr or r.stdout or f"{args[0]} failed").strip()[:300])
    return r.stdout


def _png_of_screen(region: tuple[int, int, int, int] | None = None) -> bytes:
    import mss
    import mss.tools

    with mss.mss() as m:
        mon = m.monitors[1] if region is None else {"left": region[0], "top": region[1],
                                                     "width": max(1, region[2]), "height": max(1, region[3])}
        shot = m.grab(mon)
        return mss.tools.to_png(shot.rgb, shot.size)


class _NoControls:
    def controls(self, handle: int, limit: int) -> list[ControlInfo]:
        raise DesktopUnavailable(NO_CONTROLS)

    def invoke(self, index: int) -> None:
        raise DesktopUnavailable(NO_CONTROLS)

    def set_text(self, index: int, text: str) -> None:
        raise DesktopUnavailable(NO_CONTROLS)

    def read(self, index: int) -> str:
        raise DesktopUnavailable(NO_CONTROLS)

    def snapshot(self, handle):
        return DesktopDriver.snapshot(self, None)


class LinuxX11Driver(_NoControls, DesktopDriver):
    name = "linux-x11"

    def available(self) -> tuple[bool, str]:
        if not os.environ.get("DISPLAY"):
            if os.environ.get("WAYLAND_DISPLAY"):
                return False, "This desktop uses Wayland, which does not let apps control other windows. Log in with an X11 (Xorg) session."
            return False, "There is no desktop display here."
        missing = [t for t in ("xdotool", "wmctrl") if shutil.which(t) is None]
        if missing:
            return False, f"Install {' and '.join(missing)} (e.g. sudo apt install {' '.join(missing)})."
        return True, ""

    def list_windows(self) -> list[WindowInfo]:
        active = self._active_id()
        out = []
        try:
            listing = _run(["wmctrl", "-lpG"])
        except DesktopUnavailable as exc:
            if "client list" in str(exc).lower():
                raise DesktopUnavailable("No window manager is answering, so windows cannot be listed.") from exc
            raise
        for line in listing.splitlines():
            parts = line.split(None, 8)
            if len(parts) < 8:
                continue
            wid, _desk, pid, x, y, w, h = int(parts[0], 16), parts[1], parts[2], *map(int, parts[3:7])
            title = parts[8] if len(parts) > 8 else ""
            proc = ""
            try:
                proc = open(f"/proc/{pid}/comm", encoding="utf-8").read().strip()
            except OSError:
                pass
            out.append(WindowInfo(wid, title, proc, wid == active, (x, y, w, h),
                                  dialog=any(k in title.lower() for k in ("save as", "open file", "error", "warning"))))
        return out

    def _active_id(self) -> int | None:
        try:
            return int(_run(["xdotool", "getactivewindow"]).strip())
        except (DesktopUnavailable, ValueError):
            return None

    def active_window(self) -> WindowInfo | None:
        a = self._active_id()
        return next((w for w in self.list_windows() if w.handle == a), None)

    def focus_window(self, handle: int) -> WindowInfo:
        _run(["wmctrl", "-ia", hex(handle)])
        return next((w for w in self.list_windows() if w.handle == handle), WindowInfo(handle, ""))

    def launch(self, target: str) -> None:
        if "://" in target or target.endswith(":") or os.path.exists(target):
            subprocess.Popen(["xdg-open", target], start_new_session=True)  # noqa: S603,S607
            return
        name = target.strip().lower().replace(" ", "-")
        for cmd in ([name], ["gtk-launch", name], ["gtk-launch", f"org.gnome.{target.strip().title()}"]):
            if shutil.which(cmd[0]):
                subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
                return
        raise DesktopUnavailable(f"No app called '{target}' was found on this computer.")

    def type_keys(self, text: str) -> None:
        _run(["xdotool", "type", "--delay", "12", "--", text], timeout=60)

    def send_keys(self, keys: list[str]) -> None:
        combo = "+".join(_X_KEYS.get(k.lower(), k.upper() if len(k) > 1 and k[0].lower() == "f" and k[1:].isdigit() else k.lower())
                         for k in keys)
        _run(["xdotool", "key", "--clearmodifiers", combo])

    def screenshot(self, handle: int | None) -> bytes:
        if handle is None:
            return _png_of_screen()
        w = next((w for w in self.list_windows() if w.handle == handle), None)
        return _png_of_screen(w.rect if w else None)

    def click_at(self, x: int, y: int) -> None:
        _run(["xdotool", "mousemove", str(x), str(y), "click", "1"])

    def screen_size(self) -> tuple[int, int]:
        w, h = _run(["xdotool", "getdisplaygeometry"]).split()
        return int(w), int(h)

    def scroll(self, handle: int, down: bool, clicks: int) -> None:
        w = next((w for w in self.list_windows() if w.handle == handle), None)
        if w:
            _run(["xdotool", "mousemove", str(w.rect[0] + w.rect[2] // 2), str(w.rect[1] + w.rect[3] // 2)])
        _run(["xdotool", "click", "--repeat", str(max(1, min(clicks, 30))), "5" if down else "4"])


class MacDriver(_NoControls, DesktopDriver):
    name = "macos"

    def available(self) -> tuple[bool, str]:
        try:
            _run(["osascript", "-e", 'tell application "System Events" to get name of first process'])
        except DesktopUnavailable as exc:
            return False, ("macOS needs permission first: System Settings > Privacy & Security > Accessibility, "
                           f"turn on S-CLAW. ({exc})")
        return True, ""

    def list_windows(self) -> list[WindowInfo]:
        script = ('set out to ""\ntell application "System Events"\n'
                  'set front to name of first process whose frontmost is true\n'
                  'repeat with p in (processes whose background only is false)\n'
                  'repeat with w in windows of p\n'
                  'set out to out & (name of p) & "\t" & (name of w) & "\t" & ((name of p) = front) & linefeed\n'
                  'end repeat\nend repeat\nend tell\nreturn out')
        out = []
        for i, line in enumerate(_run(["osascript", "-e", script]).splitlines()):
            proc, _, rest = line.partition("\t")
            title, _, front = rest.partition("\t")
            out.append(WindowInfo(i + 1, title, proc, front.strip() == "true"))
        return out

    def active_window(self) -> WindowInfo | None:
        return next((w for w in self.list_windows() if w.active), None)

    def focus_window(self, handle: int) -> WindowInfo:
        w = next((w for w in self.list_windows() if w.handle == handle), None)
        if w is None:
            raise DesktopUnavailable("That window is gone.")
        _run(["osascript", "-e", f'tell application "{w.process}" to activate'])
        return w

    def launch(self, target: str) -> None:
        args = ["open", target] if ("://" in target or os.path.exists(target)) else ["open", "-a", target]
        _run(args)

    def type_keys(self, text: str) -> None:
        esc = text.replace("\\", "\\\\").replace('"', '\\"')
        _run(["osascript", "-e", f'tell application "System Events" to keystroke "{esc}"'], timeout=60)

    def send_keys(self, keys: list[str]) -> None:
        mods = [_MAC_MODS[k.lower()] for k in keys if k.lower() in _MAC_MODS]
        rest = [k for k in keys if k.lower() not in _MAC_MODS]
        if len(rest) != 1:
            raise DesktopUnavailable("Give one key with its modifiers, e.g. cmd + s.")
        k = rest[0].lower()
        using = f" using {{{', '.join(mods)}}}" if mods else ""
        stmt = f"key code {_MAC_KEYCODES[k]}{using}" if k in _MAC_KEYCODES else f'keystroke "{k}"{using}'
        _run(["osascript", "-e", f'tell application "System Events" to {stmt}'])

    def screenshot(self, handle: int | None) -> bytes:
        return _png_of_screen()

    def click_at(self, x: int, y: int) -> None:
        if shutil.which("cliclick"):
            _run(["cliclick", f"c:{x},{y}"])
            return
        raise DesktopUnavailable("Clicking at a point on macOS needs cliclick (brew install cliclick).")

    def screen_size(self) -> tuple[int, int]:
        import mss

        with mss.mss() as m:
            mon = m.monitors[1]
            return mon["width"], mon["height"]


def posix_driver() -> DesktopDriver:
    return MacDriver() if sys.platform == "darwin" else LinuxX11Driver()
