"""Runs one task at a time in the background, with approvals and cancellation."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from claw.agent.executor import run_agent
from claw.agent.planner import PlanningFailed, make_plan
from claw.logging_setup import log_event
from claw.models.base import ModelError
from claw.tools.base import ToolContext

if TYPE_CHECKING:
    from claw.api.app import AppState

log = logging.getLogger("claw.runner")


class TaskBusy(Exception):
    pass


@dataclass
class PendingApproval:
    id: str
    task_id: str
    payload: dict[str, Any]
    future: asyncio.Future


class TaskRunner:
    def __init__(self, state: "AppState"):
        self.state = state
        self.current_id: str | None = None
        self._task: asyncio.Task | None = None
        self.approvals: dict[str, PendingApproval] = {}

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, task_text: str) -> str:
        if self.busy:
            raise TaskBusy()
        db = self.state.db
        task_id = db.create_task(task_text, self.state.model_label())
        db.add_event(task_id, "requested_task", {"task": task_text})
        self.current_id = task_id
        self._task = asyncio.create_task(self._run(task_id, task_text), name=f"claw-task-{task_id}")
        return task_id

    def cancel(self, task_id: str) -> bool:
        if not self.busy or self.current_id != task_id:
            return False
        for appr in list(self.approvals.values()):
            if appr.task_id == task_id and not appr.future.done():
                appr.future.set_result(False)
        self._task.cancel()
        return True

    def answer(self, approval_id: str, approve: bool) -> bool:
        appr = self.approvals.get(approval_id)
        if appr is None or appr.future.done():
            return False
        appr.future.set_result(bool(approve))
        return True

    def pending(self) -> list[dict[str, Any]]:
        return [{"id": a.id, "task_id": a.task_id, **a.payload} for a in self.approvals.values() if not a.future.done()]

    async def wait(self) -> None:
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self, task_id: str, task_text: str) -> None:
        state, db = self.state, self.state.db
        settings = state.settings

        def emit(kind: str, data: dict[str, Any]) -> None:
            db.add_event(task_id, kind, data)

        async def request_approval(payload: dict[str, Any]) -> bool | None:
            approval_id = uuid.uuid4().hex
            future = asyncio.get_running_loop().create_future()
            self.approvals[approval_id] = PendingApproval(approval_id, task_id, payload, future)
            db.update_task(task_id, status="awaiting_approval")
            emit("approval_requested", {"approval_id": approval_id, **payload})
            try:
                return await asyncio.wait_for(future, timeout=settings.agent.approval_timeout_s)
            except TimeoutError:
                return None
            finally:
                self.approvals.pop(approval_id, None)
                db.update_task(task_id, status="running")

        state.browser.reset_task_state()
        state.desktop.reset_task_state()
        ctx = ToolContext(
            settings=settings, policy=state.policy(), data_dir=state.data_dir, browser=state.browser, task_id=task_id,
            desktop=state.desktop, vision=state.vision_fn(),
        )
        try:
            adapter = state.think_adapter()
            db.update_task(task_id, status="planning")
            emit("model_call", {"provider": adapter.provider, "model": adapter.model, "purpose": "plan"})
            plan = await make_plan(task_text, adapter, state.policy())
            plan_json = plan.model_dump(mode="json")
            db.update_task(task_id, status="running", plan=plan_json)
            emit("planned", {"steps": len(plan.steps)})
            plan_text = "\n".join(f"{s.index}. {s.description}" for s in plan.steps)
            outcome = await run_agent(task_text, plan_text, adapter, state.registry, ctx, emit, request_approval)
            db.update_task(task_id, status=outcome.status, error=outcome.error, result=outcome.summary())
            emit("task_" + outcome.status, {"error": outcome.error} if outcome.error else {})
            log_event(log, "task ended", task_id=task_id, status=outcome.status, steps=len(outcome.steps))
        except asyncio.CancelledError:
            db.update_task(task_id, status="cancelled", error="Stopped by you.")
            emit("task_cancelled", {})
            raise
        except PlanningFailed as exc:
            db.update_task(task_id, status="failed", error=exc.message)
            emit("failed", {"message": exc.message, "details": exc.details})
        except ModelError as exc:
            db.update_task(task_id, status="failed", error=exc.message)
            emit("failed", {"message": exc.message, "hint": exc.hint})
        except Exception:  # noqa: BLE001 — record, never crash the server
            log.exception("task crashed")
            db.update_task(task_id, status="failed", error="An unexpected error stopped the task. See the log file.")
            emit("failed", {"message": "unexpected error"})
