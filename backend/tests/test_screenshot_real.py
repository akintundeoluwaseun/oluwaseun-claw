"""Real screen capture with mss, the same calls the Windows driver makes.
Runs where a display exists (Windows, or Linux under Xvfb)."""

import os
import sys

import pytest

needs_display = pytest.mark.skipif(sys.platform != "win32" and not os.environ.get("DISPLAY"), reason="no display")


@needs_display
def test_mss_full_screen_and_region_to_png():
    import mss
    import mss.tools

    with mss.mss() as sct:
        mon = sct.monitors[1]
        full = mss.tools.to_png(sct.grab(mon).rgb, sct.grab(mon).size)
        part = sct.grab({"left": mon["left"], "top": mon["top"], "width": 50, "height": 40})
        png = mss.tools.to_png(part.rgb, part.size)
    assert full[:8] == b"\x89PNG\r\n\x1a\n" and png[:8] == b"\x89PNG\r\n\x1a\n"
    assert part.size == (50, 40)
