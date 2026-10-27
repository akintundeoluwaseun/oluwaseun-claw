"""Photograph Claw's interface without a Windows desktop.

    backend/.venv/bin/python scripts/screenshots.py [--out DIR]

Serves desktop/src/renderer over localhost and loads it in Chromium with the
Electron bridge (window.claw / window.quick) replaced by a stand-in that answers
with the shapes the backend really returns. Everything photographed - the HTML,
the CSS, the JavaScript, the layout - is the app's own.

What this is NOT: the app running on Windows. There is no Electron window, no
backend process and no real data here. It catches layout and wording problems,
which is most of them, and it has already caught two: a button pushed onto its
own row, and a status chip showing local-brain wording for a hosted model.

To compare against an earlier version, check that version's renderer into
another folder and run this against both:

    git show HEAD~1:desktop/src/renderer/app.js > /tmp/before/app.js
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import http.server
import json
import socketserver
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RENDERER = ROOT / "desktop" / "src" / "renderer"
# The build workspace has no Playwright browser download; this is the one it has.
LOCAL_CHROMIUM = "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome"

SETTINGS = {
    "version": 3,
    "model": {
        "mode": "cloud", "selected": None, "idle_unload_minutes": 10,
        "provider": "openai_compatible", "base_url": "https://api.example.com/v1",
        "model": "hosted-model", "request_timeout_s": 120.0, "temperature": 0.2,
        "allow_remote_server": False, "api_key": "__keep__", "api_key_set": True,
    },
    "permissions": {
        "modes": {"read_only": "allow", "local_write": "ask", "external": "ask", "destructive": "ask"},
        "authorized_folders": ["C:\\Users\\Seun\\Documents", "C:\\Users\\Seun\\Downloads"],
    },
    "browser": {"channel": "msedge", "headless": False, "search_engine": "duckduckgo",
                "custom_search_url": "", "history_access": "ask", "navigation_timeout_s": 30},
    "agent": {"max_steps": 20, "step_timeout_s": 60, "approval_timeout_s": 600,
              "max_consecutive_failures": 3},
    "desktop": {"start_with_windows": False, "show_quick_bar": True, "keep_awake_while_running": True,
                "notifications": True, "close_to_tray": True},
    "documents": {"ocr_language": "eng"},
    "messages": {"whatsapp_read": "ask", "show_previews": False, "check_every_minutes": 0, "notify": True},
    "voice": {"enabled": True, "model": "zipformer-en-stream", "mode": "click",
              "push_to_talk": "Ctrl+Shift+V", "auto_submit": False, "keep_recordings": False,
              "input_device": ""},
}

VOICE = {
    "enabled": True, "engine": "sherpa-onnx", "runtime_ready": True, "ready": True, "reason": "",
    "streaming": True, "selected": "zipformer-en-stream", "loaded": "zipformer-en-stream",
    "model": {"id": "zipformer-en-stream", "name": "Live (English)", "engine": "sherpa-onnx",
              "kind": "streaming", "streaming": True, "languages": ["en"], "license": "apache-2.0",
              "source": "huggingface.co/...", "verified": True, "present": True,
              "damaged_parts": [], "size_mb": 331.4},
    "catalog": [], "installed": [],
    "download": {"id": None, "status": "idle", "done_bytes": 0, "total_bytes": 0,
                 "message": "", "progress": 0.0},
    "push_to_talk": "Ctrl+Shift+V", "auto_submit": False, "keep_recordings": False, "last_check": 0,
}

ROUTES = {
    "/settings": {"settings": SETTINGS, "error": None,
                  "data_dir": "C:\\Users\\Seun\\AppData\\Roaming\\OluwaseunClaw"},
    "/speech": VOICE,
    "/brain": {"mode": "cloud",
               "hardware": {"total_ram_gb": 16.0, "available_ram_gb": 11.2, "cpu_cores": 8,
                            "gpu_name": None, "gpu_vram_gb": None},
               "hardware_text": "16 GB memory, 8 processor cores",
               "engine": {"state": "stopped", "message": "", "model_id": None, "started_at": None,
                          "restarts": 0, "available": True},
               "ready": True, "active": None, "selected": None, "recommended": "qwen3-vl-4b",
               "installed": [], "catalog": [],
               "download": {"id": None, "status": "idle", "progress": 0.0}},
    "/models/status": {"server_reachable": True, "model_available": True,
                       "provider": "openai_compatible", "base_url": "https://api.example.com/v1",
                       "model": "hosted-model", "message": "Ready", "available_models": [],
                       "reason": "ok", "mode": "cloud"},
    "/tasks": {"tasks": []},
    "/approvals": {"approvals": []},
    "/runner": {"busy": False, "task_id": None},
    "/messages/whatsapp": {"seq": 0, "result": None},
    "/health": {"status": "ok", "version": "0.5.0"},
}

AGENT = {"phase": "idle", "activity": "", "step": 0, "taskId": None, "usingInput": False}

STUB = """
(() => {
  const routes = (__ROUTES__), agent = (__AGENT__);
  const reply = (route) => {
    const base = route.split('?')[0].replace(/\\/$/, '') || '/';
    for (const k of Object.keys(routes)) {
      if (base === k || base.startsWith(k + '/')) return {ok: true, status: 200, body: routes[k]};
    }
    return {ok: true, status: 200, body: {}};
  };
  const noop = () => () => {};
  window.claw = {
    api: async (m, route) => reply(route),
    backendStatus: async () => ({state: 'ready', message: '', detail: ''}),
    agentStatus: async () => (agent),
    restartBackend: async () => ({}), pickFolder: async () => null, openOutput: async () => ({}),
    openDocument: async () => null, saveSearchable: async () => ({}), showDocument: async () => ({}),
    importBrain: async () => null, confirm: async () => true,
    shortcut: async () => 'Ctrl+Shift+Space', stopShortcut: async () => 'Ctrl+Alt+X',
    platform: 'win32', onBackendStatus: noop, onAgentStatus: noop, onTaskStarted: noop,
    onNavigate: noop, onSettingsChanged: noop,
  };
  window.quick = {
    run: async () => ({ok: true}), setMode: () => {}, openApp: () => {}, stop: () => {},
    status: async () => (agent), shortcut: async () => 'Ctrl+Shift+Space',
    stopShortcut: async () => 'Ctrl+Alt+X', voiceStatus: async () => routes['/speech'],
    transcribe: async () => ({ok: true, text: ''}),
    streamStart: async () => ({ok: true, streamId: 'demo'}),
    streamChunk: async () => ({ok: true, text: ''}),
    streamFinish: async () => ({ok: true, text: ''}),
    streamCancel: async () => ({ok: true}),
    onPushToTalk: noop, onStatus: noop, onMode: noop,
  };
})();
"""


def serve(directory: Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


async def main(out: Path, renderer: Path) -> int:
    from playwright.async_api import async_playwright

    out.mkdir(parents=True, exist_ok=True)
    httpd, port = serve(renderer)
    base = f"http://127.0.0.1:{port}"
    stub = STUB.replace("__ROUTES__", json.dumps(ROUTES)).replace("__AGENT__", json.dumps(AGENT))
    errors: list[str] = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=LOCAL_CHROMIUM)
            for theme in ("dark", "light"):
                ctx = await browser.new_context(viewport={"width": 1280, "height": 860},
                                                device_scale_factor=2, color_scheme=theme)
                await ctx.add_init_script(stub)
                page = await ctx.new_page()
                page.on("pageerror", lambda e: errors.append(str(e)[:160]))
                await page.goto(f"{base}/index.html")
                await page.wait_for_timeout(1200)
                await page.screenshot(path=str(out / f"app-home-{theme}.png"))
                for view in ("tasks", "documents"):
                    await page.evaluate(f"document.body.dataset.view = '{view}'")
                    await page.wait_for_timeout(400)
                    await page.screenshot(path=str(out / f"app-{view}-{theme}.png"))
                # Settings is a dialog opened by a click, not a body[data-view] value.
                # Setting the attribute photographs the home page instead, which is how
                # a whole set of "settings" screenshots once turned out to be wrong.
                await page.click("#open-settings")
                await page.wait_for_timeout(700)
                await page.screenshot(path=str(out / f"app-settings-{theme}.png"))
                await ctx.close()

            ctx = await browser.new_context(viewport={"width": 760, "height": 240},
                                            device_scale_factor=2, color_scheme="dark")
            await ctx.add_init_script(stub)
            page = await ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)[:160]))
            await page.goto(f"{base}/quickbar.html")
            await page.wait_for_timeout(900)
            await page.screenshot(path=str(out / "bar-collapsed.png"), omit_background=True)
            await page.evaluate("document.body.dataset.mode = 'expanded'")
            await page.wait_for_timeout(400)
            await page.screenshot(path=str(out / "bar-expanded.png"), omit_background=True)
            await ctx.close()
            await browser.close()
    finally:
        httpd.shutdown()

    shots = sorted(f.name for f in out.glob("*.png"))
    print(f"{len(shots)} screenshots in {out}")
    for name in shots:
        print("   ", name)
    if errors:
        print("\npage errors (the screenshots may be wrong):")
        for e in dict.fromkeys(errors):
            print("   ", e)
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "build" / "screenshots"))
    ap.add_argument("--renderer", default=str(RENDERER), help="a different renderer folder, to compare versions")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(Path(args.out), Path(args.renderer))))
