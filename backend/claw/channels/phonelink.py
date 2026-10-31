"""The S-CLAW phone app, over the home Wi-Fi.

Off unless switched on in Settings > Phone. When on, a second small web server listens on
the computer's local network address (port 47820 by default) and serves the phone app and
its API. Every request needs the pairing key that was in the QR code, compared in constant
time, and only private network addresses (home Wi-Fi) are answered - never the internet.

The phone gets the same things the app has: chats, starting a task, following it, and
answering Claw's questions (Allow / Don't allow). Everything that asks first still asks.
"""

from __future__ import annotations

import hmac
import ipaddress
import secrets
import socket
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from claw.agent.runner import TaskBusy

MOBILE = Path(__file__).resolve().parent / "mobile"
ACTIVE = {"created", "planning", "running", "awaiting_approval"}


def new_key() -> str:
    return secrets.token_urlsafe(32)


def lan_address() -> str:
    """This computer's address on the local network (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.0.1", 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def pairing_url(port: int, key: str) -> str:
    return f"http://{lan_address()}:{port}/#k={key}"


def qr_svg(text: str) -> str:
    import segno

    # A data: URI the page can show as an image. (svg_inline leaves out the xmlns, which
    # is fine inside HTML but makes the same SVG a broken image - caught on screenshot.)
    return segno.make(text, error="m").svg_data_uri(scale=5, dark="#111111", light="#ffffff")


def _private(host: str | None) -> bool:
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def create_link_app(state) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def no(code: int, msg: str):
        return JSONResponse({"error": msg}, status_code=code)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not _private(request.client.host if request.client else None):
            return no(403, "Only the home network can use this.")
        if request.url.path.startswith("/api/"):
            want = state.settings.phone.link_key
            got = request.headers.get("x-claw-key", "")
            if not want or not hmac.compare_digest(got, want):
                return no(401, "This phone is not paired. Scan the QR code in S-CLAW again.")
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    @app.get("/")
    async def page():
        return FileResponse(MOBILE / "index.html", media_type="text/html")

    @app.get("/{name}")
    async def asset(name: str):
        if name not in ("app.js", "app.css", "manifest.webmanifest", "icon.svg"):
            return no(404, "Not found")
        return FileResponse(MOBILE / name)

    @app.get("/api/hello")
    async def hello():
        b = state.runner
        return {"ok": True, "busy": b.busy, "computer": socket.gethostname()}

    @app.get("/api/chats")
    async def chats():
        return {"chats": [{"id": t["id"], "thread_id": t["thread_id"], "title": t.get("title") or t["task_text"],
                           "status": t["status"], "messages": t.get("messages", 1), "created_at": t["created_at"]}
                          for t in state.db.list_threads(30, None)]}

    @app.get("/api/chat/{thread_id}")
    async def chat(thread_id: str):
        if not thread_id.isalnum() or len(thread_id) != 32:
            return no(422, "Bad chat id.")
        tasks = state.db.thread_tasks(thread_id)
        return {"title": state.db.thread_title(thread_id),
                "messages": [{"id": t["id"], "text": t["task_text"], "status": t["status"],
                              "answer": (t.get("result") or {}).get("final_answer") or t.get("error") or ""} for t in tasks]}

    @app.post("/api/run")
    async def run(request: Request):
        body = await request.json()
        text = str(body.get("task", "")).strip()
        thread = body.get("thread_id") or None
        if not 3 <= len(text) <= 4000:
            return no(422, "Say what Claw should do.")
        if thread is not None and (not isinstance(thread, str) or len(thread) != 32 or not thread.isalnum()):
            return no(422, "Bad chat id.")
        try:
            tid = state.runner.start(text, thread_id=thread)
        except TaskBusy:
            return no(409, "Claw is busy with another task.")
        return {"id": tid, "thread_id": state.db.get_task(tid)["thread_id"]}

    @app.get("/api/task/{task_id}")
    async def task(task_id: str):
        t = state.db.get_task(task_id) if task_id.isalnum() and len(task_id) == 32 else None
        if t is None:
            return no(404, "No such task.")
        steps = [e for e in state.db.get_events(task_id, 0) if e["kind"] in ("verified", "done", "failed", "denied", "rejected")]
        return {"status": t["status"], "active": t["status"] in ACTIVE,
                "answer": (t.get("result") or {}).get("final_answer") or "", "error": t.get("error") or "",
                "steps": [{"kind": e["kind"], "tool": (e.get("data") or {}).get("tool", ""),
                           "detail": str((e.get("data") or {}).get("detail", ""))[:200]} for e in steps][-12:],
                "approvals": [{"id": a["id"], "description": a.get("description", ""), "tool": a.get("tool", ""),
                               "args": a.get("args", {})} for a in state.runner.pending() if a["task_id"] == task_id]}

    @app.post("/api/approve/{approval_id}")
    async def approve(approval_id: str, request: Request):
        body = await request.json()
        if not isinstance(body.get("approve"), bool):
            return no(422, "Send approve true or false.")
        return {"ok": state.runner.answer(approval_id, body["approve"])}

    @app.post("/api/stop")
    async def stop():
        r = state.runner
        return {"ok": bool(r.busy and r.cancel(r.current_id))}

    return app
