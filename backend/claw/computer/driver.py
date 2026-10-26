"""Desktop control: the interface every platform driver implements.

Tools never talk to Windows directly; they call a DesktopDriver. The real
driver (windows_uia.py) uses Windows UI Automation through pywinauto. Tests use
a labelled stand-in so the safety and verification logic around it can be
checked anywhere.

All driver calls run on ONE dedicated thread, because Windows UI Automation
(COM) objects must be used from the thread that created them.
"""

from __future__ import annotations

import asyncio
import sys
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field


@dataclass
class WindowInfo:
    handle: int
    title: str
    process: str = ""
    active: bool = False
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)
    dialog: bool = False  # a dialog box (Save As, an error message…) rather than a main window

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ControlInfo:
    index: int
    role: str
    name: str
    automation_id: str = ""
    value: str = ""
    enabled: bool = True
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)

    def line(self) -> str:
        bits = [f"[{self.index}] {self.role}"]
        if self.name:
            bits.append(f'"{self.name}"')
        if self.value and self.value != self.name:
            bits.append(f"value={self.value[:80]!r}")
        if not self.enabled:
            bits.append("(disabled)")
        return " ".join(bits)


@dataclass
class Snapshot:
    """A cheap picture of 'what the screen is like', used to check if an action changed anything."""

    active_title: str
    window_titles: list[str] = field(default_factory=list)
    control_names: list[str] = field(default_factory=list)
    dialog_titles: list[str] = field(default_factory=list)


class DesktopUnavailable(Exception):
    pass


class DesktopDriver(ABC):
    name = "abstract"

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """(True, '') if desktop control can work right now, else (False, reason for the user)."""

    @abstractmethod
    def list_windows(self) -> list[WindowInfo]: ...

    @abstractmethod
    def active_window(self) -> WindowInfo | None: ...

    @abstractmethod
    def focus_window(self, handle: int) -> WindowInfo: ...

    @abstractmethod
    def launch(self, target: str) -> None:
        """Start a program from a resolved path (an .exe or a Start-menu shortcut)."""

    @abstractmethod
    def controls(self, handle: int, limit: int) -> list[ControlInfo]:
        """List the window's controls; indexes stay valid until the next call."""

    @abstractmethod
    def invoke(self, index: int) -> None: ...

    @abstractmethod
    def set_text(self, index: int, text: str) -> None: ...

    @abstractmethod
    def type_keys(self, text: str) -> None:
        """Type literal text into whatever has keyboard focus."""

    @abstractmethod
    def send_keys(self, keys: list[str]) -> None:
        """Press a validated key combination, e.g. ['ctrl', 's']."""

    @abstractmethod
    def read(self, index: int) -> str: ...

    @abstractmethod
    def screenshot(self, handle: int | None) -> bytes:
        """PNG bytes of one window, or of the main screen when handle is None."""

    @abstractmethod
    def click_at(self, x: int, y: int) -> None: ...

    @abstractmethod
    def screen_size(self) -> tuple[int, int]: ...

    def scroll(self, handle: int, down: bool, clicks: int) -> None:
        """Scroll the window's content with the mouse wheel over its centre."""
        raise DesktopUnavailable("Scrolling is not supported here.")

    def menu_select(self, handle: int, path: list[str]) -> None:
        """Choose a menu item by its path, e.g. ["File", "Save As..."]."""
        raise DesktopUnavailable("Menus are not supported here.")

    def snapshot(self, handle: int | None) -> Snapshot:
        active = self.active_window()
        names: list[str] = []
        if handle is not None:
            try:
                names = [f"{c.role}:{c.name}:{c.value[:40]}" for c in self.controls(handle, 150)]
            except Exception:  # noqa: BLE001 — the window may have closed, which is itself a change
                names = ["<gone>"]
        windows = self.list_windows()
        return Snapshot(
            active_title=active.title if active else "",
            window_titles=sorted(w.title for w in windows),
            control_names=names,
            dialog_titles=sorted(w.title for w in windows if w.dialog),
        )


class UnsupportedDriver(DesktopDriver):
    name = "unsupported"

    def __init__(self, reason: str):
        self.reason = reason

    def available(self):
        return False, self.reason

    def _no(self, *a, **k):
        raise DesktopUnavailable(self.reason)

    list_windows = active_window = focus_window = launch = controls = invoke = _no  # type: ignore[assignment]
    set_text = type_keys = send_keys = read = screenshot = click_at = screen_size = scroll = menu_select = _no  # type: ignore[assignment]


class DesktopSession:
    """Owns the driver, its single worker thread, and per-task state."""

    def __init__(self, driver: DesktopDriver):
        self.driver = driver
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="claw-desktop", initializer=_com_init)
        self.last_window: int | None = None
        self.last_controls: list[ControlInfo] = []
        self.screenshot_taken = False

    def reset_task_state(self) -> None:
        self.last_window = None
        self.last_controls = []
        self.screenshot_taken = False

    async def call(self, fn, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, lambda: fn(*args))

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def _com_init() -> None:
    """Runs once on the desktop worker thread: single-threaded COM, as UI Automation expects."""
    if sys.platform == "win32":
        sys.coinit_flags = 2  # type: ignore[attr-defined]  # COINIT_APARTMENTTHREADED, read by comtypes/pywinauto
        try:
            import comtypes  # noqa: PLC0415

            comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
        except Exception:  # noqa: BLE001 — pywinauto initialises COM itself if this fails
            pass


def default_driver() -> DesktopDriver:
    if sys.platform != "win32":
        return UnsupportedDriver("Controlling desktop apps works on Windows only.")
    try:
        from claw.computer.windows_uia import WindowsUIADriver  # noqa: PLC0415
    except ImportError as exc:
        return UnsupportedDriver(f"Desktop control is not installed ({exc.name}). Run scripts\\setup.ps1 again.")
    return WindowsUIADriver()
