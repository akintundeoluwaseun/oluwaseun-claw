"""Runs one task at a time in the background, with approvals and cancellation."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from claw.agent.executor import run_agent
from claw.agent.planner import PlanningFailed, make_plan
from claw.agent.titles import clean_model_title, fallback_title
from claw.logging_setup import log_event
from claw.models.base import ModelError
#: What to assume for a model whose window Claw cannot read. Conservative on
#: purpose: trimming a little early costs context, trimming too late costs the run.
HOSTED_CONTEXT_TOKENS = 32768
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
        #: True while a scheduled job is running, so nothing waits for a person.
        self.unattended = False

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, task_text: str, unattended: bool = False, thread_id: str | None = None) -> str:
        """Run a task. `unattended` means nobody is watching — a scheduled job.

        It is not a convenience flag: it changes the permission policy, because
        an approval cannot be given by an empty room.
        """
        if self.busy:
            raise TaskBusy()
        db = self.state.db
        self.unattended = unattended
        if thread_id and not db.thread_exists(thread_id):
            thread_id = None  # a chat that was deleted: start a new one rather than fail
        earlier = db.thread_tasks(thread_id) if thread_id else []
        task_id = db.create_task(task_text, self.state.model_label(), thread_id)
        thread = thread_id or task_id
        if not earlier:
            db.set_thread_title(thread, fallback_title(task_text))  # replaced by the model's title once it has planned
        db.add_event(task_id, "requested_task", {"task": task_text, "unattended": unattended, "thread_id": thread})
        self.current_id = task_id
        self._task = asyncio.create_task(self._run(task_id, task_text, thread, conversation_context(earlier), not earlier),
                                         name=f"claw-task-{task_id}")
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

    async def _run(self, task_id: str, task_text: str, thread_id: str | None = None, context: str = "",
                   first_in_chat: bool = True) -> None:
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
        try:
            adapter = await state.think_adapter()
            ctx = ToolContext(
                settings=settings, policy=state.policy().unattended() if self.unattended else state.policy(), data_dir=state.data_dir, browser=state.browser, task_id=task_id,
                desktop=state.desktop, vision=state.vision_fn(adapter), llm=adapter, docs=state.docs.pipeline,
                ask_user=request_approval, recent_tasks=db.list_tasks, memory_store=db,
            )
            db.update_task(task_id, status="planning")
            emit("model_call", {"provider": adapter.provider, "model": adapter.model, "purpose": "plan"})
            # Earlier messages of this chat are given as context, so "now save it as a PDF" works.
            request = f"{task_text}\n\n{context}" if context else task_text
            plan = await make_plan(request, adapter, state.policy())
            if first_in_chat and thread_id and (title := clean_model_title(plan.title)):
                db.set_thread_title(thread_id, title)
            plan_json = plan.model_dump(mode="json")
            db.update_task(task_id, status="running", plan=plan_json)
            emit("planned", {"steps": len(plan.steps)})
            plan_text = "\n".join(f"{s.index}. {s.description}" for s in plan.steps)
            caps = {s.capability.value for s in plan.steps} - {"reasoning"}
            # Ask the server what it will accept, and only fall back to what was
            # requested. The built-in engine starts llama-server with -c
            # <ctx_size>, but llama.cpp clamps that DOWN to the model's trained
            # context: a model trained at 2048 gives a 2048-token server however
            # large the flag was, and nothing says so. Budgeting against the
            # requested figure then builds a prompt the server rejects outright,
            # which a person sees as the task failing rather than as a long
            # conversation being trimmed. A hosted model usually will not answer
            # /props, and gets the conservative default.
            asked = (state.brain.engine.ctx_size if settings.model.mode == "builtin"
                     else HOSTED_CONTEXT_TOKENS)
            window = asked
            reported = None
            if hasattr(adapter, "context_window"):
                try:
                    reported = await adapter.context_window()
                except Exception:  # never let a window probe fail the task
                    reported = None
            if reported:
                window = reported
                if reported != asked:
                    log_event(log, "model window differs from the one requested",
                              task_id=task_id, asked=asked, actual=reported)
            outcome = await run_agent(request, plan_text, adapter, state.registry, ctx, emit,
                                      request_approval, caps or None, window_tokens=window)
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


def conversation_context(earlier: list[dict[str, Any]], max_chars: int = 1500) -> str:
    """The last few messages of a chat, so a follow-up can refer to them. Bounded: small models have small windows."""
    if not earlier:
        return ""
    lines = []
    for t in earlier[-3:]:
        result = t.get("result") or {}
        reply = result.get("final_answer") or (f"(failed: {t['error']})" if t.get("error") else f"({t['status']})")
        lines.append(f"- You were asked: {t['task_text'][:300]}\n  Result: {str(reply)[:300]}")
    text = "Earlier in this conversation:\n" + "\n".join(lines)
    return text[-max_chars:]
