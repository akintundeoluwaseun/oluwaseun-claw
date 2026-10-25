import json

import pytest
from fastapi.testclient import TestClient

from claw.api.app import create_app
from tests.fake_model_server import FakeModelServer

TOKEN = "t" * 40
VALID_PLAN = {
    "goal": "Find the newest PDF in Downloads and summarize it",
    "steps": [
        {"description": "List PDF files in Downloads", "capability": "files", "risk": "read_only", "expected_result": "A list of PDFs"},
        {"description": "Read the newest PDF", "capability": "files", "risk": "read_only", "expected_result": "Its text"},
        {"description": "Write a summary", "capability": "reasoning", "risk": "read_only", "expected_result": "A short summary"},
    ],
    "questions": [],
}


@pytest.fixture
def fake_server():
    with FakeModelServer() as srv:
        yield srv


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def make_client(data_dir):
    def _make(settings: dict | None = None):
        if settings is not None:
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "settings.json").write_text(json.dumps(settings))
        client = TestClient(create_app(data_dir, TOKEN), base_url="http://127.0.0.1")
        client.headers["X-Claw-Token"] = TOKEN
        return client

    return _make


# ---------- Browser fixtures (Batch 2) ----------
import os
from pathlib import Path

from claw.browser.session import BrowserSession
from claw.config import Settings
from claw.permissions.policy import PermissionPolicy
from claw.tools.base import ToolContext
from tests.site_server import SiteServer

_LOCAL_CHROMIUM = "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome"
if not os.environ.get("CLAW_BROWSER_EXECUTABLE") and Path(_LOCAL_CHROMIUM).exists():
    # Build workspace only: Playwright's own browser download is blocked here.
    os.environ["CLAW_BROWSER_EXECUTABLE"] = _LOCAL_CHROMIUM


def browser_settings(site_url: str, folders: list[str] | None = None, **browser) -> Settings:
    return Settings.model_validate(
        {
            "browser": {
                "channel": "chromium",
                "headless": True,
                "search_engine": "custom",
                "custom_search_url": site_url + "/search?q={query}",
                **browser,
            },
            "permissions": {"authorized_folders": folders or []},
            "agent": {"step_timeout_s": 20, "approval_timeout_s": 30},
        }
    )


@pytest.fixture
def site():
    with SiteServer() as s:
        yield s


@pytest.fixture
async def tool_ctx(tmp_path, site):
    save_dir = tmp_path / "saved"
    save_dir.mkdir()
    settings = browser_settings(site.base_url, [str(save_dir)])
    browser = BrowserSession(tmp_path / "data", lambda: settings.browser)
    ctx = ToolContext(
        settings=settings,
        policy=PermissionPolicy(settings.permissions.modes, settings.permissions.authorized_folders),
        data_dir=tmp_path / "data",
        browser=browser,
        task_id="t1",
    )
    yield ctx
    await browser.close()


# ---------- Desktop fixtures (Batch 3) ----------
from claw.computer.driver import DesktopSession
from tests.fake_desktop import FakeDesktop


@pytest.fixture
async def desk_ctx(tool_ctx, tmp_path):
    """tool_ctx plus the stand-in desktop and a pretend Start menu."""
    fake = FakeDesktop()
    session = DesktopSession(fake)
    tool_ctx.desktop = session
    menu = tmp_path / "startmenu"
    (menu / "Microsoft Office").mkdir(parents=True)
    for name in ("Excel.lnk", "Word.lnk", "Microsoft Office/OneNote.lnk", "Command Prompt.lnk", "Visual Studio Code.lnk", "Visual Studio Installer.lnk"):
        (menu / name).write_text("shortcut")
    tool_ctx.start_menu_dirs = [menu]
    tool_ctx.fake = fake
    yield tool_ctx
    session.close()
