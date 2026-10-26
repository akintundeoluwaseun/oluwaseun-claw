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
import hmac
import logging
from contextlib import asynccontextmanager
import platform
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
from claw.agent.schemas import PlanRequest, TaskStatus
from claw.browser.session import BrowserSession
from claw.computer.driver import DesktopSession, default_driver
from claw.config import ConfigError, ModelSettings, Settings, SettingsStore, describe_validation_error
from claw.logging_setup import log_event
from claw.documents.pdf_pipeline import PdfPipeline
from claw.documents.service import DocumentService
from claw.models.base import ModelAdapter, ModelError, ModelNotFound, ModelStatus
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
        if ms.mode in ("custom", "cloud"):
            # Cloud: a hosted model over the internet. No brain is downloaded, started or needed.
            return build_adapter(ms)
        return await self.brain.adapter(ms.selected, ms.request_timeout_s, ms.temperature)

    def vision_fn(self, adapter: ModelAdapter):
        """Reads screenshots with the same brain when it has a vision file; otherwise None."""
        return adapter.see if getattr(adapter, "vision", False) else None

    def model_label(self) -> str | None:
        ms = self.settings.model
        if ms.mode in ("custom", "cloud"):
            return ms.model or None
        m = self.brain.active_model(ms.selected)
        return m.name if m else None

    def policy(self) -> PermissionPolicy:
        return PermissionPolicy(
            self.settings.permissions.modes, self.settings.permissions.authorized_folders,
            self.docs.opened_paths if self.docs else None,
        )


def error_response(status: int, code: str, message: str, hint: str = "", details: list[str] | None = None):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "hint": hint, "details": details or []}},
    )


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
    except ConfigError as exc:
        state.settings_error = exc
        log.warning("settings invalid; running with defaults until fixed", extra={"fields": {"problems": exc.problems}})
    state.browser = BrowserSession(data_dir, lambda: state.settings.browser)
    state.docs = DocumentService(PdfPipeline(data_dir / "documents", language=state.settings.documents.ocr_language))
    state.runner = TaskRunner(state)
    interrupted = state.db.mark_interrupted()
    if interrupted:
        log_event(log, "marked unfinished tasks as interrupted", count=interrupted)

    from claw.integrations.whatsapp import CheckStore, check_whatsapp

    wa = {"seq": 0, "result": None, "lock": asyncio.Lock(), "next_auto": 0.0}

    async def run_whatsapp_check(manual: bool) -> dict:
        async with wa["lock"]:
            ms = state.settings.messages
            result = await check_whatsapp(state.desktop.call, state.desktop.driver, CheckStore(state.data_dir),
                                          with_previews=ms.show_previews, open_if_needed=manual)
            wa["seq"] += 1
            wa["result"] = {**result.as_dict(), "manual": manual}
            log_event(log, "whatsapp checked", state=result.state, unread=len(result.unread), manual=manual)
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

    @asynccontextmanager
    async def lifespan(_app):
        watcher = asyncio.create_task(idle_watch())
        wa_task = asyncio.create_task(whatsapp_watch())
        yield
        watcher.cancel()
        wa_task.cancel()
        await state.brain.shutdown()
        if state.runner.busy:
            state.runner.cancel(state.runner.current_id)
            await state.runner.wait()
        await state.browser.close()
        state.desktop.close()
        state.db.close()

    app = FastAPI(
        title="Oluwaseun Claw backend", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
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
        return data

    def _restore_key(raw: dict, current) -> dict:
        """A page that did not change the key sends the placeholder back; keep what is stored."""
        model = raw.get("model")
        if isinstance(model, dict):
            model.pop("api_key_set", None)
            if model.get("api_key") == KEY_KEPT:
                model["api_key"] = current.model.api_key
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
        store.save(new_settings)
        state.settings = new_settings
        state.settings_error = None
        # mode and model only: the key is a credential and never reaches the log.
        log_event(log, "settings saved", mode=new_settings.model.mode, model=new_settings.model.model)
        return {"settings": _public_settings(new_settings), "error": None, "data_dir": str(state.data_dir)}

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
            status = ModelStatus(
                server_reachable=info["engine"]["available"], model_available=info["ready"], provider="builtin",
                base_url="", model=active["name"] if active else "", message=message,
            )
            return {**status.model_dump(), "mode": "builtin"}
        try:
            adapter = await state.think_adapter()
        except ModelError as exc:
            status = ModelStatus(server_reachable=False, model_available=False, provider=ms.mode, base_url="", model="",
                                 message=f"{exc.message} {exc.hint}".strip())
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
            candidate = ModelSettings.model_validate(await request.json())
        except ValidationError as exc:
            return error_response(422, "invalid_settings", "Model settings are not valid.", details=describe_validation_error(exc))
        except ValueError:
            return error_response(400, "bad_json", "The request was not valid JSON.")
        status = await build_adapter(candidate).status()
        return status.model_dump()

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

        task_id = state.db.create_task(req.task, state.model_label())
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
            task_id = state.runner.start(req.task)
        except TaskBusy:
            return error_response(409, "busy", "Another task is still running.", "Wait for it to finish or stop it first.")
        return JSONResponse(status_code=202, content={"id": task_id})

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

    @app.get("/runner")
    async def runner_status():
        return {"busy": state.runner.busy, "current_id": state.runner.current_id if state.runner.busy else None}

    @app.get("/tasks")
    async def list_tasks(q: str | None = None, limit: int = 50):
        return {"tasks": state.db.list_tasks(limit=limit, query=q)}

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
