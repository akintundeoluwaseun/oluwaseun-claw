"""Local HTTP API used by the desktop shell.

Security model:
- Binds to 127.0.0.1 only (see claw.main).
- Every request except /health must carry the per-launch session token in the
  `X-Claw-Token` header. The desktop main process generates the token and is
  the only holder; the web renderer never sees it.
- Host header must be a loopback name, which blocks DNS-rebinding pages.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hmac
import logging
import os
from contextlib import asynccontextmanager
import platform
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from claw import __version__
from claw.agent.planner import PlanningFailed, make_plan
from claw.agent.runner import TaskBusy, TaskRunner
from claw.agent.titles import clean_model_title, fallback_title
from claw.agent.schemas import PlanRequest, TaskStatus
from claw.brief import assemble, window
from claw.browser.session import BrowserSession
from claw.calendar.reminders import phrase
from claw.calendar.store import LocalCalendars
from claw.computer.driver import DesktopSession, default_driver
from claw.config import ConfigError, ModelSettings, Settings, SettingsStore, describe_validation_error, starter_folders
from claw.edition import current as current_edition
from claw.jobs.runner import JobRunner
from claw.jobs.schedule import BadSchedule, Schedule, next_run
from claw.logging_setup import log_event
from claw.documents.pdf_pipeline import PdfPipeline
from claw.documents.service import DocumentService
from claw.models.base import (ChatMessage, ModelAdapter, ModelAuthFailed, ModelError, ModelNotFound,
                              ModelRateLimited, ModelStatus)
from claw.models.claw_service import ClawServiceUnconfigured, build_service_adapter
from claw.models.registry import build_adapter
from claw.runtime.brain import Brain
from claw.runtime.hub import DownloadError
from claw.speech.audio import AudioError
from claw.speech.base import SpeechUnavailable
from claw.speech.service import SpeechService, default_store
from claw.runtime.store import ModelStore
from claw.permissions.policy import PermissionPolicy
from claw.storage.db import Database
from claw.tools.base import ToolError, ToolRegistry
from claw.tools.registry import build_registry

log = logging.getLogger("claw.api")

# Short, and answerable by any model: the point is that tokens come back at all.
SELFTEST_PROMPT = "Reply with one word: ready"

TOKEN_HEADER = "x-claw-token"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


@dataclass
class AppState:
    data_dir: Path
    token: str
    store: SettingsStore
    db: Database
    settings: Settings = field(default_factory=Settings)
    settings_error: ConfigError | None = None
    registry: ToolRegistry = field(default_factory=build_registry)
    browser: BrowserSession | None = None
    runner: TaskRunner | None = None
    brain: Brain | None = None
    speech: SpeechService | None = None
    desktop: DesktopSession | None = None
    docs: DocumentService | None = None

    async def think_adapter(self) -> ModelAdapter:
        """The model that plans and decides steps."""
        ms = self.settings.model
        if ms.mode == "service":
            # Claw Online. The service proposes actions and reads results; this computer
            # still validates and executes every one of them.
            return build_service_adapter(current_edition(), ms.request_timeout_s, ms.temperature, ms.model)
        if ms.mode in ("custom", "cloud"):
            # Cloud: a hosted model over the internet. No brain is downloaded, started or needed.
            return build_adapter(ms)
        allowed, why = current_edition().allows_mode("builtin")
        if not allowed:
            raise ModelNotFound(why, "Settings → Claw's brain.")
        # A brain on this computer has no network to wait for, only a CPU. Its first reply
        # in a task reads the whole tool list, which took up to two minutes for the 2B brain
        # on GitHub's Windows machine, so the 120 s meant for servers cut it off mid-thought.
        return await self.brain.adapter(ms.selected, max(ms.request_timeout_s, LOCAL_REPLY_TIMEOUT_S), ms.temperature)

    def vision_fn(self, adapter: ModelAdapter):
        """Reads screenshots with the same brain when it has a vision file; otherwise None."""
        return adapter.see if getattr(adapter, "vision", False) else None

    def model_label(self) -> str | None:
        ms = self.settings.model
        if ms.mode == "service":
            from claw.models.claw_service import DEFAULT_SERVICE_MODEL

            return ms.model or DEFAULT_SERVICE_MODEL
        if ms.mode in ("custom", "cloud"):
            return ms.model or None
        m = self.brain.active_model(ms.selected)
        return m.name if m else None

    def policy(self) -> PermissionPolicy:
        return PermissionPolicy(
            self.settings.permissions.modes, self.settings.permissions.authorized_folders,
            self.docs.opened_paths if self.docs else None,
        )


def _job_moment(value):
    """A stored timestamp as an aware datetime, or None."""
    if not value:
        return None
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def error_response(status: int, code: str, message: str, hint: str = "", details: list[str] | None = None):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "hint": hint, "details": details or []}},
    )


LOCAL_REPLY_TIMEOUT_S = 600.0


def create_app(data_dir: Path, token: str) -> FastAPI:
    if len(token) < 32:
        raise ValueError("session token must be at least 32 characters")
    store = SettingsStore(data_dir)
    state = AppState(data_dir=data_dir, token=token, store=store, db=Database(data_dir / "claw.db"))
    state.desktop = DesktopSession(default_driver())
    state.brain = Brain(ModelStore(data_dir))
    state.speech = SpeechService(default_store(data_dir),
                                 hardware_ram_gb=getattr(state.brain.hardware, "total_ram_gb", None))
    try:
        state.settings = store.load()
        perms = state.settings.permissions
        if not perms.starter_folders_added and not os.environ.get("CLAW_NO_STARTER_FOLDERS"):
            perms.authorized_folders = perms.authorized_folders or starter_folders()
            perms.starter_folders_added = True
            store.save(state.settings)
            log_event(log, "starter folders added", count=len(perms.authorized_folders))
    except ConfigError as exc:
        state.settings_error = exc
        log.warning("settings invalid; running with defaults until fixed", extra={"fields": {"problems": exc.problems}})
    state.browser = BrowserSession(data_dir, lambda: state.settings.browser)
    state.docs = DocumentService(PdfPipeline(data_dir / "documents", language=state.settings.documents.ocr_language))
    state.runner = TaskRunner(state)
    interrupted = state.db.mark_interrupted()
    if interrupted:
        log_event(log, "marked unfinished tasks as interrupted", count=interrupted)

    from claw.integrations.standing_reply import NotAuthorised, StandingReply
    from claw.integrations.whatsapp import CheckStore, check_whatsapp

    wa = {"seq": 0, "result": None, "lock": asyncio.Lock(), "next_auto": 0.0, "drafts": []}
    standing = StandingReply(data_dir / "standing-reply.json")

    async def run_whatsapp_check(manual: bool) -> dict:
        async with wa["lock"]:
            ms = state.settings.messages
            result = await check_whatsapp(state.desktop.call, state.desktop.driver, CheckStore(state.data_dir),
                                          with_previews=ms.show_previews, open_if_needed=manual)
            wa["seq"] += 1
            wa["result"] = {**result.as_dict(), "manual": manual}
            log_event(log, "whatsapp checked", state=result.state, unread=len(result.unread), manual=manual)
            # A standing reply prepares drafts here and nowhere else. It cannot
            # send: the drafts wait for the person, and expiry is checked again
            # inside drafts_for, so a window that closed produces nothing.
            if result.state == "ok":
                try:
                    fresh = await asyncio.to_thread(
                        standing.drafts_for, [(c.name, c.unread) for c in result.unread])
                except NotAuthorised:
                    fresh = []
                if fresh:
                    wa["drafts"] = [d.as_dict() for d in fresh] + wa["drafts"][:20]
                    log_event(log, "standing reply drafted", drafts=len(fresh))
            return wa["result"]

    async def whatsapp_watch():
        """Optional background check. Only when the user chose "Go ahead" for reading messages and an
        interval; never while a task is using the desktop; never opens WhatsApp by itself."""
        while True:
            await asyncio.sleep(30)
            ms = state.settings.messages
            if not ms.check_every_minutes or ms.whatsapp_read != "allow" or state.runner.busy:
                continue
            if time.time() < wa["next_auto"]:
                continue
            wa["next_auto"] = time.time() + ms.check_every_minutes * 60
            try:
                await run_whatsapp_check(manual=False)
            except Exception:  # noqa: BLE001 — a failed background check must never stop the loop
                log.warning("background WhatsApp check failed", exc_info=True)

    async def idle_watch():
        """Stop the engine when Claw has been quiet for a while, to give the memory back."""
        while True:
            await asyncio.sleep(30)
            if state.runner.busy:
                state.brain.touch()
                continue
            await state.brain.engine.stop_if_idle(state.settings.model.idle_unload_minutes * 60)

    phone: dict = {"bridge": None, "task": None}

    async def stop_phone():
        if phone["task"]:
            phone["task"].cancel()
        if phone["bridge"]:
            await phone["bridge"].client.close()
        phone.update(bridge=None, task=None)

    link: dict = {"server": None, "task": None}

    async def stop_link():
        if link["server"]:
            link["server"].should_exit = True
            try:
                await asyncio.wait_for(link["task"], 5)
            except Exception:  # noqa: BLE001
                link["task"].cancel()
        link.update(server=None, task=None)

    async def restart_link():
        await stop_link()
        ps = state.settings.phone
        if not (ps.link_enabled and ps.link_key):
            return
        import uvicorn

        from claw.channels.phonelink import create_link_app

        cfg = uvicorn.Config(create_link_app(state), host="0.0.0.0", port=ps.link_port, log_level="warning",  # noqa: S104 - home network only; the app refuses others
                             access_log=False, lifespan="off")
        server = uvicorn.Server(cfg)
        server.install_signal_handlers = lambda: None
        link.update(server=server, task=asyncio.create_task(server.serve()))

    async def restart_phone():
        await restart_link()
        await stop_phone()
        ps = state.settings.phone
        if not (ps.enabled and ps.telegram_token):
            return
        from claw.channels.bridge import PhoneBridge
        from claw.channels.telegram import TelegramClient, TelegramError

        try:
            client = TelegramClient(ps.telegram_token, base=os.environ.get("CLAW_TELEGRAM_API", "https://api.telegram.org"))
        except TelegramError as exc:
            log_event(log, "phone not started", reason=str(exc))
            return
        phone["bridge"] = PhoneBridge(state, client)
        phone["task"] = asyncio.create_task(phone["bridge"].run())

    @asynccontextmanager
    async def lifespan(_app):
        watcher = asyncio.create_task(idle_watch())
        wa_task = asyncio.create_task(whatsapp_watch())
        jobs_task = asyncio.create_task(JobRunner(state).loop())
        await restart_phone()
        yield
        await stop_phone()
        await stop_link()
        watcher.cancel()
        wa_task.cancel()
        jobs_task.cancel()
        await state.brain.shutdown()
        if state.runner.busy:
            state.runner.cancel(state.runner.current_id)
            await state.runner.wait()
        await state.browser.close()
        state.desktop.close()
        state.db.close()

    app = FastAPI(
        title="S-CLAW backend", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.claw = state

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
        if host not in _LOOPBACK_HOSTS:
            return error_response(403, "bad_host", "Requests must come from this computer.")
        if request.url.path != "/health":
            supplied = request.headers.get(TOKEN_HEADER, "")
            if not hmac.compare_digest(supplied.encode(), state.token.encode()):
                return error_response(401, "unauthorized", "Missing or wrong session token.")
        return await call_next(request)

    @app.exception_handler(ModelError)
    async def _model_error(_: Request, exc: ModelError):
        return error_response(502, "model_error", exc.message, exc.hint)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        log.exception("unhandled error")
        return error_response(500, "internal_error", "Something went wrong inside the agent.", "Details are in the log file.")

    @app.get("/health")
    async def health():
        db_ok = True
        try:
            state.db.schema_version()
        except Exception:  # noqa: BLE001 — health must never raise
            db_ok = False
        return {
            "status": "ok" if db_ok else "degraded",
            "version": __version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "db_ok": db_ok,
            "settings_ok": state.settings_error is None,
        }

    KEY_KEPT = "__keep__"  # the page sends this back to mean "leave the saved key alone"

    def _public_settings(settings) -> dict:
        """Settings as the page may see them: the API key is never sent out in full."""
        data = settings.model_dump(mode="json")
        key = settings.model.api_key
        data["model"]["api_key"] = (KEY_KEPT if key else "")
        data["model"]["api_key_set"] = bool(key)
        data["phone"]["telegram_token"] = KEY_KEPT if settings.phone.telegram_token else ""
        data["phone"]["link_key"] = KEY_KEPT if settings.phone.link_key else ""
        return data

    def _restore_key(raw: dict, current) -> dict:
        """A page that did not change the key sends the placeholder back; keep what is stored."""
        model = raw.get("model")
        if isinstance(model, dict):
            model.pop("api_key_set", None)
            if model.get("api_key") == KEY_KEPT:
                model["api_key"] = current.model.api_key
        phone = raw.get("phone")
        if isinstance(phone, dict):
            if phone.get("telegram_token") == KEY_KEPT:
                phone["telegram_token"] = current.phone.telegram_token
            # The Wi-Fi key is made here, never typed or changed by the page.
            phone["link_key"] = current.phone.link_key
            # Pairing is done by the code on the phone, never by the page.
            phone["paired_chat_id"] = current.phone.paired_chat_id if phone.get("telegram_token") == current.phone.telegram_token else None
        return raw

    @app.get("/settings")
    async def get_settings():
        err = state.settings_error
        return {
            "settings": _public_settings(state.settings),
            "error": {"message": err.message, "details": err.problems} if err else None,
            "data_dir": str(state.data_dir),
        }

    @app.put("/settings")
    async def put_settings(request: Request):
        try:
            raw = await request.json()
        except ValueError:
            return error_response(400, "bad_json", "The settings sent were not valid JSON.")
        if isinstance(raw, dict):
            raw = _restore_key(raw, state.settings)
        try:
            new_settings = SettingsStore.validate(raw)
        except ConfigError as exc:
            return error_response(422, "invalid_settings", exc.message, details=exc.problems)
        # One codebase, two editions: the edition decides which ways of thinking exist
        # here. Refusing the setting is the point - silently using another one is how
        # an "offline" install ends up sending the user's documents to a server.
        allowed, why = current_edition().allows_mode(new_settings.model.mode)
        if not allowed:
            return error_response(409, "wrong_edition", why)
        if new_settings.phone.link_enabled and not new_settings.phone.link_key:
            from claw.channels.phonelink import new_key

            new_settings.phone.link_key = new_key()
        phone_changed = new_settings.phone != state.settings.phone
        store.save(new_settings)
        state.settings = new_settings
        state.settings_error = None
        if phone_changed:
            await restart_phone()
        # mode and model only: the key is a credential and never reaches the log.
        log_event(log, "settings saved", mode=new_settings.model.mode, model=new_settings.model.model)
        return {"settings": _public_settings(new_settings), "error": None, "data_dir": str(state.data_dir)}

    @app.get("/edition")
    async def edition():
        """Which edition this install is, and what it may do.

        The interface uses this to hide what does not exist here rather than offering
        a brain download in Claw Online or a key field where no key is needed.
        """
        ed = current_edition()
        body = ed.as_dict()
        body["modes"] = {m: {"allowed": ed.allows_mode(m)[0], "why_not": ed.allows_mode(m)[1]}
                         for m in ("builtin", "service", "cloud", "custom")}
        return body

    @app.get("/models/status")
    async def model_status():
        ms = state.settings.model
        if ms.mode == "builtin":
            info = state.brain.summary(ms.selected)
            active = info["active"]
            eng = info["engine"]
            message = (
                ("Ready" if eng["state"] == "ready" else "Ready (starts when needed)") if info["ready"]
                else " ".join(state.brain.not_ready(ms.selected))
            )
            if info["ready"] and eng["state"] == "failed":
                # The brain is installed but its last start failed. Saying "Ready" here is
                # what made a model look fine in Settings while every task errored.
                reason = "engine_failed"
                message = f"The brain is installed but did not start: {eng['message']}"
            elif info["ready"]:
                reason = "ok"
            elif not eng["available"]:
                reason = "unreachable"          # the llama.cpp engine itself is not there
            elif state.brain.download.status in ("resolving", "downloading", "verifying"):
                reason = "not_configured"       # a brain is on its way
            else:
                reason = "model_missing"        # engine fine, no brain on this computer
            status = ModelStatus(
                server_reachable=info["engine"]["available"], model_available=info["ready"] and reason != "engine_failed",
                provider="builtin",
                base_url="", model=active["name"] if active else "", message=message, reason=reason,
            )
            return {**status.model_dump(), "mode": "builtin"}
        try:
            adapter = await state.think_adapter()
        except ClawServiceUnconfigured as exc:
            # A Claw Online build with no service in it. Not a network problem, and not
            # something a retry fixes, so it must not read as "unreachable".
            status = ModelStatus(server_reachable=False, model_available=False, provider=ms.mode,
                                 base_url="", model="", reason="not_configured",
                                 message=f"{exc.message} {exc.hint}".strip())
            return {**status.model_dump(), "mode": ms.mode}
        except ModelError as exc:
            status = ModelStatus(server_reachable=False, model_available=False, provider=ms.mode, base_url="", model="",
                                 reason="error", message=f"{exc.message} {exc.hint}".strip())
            return {**status.model_dump(), "mode": ms.mode}
        return {**(await adapter.status()).model_dump(), "mode": ms.mode}

    @app.get("/brain")
    async def get_brain():
        return {"mode": state.settings.model.mode, **state.brain.summary(state.settings.model.selected)}

    # ---------- voice (offline speech recognition) ----------
    @app.get("/speech")
    async def speech_status():
        return state.speech.status(state.settings)

    @app.post("/speech/transcribe")
    async def speech_transcribe(request: Request):
        """WAV bytes in, recognised words out. The audio is not stored."""
        wav = await request.body()
        try:
            result = await state.speech.transcribe(wav, state.settings)
        except AudioError as exc:
            return error_response(400, "audio", str(exc))
        except SpeechUnavailable as exc:
            return error_response(409, "speech_unavailable", exc.message, hint=exc.hint)
        # The words are the user's, not an instruction to act on: the bar shows them
        # and the user submits. Marked untrusted for anything downstream.
        return {"text": result.text, "untrusted": True, **result.as_dict()}

    @app.post("/speech/stream/start")
    async def speech_stream_start(request: Request):
        rate = (await _body(request)).get("sample_rate")
        try:
            return await state.speech.start_stream(state.settings, int(rate or 16000))
        except (TypeError, ValueError):
            return error_response(400, "audio", "The microphone's sample rate was not understood.")
        except AudioError as exc:
            return error_response(400, "audio", str(exc))
        except SpeechUnavailable as exc:
            return error_response(409, "speech_unavailable", exc.message, hint=exc.hint)

    @app.post("/speech/stream/{stream_id}/chunk")
    async def speech_stream_chunk(stream_id: str, request: Request):
        """Raw 16-bit PCM in, the words so far out. Called every few hundred milliseconds."""
        try:
            return await state.speech.feed_stream(stream_id, await request.body())
        except AudioError as exc:
            return error_response(400, "audio", str(exc))
        except SpeechUnavailable as exc:
            return error_response(409, "speech_unavailable", exc.message, hint=exc.hint)

    @app.post("/speech/stream/{stream_id}/finish")
    async def speech_stream_finish(stream_id: str):
        try:
            result = await state.speech.finish_stream(stream_id)
        except SpeechUnavailable as exc:
            return error_response(409, "speech_unavailable", exc.message, hint=exc.hint)
        return {"text": result.text, "untrusted": True, **result.as_dict()}

    @app.post("/speech/stream/cancel")
    async def speech_stream_cancel():
        state.speech.cancel_stream()
        return {"cancelled": True}

    @app.post("/speech/models/download")
    async def speech_download(request: Request):
        model_id = (await _body(request)).get("id")
        try:
            state.speech.models.start_download(str(model_id))
        except DownloadError as exc:
            return error_response(409, "download", str(exc.args[0] if exc.args else exc))
        return state.speech.status(state.settings)

    @app.post("/speech/models/download/cancel")
    async def speech_download_cancel():
        state.speech.models.cancel()
        return state.speech.status(state.settings)

    @app.post("/speech/models/remove")
    async def speech_remove(request: Request):
        model_id = str((await _body(request)).get("id") or "")
        if state.speech.models.get_installed(model_id) is None and state.speech.models.store.load(model_id) is None:
            return error_response(404, "not_found", "That voice model is not installed.")
        state.speech.unload()
        return {"removed": state.speech.models.remove(model_id), **state.speech.status(state.settings)}

    async def _body(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def _save_model_settings(**changes) -> None:
        new = state.settings.model_copy(deep=True)
        for k, v in changes.items():
            setattr(new.model, k, v)
        store.save(new)
        state.settings = new

    @app.post("/brain/download")
    async def brain_download(request: Request):
        allowed, why = current_edition().allows_mode("builtin")
        if not allowed:
            return error_response(409, "wrong_edition", why)
        entry_id = (await _body(request)).get("id")
        try:
            state.brain.start_download(str(entry_id))
        except ValueError as exc:
            return error_response(409, "download", str(exc))
        return state.brain.summary(state.settings.model.selected)

    @app.post("/brain/download/cancel")
    async def brain_download_cancel():
        return {"cancelled": state.brain.cancel_download()}

    @app.post("/brain/select")
    async def brain_select(request: Request):
        model_id = (await _body(request)).get("id")
        if model_id is not None and state.brain.store.get(str(model_id)) is None:
            return error_response(404, "not_found", "That brain is not installed.")
        _save_model_settings(selected=model_id, mode="builtin")
        await state.brain.engine.stop()  # next task starts the chosen brain
        return state.brain.summary(model_id)

    @app.post("/brain/remove")
    async def brain_remove(request: Request):
        model_id = str((await _body(request)).get("id") or "")
        active = state.brain.active_model(state.settings.model.selected)
        if active and active.id == model_id and state.runner.busy:
            return error_response(409, "busy", "Wait for the current task to finish first.")
        if active and active.id == model_id:
            await state.brain.engine.stop()
        try:
            note = state.brain.store.remove(model_id)
        except ValueError as exc:
            return error_response(409, "remove", str(exc))
        if state.settings.model.selected == model_id:
            _save_model_settings(selected=None)
        return {"message": note, **state.brain.summary(state.settings.model.selected)}

    @app.post("/brain/import")
    async def brain_import(request: Request):
        """Main-process only (path comes from the file dialog); not in the UI route allowlist."""
        body = await _body(request)
        try:
            m = state.brain.store.import_file(Path(str(body.get("path"))), Path(body["mmproj"]) if body.get("mmproj") else None)
        except ValueError as exc:
            return error_response(422, "import", str(exc))
        _save_model_settings(selected=m.id, mode="builtin")
        await state.brain.engine.stop()
        return state.brain.summary(m.id)

    @app.post("/brain/restart")
    async def brain_restart():
        await state.brain.engine.stop()
        try:
            await state.think_adapter()
        except ModelError as exc:
            return error_response(502, "engine", exc.message, exc.hint)
        return state.brain.summary(state.settings.model.selected)

    # ---------- Messages ----------
    @app.get("/messages/whatsapp")
    async def whatsapp_status():
        stored = CheckStore(state.data_dir).load()
        return {"seq": wa["seq"], "result": wa["result"], "last_check_at": stored.get("checked_at"),
                "last_attempt_at": stored.get("last_attempt"), "last_state": stored.get("last_state")}

    @app.post("/messages/whatsapp/check")
    async def whatsapp_check_now():
        """The user pressed "Check WhatsApp now": that click is their consent for this one check."""
        if state.settings.messages.whatsapp_read == "deny":
            return error_response(403, "denied", "Reading WhatsApp is set to Never in Settings.")
        if state.runner.busy:
            return error_response(409, "busy", "Claw is using the computer for a task. Check again when it finishes.")
        return await run_whatsapp_check(manual=True)

    # ---------- Documents ----------
    @app.post("/documents/open")
    async def documents_open(request: Request):
        """Main-process only (path comes from the file dialog); not in the UI route allowlist."""
        raw = (await _body(request)).get("path")
        if not isinstance(raw, str) or not raw:
            return error_response(422, "path", "No file was given.")
        path = Path(raw)
        if path.suffix.lower() not in (".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md", ".csv"):
            return error_response(422, "type", "Claw can open PDF, Word, Excel and text files.")
        try:
            job = state.docs.open(path)
        except ToolError as exc:
            return error_response(422, "open", exc.message)
        return job.status_dict()

    @app.get("/documents/{doc_id}")
    async def documents_get(doc_id: str, pages: int = 0):
        job = state.docs.get(doc_id)
        if job is None:
            return error_response(404, "not_found", "That document is not open.")
        return job.status_dict(with_pages=bool(pages))

    @app.get("/documents/{doc_id}/search")
    async def documents_search(doc_id: str, q: str = ""):
        job = state.docs.get(doc_id)
        if job is None or job.status != "done":
            return error_response(409, "not_ready", "The document isn't ready yet.")
        return {"hits": state.docs.search(job, q[:200])}

    @app.post("/documents/{doc_id}/cancel")
    async def documents_cancel(doc_id: str):
        job = state.docs.get(doc_id)
        if job is None:
            return error_response(404, "not_found", "That document is not open.")
        job.cancel.set()
        return {"ok": True}

    @app.post("/documents/{doc_id}/searchable")
    async def documents_searchable(doc_id: str, request: Request):
        """Main-process only: the output path comes from the Save dialog."""
        job = state.docs.get(doc_id)
        out = (await _body(request)).get("out")
        if job is None or job.result is None:
            return error_response(409, "not_ready", "Only a PDF that has finished reading can be saved as searchable.")
        if not isinstance(out, str) or not out.lower().endswith(".pdf"):
            return error_response(422, "out", "Choose where to save the PDF.")
        try:
            path = await asyncio.to_thread(state.docs.pipeline.searchable_pdf, Path(job.path), Path(out))
        except FileExistsError:
            return error_response(409, "exists", "A file with that name already exists. Choose another name.")
        except ToolError as exc:
            return error_response(422, "searchable", exc.message)
        return {"path": str(path)}

    @app.post("/models/probe")
    async def probe_models(request: Request):
        """Check an unsaved model configuration (used by Settings → Test connection)."""
        try:
            raw = await request.json()
            # Testing a connection without retyping the key: the page sends the placeholder
            # back, exactly as it does when saving, so resolve it to the stored one.
            if isinstance(raw, dict):
                raw = _restore_key({"model": raw}, state.settings)["model"]
            candidate = ModelSettings.model_validate(raw)
        except ValidationError as exc:
            return error_response(422, "invalid_settings", "Model settings are not valid.", details=describe_validation_error(exc))
        except ValueError:
            return error_response(400, "bad_json", "The request was not valid JSON.")
        # Only "custom" and "cloud" have an address to test. "builtin" thinks through
        # the managed brain and "service" through the address compiled into the
        # edition, so for those two the base_url in this request is never dialled
        # for real work - and must not be dialled here either. Building an adapter
        # from it regardless would make this endpoint the one place an arbitrary
        # host could be contacted while the saved mode is local, which is exactly
        # the thing the settings rule exists to prevent.
        if candidate.mode not in ("custom", "cloud"):
            return await model_status()
        status = await build_adapter(candidate).status()
        return status.model_dump()

    @app.post("/models/selftest")
    async def model_selftest(request: Request):
        """Send a real prompt and report what came back.

        /models/status and /models/probe only ask whether the server is there and
        whether it lists the model. Neither generates anything, so both can say
        "Ready" for a configuration that fails the moment a task starts. This one
        is the only check that proves the model actually answers.
        """
        ms = state.settings.model
        candidate = None
        try:
            raw = await request.json()
        except ValueError:
            raw = None                      # no body: test the configuration that is saved
        if isinstance(raw, dict) and raw:
            try:
                # Same placeholder dance as /models/probe: the page never holds the key.
                candidate = ModelSettings.model_validate(_restore_key({"model": raw}, state.settings)["model"])
            except ValidationError as exc:
                return error_response(422, "invalid_settings", "Model settings are not valid.",
                                      details=describe_validation_error(exc))
            ms = candidate
        base = {"mode": ms.mode, "model": (ms.model if candidate else state.model_label()) or ms.model or ""}
        started = time.perf_counter()
        try:
            adapter = build_adapter(candidate) if candidate and candidate.mode != "builtin" \
                else await state.think_adapter()
            reply = await adapter.chat([ChatMessage(role="user", content=SELFTEST_PROMPT)])
        except ModelAuthFailed as exc:
            return {**base, "ok": False, "reason": "auth_failed", "message": f"{exc.message} {exc.hint}".strip()}
        except ModelRateLimited as exc:
            return {**base, "ok": False, "reason": "rate_limited", "message": f"{exc.message} {exc.hint}".strip()}
        except ClawServiceUnconfigured as exc:
            return {**base, "ok": False, "reason": "not_configured", "message": f"{exc.message} {exc.hint}".strip()}
        except ModelNotFound as exc:
            return {**base, "ok": False, "reason": "model_missing", "message": f"{exc.message} {exc.hint}".strip()}
        except ModelError as exc:
            return {**base, "ok": False, "reason": "unreachable", "message": f"{exc.message} {exc.hint}".strip()}
        took = round((time.perf_counter() - started) * 1000)
        text = (reply or "").strip()
        log_event(log, "model self-test", mode=ms.mode, ok=bool(text), ms=took)
        return {
            **base, "ok": bool(text), "reason": "ok" if text else "error", "ms": took,
            # The model's own words, kept short. They are shown as a quotation, never
            # followed as instructions.
            "reply": text[:300],
            "message": f"The model replied in {took / 1000:.1f}s." if text
                       else "The model was reached but returned nothing.",
        }

    @app.post("/tasks/plan")
    async def plan_task(request: Request):
        try:
            req = PlanRequest.model_validate(await request.json())
        except ValidationError as exc:
            return error_response(422, "invalid_task", "The task could not be accepted.", details=describe_validation_error(exc))
        except ValueError:
            return error_response(400, "bad_json", "The request was not valid JSON.")
        if state.settings_error:
            return error_response(409, "settings_invalid", state.settings_error.message, "Fix them in Settings.", state.settings_error.problems)

        thread_ok = req.thread_id and state.db.thread_exists(req.thread_id)
        task_id = state.db.create_task(req.task, state.model_label(), req.thread_id if thread_ok else None)
        if not thread_ok:
            state.db.set_thread_title(task_id, fallback_title(req.task))
        state.db.add_event(task_id, "requested", {"task": req.task})
        state.db.update_task(task_id, status=TaskStatus.PLANNING)
        try:
            adapter = await state.think_adapter()
            state.db.add_event(task_id, "model_call", {"provider": adapter.provider, "model": adapter.model})
            plan = await make_plan(req.task, adapter, state.policy())
        except ModelError as exc:
            state.db.add_event(task_id, "failed", {"message": exc.message, "hint": exc.hint})
            state.db.update_task(task_id, status=TaskStatus.FAILED, error=exc.message)
            return _task_error(task_id, 502, "model_error", exc.message, exc.hint)
        except PlanningFailed as exc:
            state.db.add_event(task_id, "failed", {"message": exc.message, "details": exc.details})
            state.db.update_task(task_id, status=TaskStatus.FAILED, error=exc.message)
            return _task_error(task_id, 422, "planning_failed", exc.message, details=exc.details)
        plan_json = plan.model_dump(mode="json")
        state.db.add_event(task_id, "planned", {"steps": len(plan.steps)})
        state.db.update_task(task_id, status=TaskStatus.PLANNED, plan=plan_json)
        if not thread_ok and (title := clean_model_title(plan.title)):
            state.db.set_thread_title(task_id, title)
        log_event(log, "task planned", task_id=task_id, steps=len(plan.steps))
        return state.db.get_task(task_id)

    @app.post("/tasks/run")
    async def run_task(request: Request):
        try:
            req = PlanRequest.model_validate(await request.json())
        except ValidationError as exc:
            return error_response(422, "invalid_task", "The task could not be accepted.", details=describe_validation_error(exc))
        except ValueError:
            return error_response(400, "bad_json", "The request was not valid JSON.")
        if state.settings_error:
            return error_response(409, "settings_invalid", state.settings_error.message, "Fix them in Settings.", state.settings_error.problems)
        try:
            task_id = state.runner.start(req.task, thread_id=req.thread_id)
        except TaskBusy:
            return error_response(409, "busy", "Another task is still running.", "Wait for it to finish or stop it first.")
        row = state.db.get_task(task_id) or {}
        return JSONResponse(status_code=202, content={"id": task_id, "thread_id": row.get("thread_id") or task_id})

    @app.post("/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str):
        if not state.runner.cancel(task_id):
            return error_response(409, "not_running", "That task is not running.")
        return {"cancelling": True}

    @app.get("/tasks/{task_id}/events")
    async def task_events(task_id: str, after: int = 0):
        task = state.db.get_task(task_id)
        if task is None:
            return error_response(404, "not_found", "That task does not exist.")
        return {
            "status": task["status"],
            "events": state.db.get_events(task_id, after),
            "result": task["result"],
            "plan": task["plan"],
            "error": task["error"],
            "approvals": [a for a in state.runner.pending() if a["task_id"] == task_id],
        }

    # ---------- scheduled jobs ----------
    def job_view(job: dict) -> dict:
        """A job as the app shows it: schedule in words, when it next runs, what it did last."""
        try:
            schedule = Schedule.parse(job["kind"], job.get("minutes"), job.get("at", ""))
            words, upcoming = schedule.describe(), next_run(
                schedule, _job_moment(job.get("last_run")), datetime.now(timezone.utc))
        except BadSchedule as exc:
            words, upcoming = f"unreadable schedule ({exc})", None
        return {**job, "enabled": bool(job["enabled"]), "schedule": words,
                "next_run": upcoming.isoformat() if (upcoming and job["enabled"]) else None,
                # Said on every job, because a schedule implies a promise this cannot keep.
                "only_while_running": True}

    @app.get("/jobs")
    async def jobs_list():
        rows = await asyncio.to_thread(state.db.jobs)
        return {"jobs": [job_view(j) for j in rows],
                "note": "Jobs run only while S-CLAW is open. A computer that is off does nothing."}

    @app.post("/jobs")
    async def jobs_create(body: dict):
        name = str((body or {}).get("name", "")).strip()[:80]
        task_text = str((body or {}).get("task", "")).strip()[:2000]
        if not name or not task_text:
            return error_response(400, "bad_request", "A job needs a name and something to do.")
        try:
            schedule = Schedule.parse((body or {}).get("kind", ""), (body or {}).get("minutes"),
                                      (body or {}).get("at", ""))
        except BadSchedule as exc:
            return error_response(400, "bad_schedule", str(exc))
        job_id = await asyncio.to_thread(state.db.add_job, name, task_text, schedule.kind,
                                         schedule.minutes, schedule.at)
        log_event(log, "job created", job=name, schedule=schedule.describe())
        return job_view(await asyncio.to_thread(state.db.job, job_id))

    @app.post("/jobs/{job_id}/enabled")
    async def jobs_enable(job_id: str, body: dict):
        ok = await asyncio.to_thread(state.db.set_job_enabled, job_id, bool((body or {}).get("enabled")))
        if not ok:
            return error_response(404, "not_found", "There is no such job.")
        return job_view(await asyncio.to_thread(state.db.job, job_id))

    @app.delete("/jobs/{job_id}")
    async def jobs_delete(job_id: str):
        if not await asyncio.to_thread(state.db.delete_job, job_id):
            return error_response(404, "not_found", "There is no such job.")
        return {"deleted": job_id}

    @app.get("/jobs/{job_id}/runs")
    async def jobs_history(job_id: str):
        if await asyncio.to_thread(state.db.job, job_id) is None:
            return error_response(404, "not_found", "There is no such job.")
        return {"runs": await asyncio.to_thread(state.db.job_runs, job_id, 50)}

    @app.post("/jobs/{job_id}/run")
    async def jobs_run_now(job_id: str):
        """Run it now, watched — so approvals work normally and you can see it."""
        job = await asyncio.to_thread(state.db.job, job_id)
        if job is None:
            return error_response(404, "not_found", "There is no such job.")
        try:
            task_id = state.runner.start(job["task_text"])
        except TaskBusy:
            return error_response(409, "busy", "S-CLAW is already doing something.")
        await asyncio.to_thread(state.db.record_job_run, job_id, "started", "you ran it", task_id)
        return {"task_id": task_id}

    # ---------- memory ----------
    # Everything S-CLAW remembers is visible here, removable one at a time or
    # all at once, and exportable. A memory the person cannot see is a memory
    # they cannot correct.
    @app.get("/memory")
    async def memory_list(query: str = "", kind: str = ""):
        rows = await asyncio.to_thread(state.db.memories, query or None, kind or None, 500)
        return {"memories": rows, "kinds": sorted({r["kind"] for r in rows})}

    @app.delete("/memory/{memory_id}")
    async def memory_forget(memory_id: str):
        gone = await asyncio.to_thread(state.db.forget, memory_id)
        if gone is None:
            return error_response(404, "not_found", "That memory is not there.")
        log_event(log, "memory forgotten", kind=gone["kind"])
        return {"forgotten": {"id": gone["id"], "kind": gone["kind"], "subject": gone["subject"]}}

    @app.post("/memory/forget-all")
    async def memory_forget_all(body: dict | None = None):
        kind = (body or {}).get("kind") or None
        removed = await asyncio.to_thread(state.db.forget_all, kind)
        log_event(log, "memory cleared", kind=kind or "all", removed=removed)
        return {"removed": removed}

    @app.get("/memory/export")
    async def memory_export():
        """Everything remembered, as plain data the person can keep."""
        rows = await asyncio.to_thread(state.db.memories, None, None, 1000)
        return {"exported_at": datetime.now(timezone.utc).isoformat(),
                "app": "S-CLAW", "memories": rows}

    @app.get("/brief")
    async def brief():
        """Today, assembled. The same thing the daily_brief tool returns."""
        now = datetime.now(timezone.utc)
        store = LocalCalendars(state.data_dir / "calendars")
        start, end = window(now)
        events = await asyncio.to_thread(store.between, start, end, None)
        tasks = await asyncio.to_thread(state.db.list_tasks, 50)
        return assemble(events, tasks, now).as_dict()

    # ---------- standing reply (drafts only; nothing here can send) ----------
    @app.get("/standing-reply")
    async def standing_status():
        return {**standing.status(), "drafts": wa["drafts"],
                "sends": False,
                "note": "S-CLAW prepares these replies. You send them."}

    @app.post("/standing-reply")
    async def standing_start(body: dict):
        try:
            hours = float((body or {}).get("hours", 0))
        except (TypeError, ValueError):
            return error_response(400, "bad_request", "Say how many hours, as a number.")
        window = (wa.get("result") or {}).get("window_title") or ""
        try:
            auth = await asyncio.to_thread(
                standing.authorise, str((body or {}).get("message", "")), hours,
                account_hint=window, only_chats=(body or {}).get("only_chats") or [])
        except ValueError as exc:
            return error_response(400, "bad_request", str(exc))
        log_event(log, "standing reply authorised", minutes=auth.minutes_left())
        return {**standing.status(), "drafts": wa["drafts"], "sends": False}

    @app.delete("/standing-reply")
    async def standing_stop():
        stopped = await asyncio.to_thread(standing.stop)
        wa["drafts"] = []
        log_event(log, "standing reply stopped", was_running=stopped)
        return {**standing.status(), "drafts": [], "sends": False}

    # ---------- calendar reminders ----------
    # The app polls this; it does not push. A reminder is only ever shown once:
    # the app says what it showed, and that is recorded beside the calendars.
    @app.get("/calendar/due")
    async def calendar_due():
        store = LocalCalendars(state.data_dir / "calendars")
        items = await asyncio.to_thread(store.due, datetime.now(timezone.utc))
        return {"due": [{**item.as_dict(), "when": phrase(item)} for item in items]}

    @app.post("/calendar/due/seen")
    async def calendar_seen(body: dict):
        uids = body.get("uids") if isinstance(body, dict) else None
        if not isinstance(uids, list) or not all(isinstance(u, str) for u in uids):
            return error_response(400, "bad_request", "Send a list of event ids as 'uids'.")
        store = LocalCalendars(state.data_dir / "calendars")
        marked = await asyncio.to_thread(store.mark_shown, uids[:200])
        return {"marked": marked}

    @app.get("/approvals")
    async def approvals():
        return {"approvals": state.runner.pending()}

    @app.post("/approvals/{approval_id}")
    async def answer_approval(approval_id: str, request: Request):
        try:
            body = await request.json()
        except ValueError:
            return error_response(400, "bad_json", "The request was not valid JSON.")
        if not isinstance(body, dict) or not isinstance(body.get("approve"), bool):
            return error_response(422, "invalid", "Send {\"approve\": true} or {\"approve\": false}.")
        if not state.runner.answer(approval_id, body["approve"]):
            return error_response(404, "not_found", "That approval request is no longer waiting.")
        return {"ok": True}

    @app.get("/phone")
    async def phone_status():
        b = phone["bridge"]
        ps = state.settings.phone
        return {"enabled": ps.enabled, "token_set": bool(ps.telegram_token), "paired": ps.paired_chat_id is not None,
                "status": b.status if b else ("off" if not ps.enabled else "not started"), "bot": b.bot_name if b else "",
                "code": b.code if b and b.code and time.time() < b.code_until else None}

    @app.post("/phone/pair")
    async def phone_pair():
        b = phone["bridge"]
        if b is None:
            return error_response(409, "phone_off", "Turn on phone control and save a bot token first.")
        return {"code": b.new_code(), "bot": b.bot_name, "seconds": 600}

    @app.get("/phone/link")
    async def phone_link():
        from claw.channels.phonelink import pairing_url, qr_svg

        ps = state.settings.phone
        on = bool(ps.link_enabled and ps.link_key and link["server"] is not None)
        url = pairing_url(ps.link_port, ps.link_key) if on else ""
        return {"enabled": ps.link_enabled, "running": on, "url": url, "qr": qr_svg(url) if url else "",
                "port": ps.link_port}

    @app.post("/phone/link/new-key")
    async def phone_link_key():
        """A new pairing key: phones paired before stop working until they scan again."""
        from claw.channels.phonelink import new_key

        s = state.settings
        s.phone.link_key = new_key()
        store.save(s)
        await restart_link()
        return {"ok": True}

    @app.post("/phone/unpair")
    async def phone_unpair():
        s = state.settings
        s.phone.paired_chat_id = None
        store.save(s)
        return {"ok": True}

    @app.get("/runner")
    async def runner_status():
        return {"busy": state.runner.busy, "current_id": state.runner.current_id if state.runner.busy else None}

    @app.get("/tasks")
    async def list_tasks(q: str | None = None, limit: int = 50, thread: str | None = None):
        """The history: one entry per chat (its latest message and title). With ?thread=, that chat's messages."""
        if thread is not None:
            if not re.fullmatch(r"[0-9a-f]{32}", thread):
                return error_response(422, "thread", "That is not a chat id.")
            return {"tasks": state.db.thread_tasks(thread), "title": state.db.thread_title(thread)}
        return {"tasks": state.db.list_threads(limit=limit, query=q)}

    @app.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        task = state.db.get_task(task_id)
        if task is None:
            return error_response(404, "not_found", "That task does not exist.")
        return task

    return app


def _task_error(task_id: str, status: int, code: str, message: str, hint: str = "", details: list[str] | None = None):
    resp = error_response(status, code, message, hint, details)
    resp.headers["x-claw-task-id"] = task_id
    return resp
