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

    # ---- WhatsApp stand-in (a GUESS at WhatsApp Desktop's accessible layout; real app unverified) ----
    whatsapp_installed = False

    def add_whatsapp(self, chats, linked=True, open_now=True):
        """chats: list of (name, unread_count_or_None_or_'marked', last_message)."""
        self.whatsapp_installed = True
        self._wa_chats = chats
        self._wa_linked = linked
        self.sent_messages: list[tuple[str, str]] = []
        if open_now:
            self._open_whatsapp()

    def _wa_controls(self, filter_text="", open_chat=None):
        if not self._wa_linked:
            return [{"role": "Text", "name": "To use WhatsApp on your computer:"},
                    {"role": "Text", "name": "Scan the QR code with your phone"}]
        out = [{"role": "Edit", "name": "Search or start a new chat", "value": filter_text}]
        for name, unread, last in self._wa_chats:
            if filter_text and filter_text.lower() not in name.lower():
                continue
            row_name = name + (f", {unread} unread messages" if isinstance(unread, int) else "")
            out.append({"role": "ListItem", "name": row_name, "chat": name})
            out += [{"role": "Text", "name": name}, {"role": "Text", "name": "10:42"}, {"role": "Text", "name": last}]
            if isinstance(unread, int):
                out.append({"role": "Text", "name": f"{unread} unread messages"})
            elif unread == "marked":
                out.append({"role": "Text", "name": "Unread"})
        if open_chat:
            out += [{"role": "Text", "name": f"Chat with {open_chat}"}]
            out += [{"role": "Text", "name": m} for c, m in self.sent_messages if c == open_chat]
            out.append({"role": "Edit", "name": "Type a message", "value": ""})
        return out

    def _open_whatsapp(self):
        h = self.next_handle
        self.next_handle += 1
        self.windows[h] = {"title": "WhatsApp", "process": "WhatsApp.Root.exe", "controls": self._wa_controls()}
        self.active = h
        self._wa_handle = h

    # ---- TechDesk stand-in (a GUESS at TechDesk's screens; the real app is unverified) ----
    TD_PRODUCTS = [("Phone charger (Type-C)", 3500), ("Phone charger (iPhone)", 4500), ("USB cable", 1500), ("Power bank 10000mAh", 12000)]

    def add_techdesk(self, pin=False, total_bug=False, shortcut=True):
        self.td = {"page": "dashboard", "form": None, "search": "", "sales": [], "pin": pin, "bug": total_bug, "flash": ""}
        h = self.next_handle
        self.next_handle += 1
        self.windows[h] = {"title": "TechDesk 2.0", "process": "TechDesk.exe", "controls": []}
        self._td_handle = h
        self.active = h
        self._td_render()

    def _td_render(self):
        t = self.td
        if t["pin"]:
            c = [{"role": "Text", "name": "Enter your PIN"}, {"role": "Edit", "name": "PIN", "value": ""}]
        else:
            c = [{"role": "Button", "name": n} for n in ("Dashboard", "Sales", "Repairs", "Inventory")]
            if t["page"] == "sales":
                c.append({"role": "Button", "name": "New Sale"})
                if t["flash"]:
                    c.append({"role": "Text", "name": t["flash"]})
                for inv, items, total in t["sales"]:
                    c += [{"role": "ListItem", "name": inv}, {"role": "Text", "name": items}, {"role": "Text", "name": f"₦{total:,}"}]
            if t["form"] is not None:
                c += [{"role": "Text", "name": "New Sale"}, {"role": "Edit", "name": "Search products", "value": t["search"]}]
                if t["search"]:
                    for name, price in self.TD_PRODUCTS:
                        if all(w in name.lower() for w in t["search"].lower().split()):
                            c += [{"role": "ListItem", "name": name, "td_add": name}, {"role": "Text", "name": f"₦{price:,}"}]
                for line in t["form"]:
                    c += [{"role": "Text", "name": line["name"]}, {"role": "Edit", "name": "Qty", "value": str(line["qty"]), "td_qty": line["name"]}]
                total = sum(dict(self.TD_PRODUCTS)[l["name"]] * l["qty"] for l in t["form"]) - (500 if t["bug"] and t["form"] else 0)
                c += [{"role": "Text", "name": "Total"}, {"role": "Text", "name": f"₦{total:,}"},
                      {"role": "Button", "name": "Complete Sale"}, {"role": "Button", "name": "Cancel"}]
        self.windows[self._td_handle]["controls"] = c

    def _td_total(self):
        return sum(dict(self.TD_PRODUCTS)[l["name"]] * l["qty"] for l in self.td["form"]) - (500 if self.td["bug"] else 0)

    def _td_invoke(self, c):
        t = self.td
        name = c["name"]
        if name in ("Sales", "Dashboard", "Repairs", "Inventory") and c["role"] == "Button":
            t["page"] = name.lower()
        elif name == "New Sale" and c["role"] == "Button":
            t["form"], t["search"], t["flash"] = [], "", ""
        elif c.get("td_add"):
            t["form"].append({"name": c["td_add"], "qty": 1})
            t["search"] = ""
        elif name == "Complete Sale":
            inv = f"INV-{len(t['sales']) + 1:04d}"
            items = ", ".join(f"{l['name']} x{l['qty']}" for l in t["form"])
            t["sales"].append((inv, items, self._td_total()))
            t["form"], t["flash"] = None, f"Sale recorded. Invoice No: {inv}"
        elif name == "Cancel":
            t["form"] = None
        self._td_render()

    def _td_set(self, c, text):
        t = self.td
        if c["name"] == "Search products":
            t["search"] = text
        elif c.get("td_qty"):
            for line in t["form"]:
                if line["name"] == c["td_qty"]:
                    line["qty"] = int(text) if text.isdigit() else line["qty"]
        self._td_render()

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
        if "techdesk" in target.lower():
            self.add_techdesk()
            return
        if target == "whatsapp:":
            if not self.whatsapp_installed:
                raise OSError("No application is associated with the specified file")
            self._open_whatsapp()
            return
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
        if w.get("process") == "TechDesk.exe":
            self._td_invoke(c)
            return
        if w.get("process") == "WhatsApp.Root.exe" and c.get("chat"):
            w["open_chat"] = c["chat"]
            w["controls"] = self._wa_controls(open_chat=c["chat"])
            return
        if c["name"] == "Save":
            self._save(h)
        # MenuItems and "Send to Teams" do nothing visible in this stand-in

    def set_text(self, index, text):
        h, c = self._c(index)
        if c["role"] not in ("Edit", "Document"):
            raise DesktopUnavailable("That control does not accept text.")
        c["value"] = text
        w = self.windows[h]
        if w.get("process") == "TechDesk.exe":
            self._td_set(c, text)
            return
        if w.get("process") == "WhatsApp.Root.exe" and c["name"].startswith("Search"):
            w["controls"] = self._wa_controls(filter_text=text)

    def type_keys(self, text):
        w = self.windows.get(self.active)
        if w and w["controls"] and w["controls"][0]["role"] in ("Document", "Edit"):
            w["controls"][0]["value"] += text

    def send_keys(self, keys):
        w = self.windows.get(self.active, {})
        if keys == ["enter"] and w.get("process") == "WhatsApp.Root.exe" and w.get("open_chat"):
            box = w["controls"][-1]
            if box["value"]:
                self.sent_messages.append((w["open_chat"], box["value"]))
            w["controls"] = self._wa_controls(open_chat=w["open_chat"])
            return
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
