"""Find an installed app by name, without ever running arbitrary commands.

Sources: a few built-in Windows apps, plus Start-menu shortcuts (.lnk) for the
current user and all users. System and admin tools are refused outright, since
they could be used to run code or weaken the computer's security.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from claw.tools.base import ToolError

BUILTIN = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "wordpad": "write.exe",
    "snipping tool": "SnippingTool.exe",
}

BLOCKED = re.compile(
    r"\b(cmd|command prompt|powershell|terminal|windows terminal|regedit|registry|task scheduler|services|"
    r"group policy|gpedit|diskpart|disk management|computer management|bcdedit|wscript|cscript|mshta|"
    r"control panel|uninstall|windows security|defender|firewall|system configuration|msconfig|"
    r"recovery|reset this pc|bitlocker|event viewer|hyper-v|wsl|bash|python|node)\b",
    re.I,
)


@dataclass
class AppMatch:
    name: str
    target: str
    score: float


def start_menu_dirs() -> list[Path]:
    dirs = []
    for base in (os.environ.get("PROGRAMDATA"), os.environ.get("APPDATA")):
        if base:
            dirs.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return [d for d in dirs if d.is_dir()]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def is_system_tool(name: str) -> bool:
    """Names S-CLAW will not open, whatever route is taken to them."""
    return bool(BLOCKED.search(name.strip().lower()))


_START_APPS: tuple[float, dict[str, str]] = (0.0, {})


def start_apps(refresh: bool = False) -> dict[str, str]:
    """Every app in the Start menu, Store apps included: display name -> how to start it.

    Ported from Windows-MCP (MIT, (c) 2025 Jeomon George), desktop/service.py
    get_apps_from_start_menu: PowerShell's Get-StartApps gives each app's AppUserModelID,
    which `shell:AppsFolder\\<id>` starts. Shortcut files alone miss Store apps such as
    WhatsApp Desktop, which is why "open WhatsApp" could fail. Cached for five minutes.
    """
    import subprocess
    import sys
    import time

    global _START_APPS
    if sys.platform != "win32":
        return {}
    if not refresh and time.time() - _START_APPS[0] < 300:
        return _START_APPS[1]
    apps: dict[str, str] = {}
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "Get-StartApps | ConvertTo-Csv -NoTypeInformation"],
                           capture_output=True, text=True, timeout=20, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        import csv
        import io

        for row in csv.DictReader(io.StringIO(r.stdout.strip())):
            if row.get("Name") and row.get("AppID"):
                apps[row["Name"]] = row["AppID"]
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    _START_APPS = (time.time(), apps)
    return apps


def _target_for(app_id: str) -> str:
    # The Apps folder starts both kinds the way the Start menu does: Store apps by their
    # AppUserModelID and classic programs by their known-folder path ID.
    return f"shell:AppsFolder\\{app_id}"


def find_app(name: str, search_dirs: list[Path] | None = None) -> list[AppMatch]:
    query = name.strip().lower()
    if not query:
        raise ToolError("Say which app to open.")
    if BLOCKED.search(query):
        raise ToolError(f"Claw does not open system tools like '{name}'. Open it yourself if you need it.")
    if query in BUILTIN:
        return [AppMatch(query.title(), BUILTIN[query], 1.0)]
    q = set(_words(query))
    matches: list[AppMatch] = []
    dirs = start_menu_dirs() if search_dirs is None else search_dirs
    for root in dirs:
        for path in root.rglob("*.lnk"):
            stem = path.stem
            if BLOCKED.search(stem) or "uninstall" in stem.lower():
                continue
            w = set(_words(stem))
            if not w or not q:
                continue
            overlap = len(q & w) / len(q)
            if overlap == 0:
                continue
            score = overlap - 0.01 * len(w - q)
            matches.append(AppMatch(stem, str(path), score))
    if search_dirs is None:
        for display, app_id in start_apps().items():
            if BLOCKED.search(display) or "uninstall" in display.lower():
                continue
            w = set(_words(display))
            if not w or not q:
                continue
            overlap = len(q & w) / len(q)
            if overlap:
                matches.append(AppMatch(display, _target_for(app_id), overlap - 0.01 * len(w - q)))
    matches.sort(key=lambda m: -m.score)
    seen, unique = set(), []
    for m in matches:
        if m.name.lower() not in seen:
            seen.add(m.name.lower())
            unique.append(m)
    return unique[:8]


def choose_app(name: str, search_dirs: list[Path] | None = None) -> AppMatch:
    found = find_app(name, search_dirs)
    if not found:
        raise ToolError(f"No installed app called '{name}' was found in the Start menu.")
    best = found[0]
    exact = [m for m in found if m.name.lower() == name.strip().lower()]
    if exact:
        return exact[0]
    if len(found) > 1 and found[1].score >= best.score - 0.05:
        options = ", ".join(m.name for m in found[:5])
        raise ToolError(f"More than one app matches '{name}': {options}. Use the exact name.")
    if best.score < 0.5:
        raise ToolError(f"No app clearly matches '{name}'. Closest: {best.name}.")
    return best
