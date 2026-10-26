"""TEST DOUBLE — a tiny simulated Windows desktop with a Notepad-like app.

Used only by tests, because the build workspace has no Windows. It implements
the same DesktopDriver interface as the real UI Automation driver, so the tool
logic (permissions, verification, stale-control detection) is exercised for
real; Windows itself is not.
"""

from __future__ import annotations

import os
import struct
import zlib

from claw.computer.driver import ControlInfo, DesktopDriver, DesktopUnavailable, WindowInfo


def tiny_png() -> bytes:
    raw = b"\x00\xff\xff\xff"
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class FakeDesktop(DesktopDriver):
    name = "fake"

    def __init__(self):
        self.locked = False
        self.windows: dict[int, dict] = {1: {"title": "Desktop clutter - File Explorer", "process": "explorer.exe", "controls": []}}
        self.active = 1
        self.next_handle = 100
        self.saved: dict[str, str] = {}
        self.launched: list[str] = []
        self.clicks_at: list[tuple[int, int]] = []
        self._index: list[tuple[int, int]] = []

    # helpers
    def _notepad(self):
        return {
            "title": "Untitled - Notepad", "process": "notepad.exe",
            "controls": [
                {"role": "Document", "name": "Text editor", "value": ""},
                {"role": "MenuItem", "name": "File"},
                {"role": "MenuItem", "name": "Edit"},
                {"role": "Button", "name": "Save"},
                {"role": "Button", "name": "Send to Teams"},
            ],
        }

    def _open_save_dialog(self, owner: int):
        h = self.next_handle
        self.next_handle += 1
        self.windows[h] = {
            "title": "Save As", "process": "notepad.exe", "owner": owner, "dialog": True,
            "controls": [
                {"role": "Edit", "name": "File name:", "value": "*.txt"},
                {"role": "Button", "name": "Save"},
                {"role": "Button", "name": "Cancel"},
            ],
        }
        self.active = h

    # DesktopDriver
    def available(self):
        return (False, "Windows is locked. Desktop steps can't run on a locked screen (browser steps still can).") if self.locked else (True, "")

    def _info(self, h):
        w = self.windows[h]
        return WindowInfo(handle=h, title=w["title"], process=w["process"], active=h == self.active, rect=(0, 0, 800, 600),
                          dialog=w.get("dialog", False))

    def list_windows(self):
        return [self._info(h) for h in self.windows]

    def active_window(self):
        return self._info(self.active) if self.active in self.windows else None

    def focus_window(self, handle):
        if handle not in self.windows:
            raise DesktopUnavailable("That window has closed.")
        self.active = handle
        return self._info(handle)

    def launch(self, target):
        self.launched.append(target)
        if target.lower().endswith("notepad.exe"):
            h = self.next_handle
            self.next_handle += 1
            self.windows[h] = self._notepad()
            self.active = h

    def controls(self, handle, limit):
        if handle not in self.windows:
            raise DesktopUnavailable("That window has closed.")
        self._index = []
        out = []
        for i, c in enumerate(self.windows[handle]["controls"][:limit]):
            self._index.append((handle, i))
            out.append(ControlInfo(index=len(out), role=c["role"], name=c["name"], value=c.get("value", ""), enabled=c.get("enabled", True)))
        return out

    def _c(self, index):
        if not 0 <= index < len(self._index):
            raise DesktopUnavailable(f"There is no control number {index}.")
        h, i = self._index[index]
        if h not in self.windows:
            raise DesktopUnavailable("That window has closed.")
        return h, self.windows[h]["controls"][i]

    def _save(self, notepad_handle):
        self._open_save_dialog(notepad_handle)

    def invoke(self, index):
        h, c = self._c(index)
        w = self.windows[h]
        if w["title"] == "Save As":
            if c["name"] == "Save":
                name = w["controls"][0]["value"]
                owner = w["owner"]
                if "forbidden" in name.lower():  # a folder the app can't write to: Windows shows an error box
                    eh = self.next_handle
                    self.next_handle += 1
                    self.windows[eh] = {"title": "Save As - Error", "process": "notepad.exe", "dialog": True,
                                        "controls": [{"role": "Text", "name": "Access is denied."}, {"role": "Button", "name": "OK"}]}
                    self.active = eh
                    return
                content = self.windows[owner]["controls"][0]["value"]
                self.saved[name] = content
                if os.path.isabs(name) and os.path.isdir(os.path.dirname(name)):
                    with open(name, "w", encoding="utf-8", newline="") as fh:  # like Notepad: UTF-8, as typed
                        fh.write(content)
                self.windows[owner]["title"] = f"{os.path.basename(name)} - Notepad"
                del self.windows[h]
                self.active = owner
            elif c["name"] == "Cancel":
                owner = w["owner"]
                del self.windows[h]
                self.active = owner
            return
        if c["name"] == "Save":
            self._save(h)
        # MenuItems and "Send to Teams" do nothing visible in this stand-in

    def set_text(self, index, text):
        _, c = self._c(index)
        if c["role"] not in ("Edit", "Document"):
            raise DesktopUnavailable("That control does not accept text.")
        c["value"] = text

    def type_keys(self, text):
        w = self.windows.get(self.active)
        if w and w["controls"] and w["controls"][0]["role"] in ("Document", "Edit"):
            w["controls"][0]["value"] += text

    def send_keys(self, keys):
        if keys == ["ctrl", "s"] and self.windows.get(self.active, {}).get("process") == "notepad.exe":
            self._save(self.active)

    def read(self, index):
        _, c = self._c(index)
        return c.get("value", c["name"])

    def screenshot(self, handle):
        return tiny_png()

    def click_at(self, x, y):
        self.clicks_at.append((x, y))

    def screen_size(self):
        return (1920, 1080)

    def scroll(self, handle, down, clicks):
        w = self.windows[handle]
        w["scroll"] = max(0, w.get("scroll", 0) + (clicks if down else -clicks))
        # long documents show different lines after scrolling
        for c in w["controls"]:
            if c["role"] == "Document":
                c["name"] = f"Text editor (line {w['scroll'] + 1})"

    def menu_select(self, handle, path):
        if [p.lower().rstrip(".") for p in path] in (["file", "save as"], ["file", "save"]) and self.windows[handle]["process"] == "notepad.exe":
            self._save(handle)
            return
        raise DesktopUnavailable(f"There is no menu item {' > '.join(path)}.")
