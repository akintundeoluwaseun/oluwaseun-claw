"""The Linux (X11) desktop driver against a real X display (run under xvfb-run, with xdotool and wmctrl)."""

import os
import shutil
import subprocess
import sys
import time

import pytest

from claw.computer.driver import DesktopUnavailable
from claw.computer.posix_driver import LinuxX11Driver, NO_CONTROLS

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not os.environ.get("DISPLAY") or not shutil.which("xdotool") or not shutil.which("wmctrl"),
    reason="needs Linux with an X display, xdotool and wmctrl")


def test_no_display_is_explained(monkeypatch):
    monkeypatch.delenv("DISPLAY")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    ok, why = LinuxX11Driver().available()
    assert not ok and "Wayland" in why


def test_screen_size_screenshot_and_keys():
    d = LinuxX11Driver()
    assert d.available() == (True, "")
    w, h = d.screen_size()
    assert w > 0 and h > 0
    png = d.screenshot(None)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    d.send_keys(["ctrl", "a"])          # no window manager needed for a key press
    d.type_keys("hello")
    with pytest.raises(DesktopUnavailable, match="Windows only"):
        d.controls(1, 10)
    assert NO_CONTROLS


def test_a_window_is_listed_and_focused_when_a_window_manager_runs():
    wm = shutil.which("openbox") or shutil.which("fluxbox") or shutil.which("xfwm4")
    app = shutil.which("xmessage") or shutil.which("xeyes")
    if not wm or not app:
        pytest.skip("needs a window manager and a small X app")
    p_wm = subprocess.Popen([wm], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p_app = subprocess.Popen([app, "claw test window"] if app.endswith("xmessage") else [app],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        d = LinuxX11Driver()
        wins = []
        for _ in range(50):
            try:
                wins = d.list_windows()
            except DesktopUnavailable:   # the window manager is still starting
                wins = []
            if wins:
                break
            time.sleep(0.2)
        assert wins
        assert d.focus_window(wins[0].handle).handle == wins[0].handle
    finally:
        p_app.kill()
        p_wm.kill()
