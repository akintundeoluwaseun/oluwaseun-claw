"""Local HTTP API used by the desktop shell.

Security model:
- Binds to 127.0.0.1 only (see claw.main).
- Every request except /health must carry the per-launch session token in the
  `X-Claw-Token` header. The desktop main process generates the token and is
  the only holder; the web renderer never sees it.
- Host header must be a loopback name, which blocks DNS-rebinding pages.
"""

from __future__ import annotations

import hmac
import logging
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from claw import __version__
from claw.agent.planner import PlanningFailed, make_plan
from claw.agent.schemas import PlanRequest, TaskStatus
from claw.config import ConfigError, ModelSettings, Settings, SettingsStore, describe_validation_error
from claw.logging_setup import log_event
from claw.models.base import ModelError
from claw.models.registry import build_adapter
from claw.permissions.policy import PermissionPolicy
from claw.storage.db import Database

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

    def policy(self) -> PermissionPolicy:
        return PermissionPolicy(self.settings.permissions.modes, self.settings.permissions.authorized_folders)


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
    try:
        state.settings = store.load()
    except ConfigError as exc:
        state.settings_error = exc
        log.warning("settings invalid; running with defaults until fixed", extra={"fields": {"problems": exc.problems}})

    app = FastAPI(title="Oluwaseun Claw backend", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
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

    @app.get("/settings")
    async def get_settings():
        err = state.settings_error
        return {
            "settings": state.settings.model_dump(mode="json"),
            "error": {"message": err.message, "details": err.problems} if err else None,
            "data_dir": str(state.data_dir),
        }

    @app.put("/settings")
    async def put_settings(request: Request):
        try:
            raw = await request.json()
        except ValueError:
            return error_response(400, "bad_json", "The settings sent were not valid JSON.")
        try:
            new_settings = SettingsStore.validate(raw)
        except ConfigError as exc:
            return error_response(422, "invalid_settings", exc.message, details=exc.problems)
        store.save(new_settings)
        state.settings = new_settings
        state.settings_error = None
        log_event(log, "settings saved", provider=new_settings.model.provider, model=new_settings.model.model)
        return {"settings": new_settings.model_dump(mode="json"), "error": None, "data_dir": str(state.data_dir)}

    @app.get("/models/status")
    async def model_status():
        status = await build_adapter(state.settings.model).status()
        return status.model_dump()

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

        model_settings = state.settings.model
        task_id = state.db.create_task(req.task, model_settings.model or None)
        state.db.add_event(task_id, "requested", {"task": req.task})
        state.db.update_task(task_id, status=TaskStatus.PLANNING)
        adapter = build_adapter(model_settings)
        try:
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
