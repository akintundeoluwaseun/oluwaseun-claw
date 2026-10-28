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
                "notifications": True, "close_to_tray": True, "brief_at": "08:00",
                "theme": "system", "show_tips": True},
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

EDITIONS = {
    "online": {
        "id": "online", "name": "Claw Online", "online": True, "local_inference": False,
        "service_configured": True, "service_url": "https://brain.oluwaseunclaw.com/v1",
        "bundled_model": "", "default_mode": "service",
        "modes": {"builtin": {"allowed": False,
                              "why_not": "Claw Online does not include a brain for this computer."},
                  "service": {"allowed": True, "why_not": ""},
                  "cloud": {"allowed": True, "why_not": ""},
                  "custom": {"allowed": True, "why_not": ""}},
    },
    "local": {
        "id": "local", "name": "Claw Local", "online": False, "local_inference": True,
        "service_configured": False, "service_url": "", "bundled_model": "qwen3-vl-4b",
        "default_mode": "builtin",
        "modes": {"builtin": {"allowed": True, "why_not": ""},
                  "service": {"allowed": False,
                              "why_not": "This copy of Claw was built without a Claw service address."},
                  "cloud": {"allowed": True, "why_not": ""},
                  "custom": {"allowed": True, "why_not": ""}},
    },
}

ROUTES = {
    "/settings": {"settings": SETTINGS, "error": None,
                  "data_dir": "C:\\Users\\Seun\\AppData\\Roaming\\S-CLAW"},
    "/speech": {**VOICE, "enabled": True, "ready": True},
    "/brain": {"mode": "cloud",
               "hardware": {"total_ram_gb": 16.0, "available_ram_gb": 11.2, "cpu_cores": 8,
                            "gpu_name": None, "gpu_vram_gb": None},
               "hardware_text": "16 GB memory, 8 processor cores",
               "engine": {"state": "stopped", "message": "", "model_id": None, "started_at": None,
                          "restarts": 0, "available": True},
               "ready": True, "active": None, "selected": None, "recommended": "qwen3-vl-4b",
               "installed": [], "catalog": [],
               "download": {"id": None, "status": "idle", "progress": 0.0}},
    "/edition": EDITIONS["local"],
    "/models/probe": {"server_reachable": True, "model_available": True, "reason": "ok",
                      "provider": "openai_compatible", "base_url": "https://api.example.com/v1",
                      "model": "hosted-model", "message": "Ready", "available_models": ["hosted-model"]},
    # A real reply from a real round-trip is what the app now shows; the stand-in
    # answers in the same shape so the wording can be photographed.
    "/models/selftest": {"ok": True, "reason": "ok", "ms": 1240, "mode": "cloud",
                         "model": "hosted-model", "reply": "Ready",
                         "message": "The model replied in 1.2s."},
    "/models/status": {"server_reachable": True, "model_available": True,
                       "provider": "openai_compatible", "base_url": "https://api.example.com/v1",
                       "model": "hosted-model", "message": "Ready", "available_models": [],
                       "reason": "ok", "mode": "cloud"},
    "/brief": {"day": "2026-11-03", "headline": "One thing today: Site visit at 15:00.",
               "agenda": [{"summary": "Site visit", "at": "15:00", "location": "Meeting room 2",
                           "all_day": False, "past": False, "starts_at": None}],
               "unfinished": [], "not_included": [], "made_at": "", "text": ""},
    "/calendar/due": {"due": []},
    # A live standing reply with two prepared drafts, as the panel really reads.
    "/standing-reply": {
        "authorised": True, "message": "Thanks! I'm tied up — please come back in 3 hours.",
        "minutes_left": 97, "drafts_made": 2, "account_hint": "WhatsApp",
        "sends": False, "note": "S-CLAW prepares these replies. You send them.",
        "drafts": [
            {"chat": "Daniel Ward", "message": "Thanks! I'm tied up — please come back in 3 hours.",
             "because": "2 unread message(s)"},
            {"chat": "Priya Raman", "message": "Thanks! I'm tied up — please come back in 3 hours.",
             "because": "a new message"},
        ]},
    "/jobs": {"note": "Jobs run only while S-CLAW is open. A computer that is off does nothing.",
              "jobs": [
                  {"id": "1", "name": "Site check", "task_text": "check whether oluwaseun-joshua-site.vercel.app is up",
                   "kind": "every", "minutes": 60, "at": "", "enabled": True,
                   "schedule": "every hour", "next_run": "2026-10-27T18:40:00Z",
                   "last_run": "2026-10-27T17:40:00Z", "last_status": "completed",
                   "last_detail": "It answered in 240ms.", "only_while_running": True},
                  {"id": "2", "name": "Morning report", "task_text": "write today's agenda to a file",
                   "kind": "daily", "minutes": 0, "at": "07:30", "enabled": True,
                   "schedule": "every day at 07:30", "next_run": "2026-10-28T07:30:00Z",
                   # A skip does not set last_run: the job has not had its turn.
                   "last_run": None, "last_status": "skipped",
                   "last_detail": "S-CLAW was busy with something else.", "only_while_running": True},
                  {"id": "3", "name": "Supplier prices", "task_text": "check the supplier price list page for changes",
                   "kind": "daily", "minutes": 0, "at": "18:00", "enabled": False,
                   "schedule": "every day at 18:00", "next_run": None,
                   "last_run": None, "last_status": None, "last_detail": None,
                   "only_while_running": True},
              ]},
    # Plausible memories, so the panel can be photographed as it really reads.
    "/memory": {"memories": [
        {"id": "1", "kind": "preference", "subject": "me", "fact": "prefers meetings after 10am",
         "source": "you told S-CLAW", "updated_at": "2026-10-24T09:12:00Z", "task_id": None},
        {"id": "2", "kind": "contact", "subject": "Daniel Ward",
         "fact": "project manager at Northwind; reachable on WhatsApp",
         "source": "you told S-CLAW", "updated_at": "2026-10-22T16:40:00Z", "task_id": None},
        {"id": "3", "kind": "project", "subject": "Northwind", "fact": "hand-over is in March",
         "source": "you told S-CLAW", "updated_at": "2026-10-20T11:05:00Z", "task_id": None},
        {"id": "4", "kind": "decision", "subject": "installers",
         "fact": "Inno Setup rather than NSIS, because of the 2 GB limit",
         "source": "you told S-CLAW", "updated_at": "2026-10-19T08:30:00Z", "task_id": None},
    ], "kinds": ["contact", "decision", "preference", "project"]},
    "/tasks": {"tasks": []},
    "/approvals": {"approvals": []},
    "/runner": {"busy": False, "task_id": None},
    "/messages/whatsapp": {"seq": 0, "result": None},
    "/health": {"status": "ok", "version": "0.5.0"},
}

SENDING_APPROVAL = {
    # The same shape /tasks/{id}/events returns while a step waits for the person.
    "status": "awaiting_approval",
    "result": None,
    "plan": None,
    "error": None,
    "events": [
        {"id": 1, "kind": "plan", "at": "2026-10-27T09:14:02Z",
         "data": {"steps": ["Open Telegram", "Find the chat with John Doe",
                            "Type the message", "Send it"]}},
        {"id": 2, "kind": "verified", "at": "2026-10-27T09:14:09Z",
         "data": {"step": 3, "tool": "type_text", "detail": "Typed 36 characters into 'Message'."}},
        {"id": 3, "kind": "awaiting_approval", "at": "2026-10-27T09:14:10Z",
         "data": {"step": 4, "tool": "press_keys"}},
    ],
    "approvals": [{
        "task_id": "demo",
        "id": "demo-approval",
        "step": 4,
        "tool": "press_keys",
        "description": 'Press a key or shortcut, e.g. ["ctrl", "s"].',
        "risk": "destructive",
        "sensitive_scope": None,
        "args": {"keys": ["enter"]},
        "reason": "The message is written in the box, so Enter sends it.",
        "caution": "",
        # Copied from what the backend returns for this exact state, not written here.
        "context": "This sends the message to 'John Doe' in telegram.exe. "
                   "The message reads: \u201cRunning late - I will be there at 2.\u201d",
    }],
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
    // The same fields src/creator.js hands the renderer over IPC.
    creator: async () => ({
      name: 'Oluwaseun', holder: 'Akintunde Oluwaseun Joshua',
      site: 'https://oluwaseun-joshua-site.vercel.app/',
      whatsapp: 'oluwaseun85148', year: 2026, version: '0.5.0',
      copyright: 'Copyright \u00a9 2026 Akintunde Oluwaseun Joshua',
    }),
    openLink: async () => ({ok: true}), copyText: async () => ({ok: true}),
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
    def make_stub(routes=None):
        return (STUB.replace("__ROUTES__", json.dumps(routes or ROUTES))
                    .replace("__AGENT__", json.dumps(AGENT)))

    stub = make_stub()
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
                # The chosen theme, through the control a person would use. Setting
                # data-theme by hand photographs the colours but not the button's
                # own state, and the two disagreeing is exactly the bug worth
                # catching here.
                other = "light" if theme == "dark" else "dark"
                await page.click("#toggle-theme")
                await page.wait_for_timeout(400)
                await page.screenshot(path=str(out / f"app-forced-{other}.png"))
                await page.click("#toggle-theme")
                await page.wait_for_timeout(250)
                # The same screen with a task typed, so the primary action is
                # photographed enabled rather than greyed out.
                await page.fill("#task-input", "Open Telegram and tell John I am running late")
                await page.wait_for_timeout(350)
                await page.screenshot(path=str(out / f"app-home-typed-{theme}.png"))
                await page.fill("#task-input", "")
                # The briefing time lives in the Background panel; photographed so the
                # wording about "only while S-CLAW is running" can be read.
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
                # "Test connection" now sends a real prompt and quotes the answer, instead
                # of saying the model "answered" after a check that generated nothing.
                # Who made it, and the badge that opens the site.
                await page.click('.set-tab[data-panel="set-messages"]')
                await page.wait_for_timeout(400)
                # The standing reply sits below the WhatsApp box; photograph the
                # section itself rather than whatever happens to be in view.
                sr = page.locator("#sr-box")
                await sr.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
                await page.screenshot(path=str(out / f"app-standing-{theme}.png"))
                await page.click('.set-tab[data-panel="set-jobs"]')
                await page.wait_for_timeout(500)
                await page.screenshot(path=str(out / f"app-jobs-{theme}.png"))
                await page.click('.set-tab[data-panel="set-memory"]')
                await page.wait_for_timeout(500)
                await page.screenshot(path=str(out / f"app-memory-{theme}.png"))
                await page.click('.set-tab[data-panel="set-background"]')
                await page.wait_for_timeout(400)
                await page.screenshot(path=str(out / f"app-background-{theme}.png"))
                await page.click('.set-tab[data-panel="set-about"]')
                await page.wait_for_timeout(400)
                await page.screenshot(path=str(out / f"app-about-{theme}.png"))
                await page.click('.set-tab[data-panel="set-brain"]')
                await page.wait_for_timeout(300)
                await page.click("#s-cloud-test")
                await page.wait_for_timeout(600)
                await page.screenshot(path=str(out / f"app-model-test-{theme}.png"),
                                      clip=await page.evaluate("""() => {
                                        const b = document.getElementById('cloud-box').getBoundingClientRect();
                                        return {x: b.x - 12, y: b.y - 12, width: b.width + 24, height: b.height + 24};
                                      }"""))
                await ctx.close()

            # One application, two packaging profiles: the Settings page offers what the
            # build can actually do, so each edition is photographed as it really appears.
            for name, edition in EDITIONS.items():
                mode = "service" if edition["online"] else "builtin"
                routes = {**ROUTES, "/edition": edition,
                          "/settings": {**ROUTES["/settings"],
                                        "settings": {**SETTINGS,
                                                     "model": {**SETTINGS["model"], "mode": mode}}},
                          "/models/status": {**ROUTES["/models/status"], "mode": mode},
                          # /brain drives the wording under the brain box; leaving the
                          # default here photographed Claw Local saying it was using a
                          # hosted model, which is exactly the confusion to avoid.
                          "/brain": {**ROUTES["/brain"], "mode": mode}}
                ctx = await browser.new_context(viewport={"width": 1180, "height": 900},
                                                device_scale_factor=2, color_scheme="dark")
                await ctx.add_init_script(make_stub(routes))
                page = await ctx.new_page()
                page.on("pageerror", lambda e: errors.append(str(e)[:160]))
                await page.goto(f"{base}/index.html")
                await page.wait_for_timeout(900)
                await page.click("#open-settings")
                await page.wait_for_timeout(700)
                # The brain section of the Settings panel itself: photographing a clip of
                # the window caught the home page behind the dialog instead.
                section = page.locator("#s-think").locator("xpath=ancestor::section[1]")
                await section.scroll_into_view_if_needed()
                await page.wait_for_timeout(250)
                await section.screenshot(path=str(out / f"edition-{name}.png"))
                await ctx.close()

            ctx = await browser.new_context(viewport={"width": 760, "height": 240},
                                            device_scale_factor=2, color_scheme="dark")
            await ctx.add_init_script(stub)
            page = await ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)[:160]))
            await page.goto(f"{base}/quickbar.html")
            await page.wait_for_timeout(900)
            await page.screenshot(path=str(out / "bar-collapsed.png"), omit_background=True)
            # The hide control appears on hover, so hovering is the only way to
            # photograph what a person actually sees when they reach for it.
            await page.hover("#pill")
            await page.wait_for_timeout(350)
            await page.screenshot(path=str(out / "bar-hover.png"), omit_background=True)
            await page.evaluate("document.body.dataset.mode = 'expanded'")
            await page.wait_for_timeout(400)
            await page.screenshot(path=str(out / "bar-expanded.png"), omit_background=True)
            await ctx.close()

            # Approving a send. "press_keys: [enter]" is what the arguments say; the
            # card has to say who receives it and what it reads, or the approval is
            # a formality the person cannot actually judge.
            for theme in ("dark", "light"):
                ctx = await browser.new_context(viewport={"width": 1180, "height": 900},
                                                device_scale_factor=2, color_scheme=theme)
                # The specific route first: the stub answers with the first key that
                # matches, and "/tasks" would otherwise swallow "/tasks/demo/events".
                await ctx.add_init_script(make_stub({
                    "/tasks/demo/events": SENDING_APPROVAL,
                    **ROUTES,
                    # One body serves both uses: creating a task reads .id, the history list reads .tasks.
                    "/tasks": {"id": "demo", "tasks": []},
                    "/approvals": {"approvals": SENDING_APPROVAL["approvals"]},
                }))
                page = await ctx.new_page()
                page.on("pageerror", lambda e: errors.append(str(e)[:160]))
                await page.goto(f"{base}/index.html")
                await page.wait_for_timeout(900)
                await page.fill("#task-input", "Open Telegram and tell John Doe I am running late")
                await page.click("#run-btn")
                await page.wait_for_timeout(1200)
                card = page.locator("#approval-card")
                if await card.is_visible():
                    await card.screenshot(path=str(out / f"approval-send-{theme}.png"))
                else:
                    errors.append("the approval card did not appear, so no picture of it was taken")
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
