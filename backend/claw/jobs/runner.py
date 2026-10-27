"""Running scheduled jobs — carefully, and only while S-CLAW is open.

The honest shape of this feature, stated once so nothing in the UI has to
pretend otherwise:

**There is no 24/7.** A job runs when S-CLAW is running. A computer that is off,
asleep or logged out does nothing, and no schedule changes that. Saying
otherwise would be the easiest lie in the product.

**Nobody is watching, so nothing may ask.** A job runs under
`PermissionPolicy.unattended()`: every "ask" becomes "no", and destructive work
is refused outright. A job that needs a person stops and says so, rather than
waiting ten minutes for an approval that will never come.

**A person at the keyboard comes first.** If a task is already running, the job
is skipped — recorded as skipped, not as run, so it is still due the moment the
person stops.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from claw.agent.runner import TaskBusy
from claw.jobs.schedule import BadSchedule, Schedule, is_due

log = logging.getLogger(__name__)
#: How often to look. A job's schedule is in minutes, so this is plenty.
TICK_SECONDS = 30


def _moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def due_jobs(jobs: list[dict], now: datetime) -> list[dict]:
    """Which enabled jobs should run now. Pure, so the arithmetic can be tested."""
    out = []
    for job in jobs:
        if not job.get("enabled"):
            continue
        try:
            schedule = Schedule.parse(job["kind"], job.get("minutes"), job.get("at", ""))
        except BadSchedule:
            continue                      # a job nobody can read is never run
        if is_due(schedule, _moment(job.get("last_run")), now):
            out.append(job)
    return out


class JobRunner:
    """Ticks, and starts one due job at a time."""

    def __init__(self, state):
        self.state = state

    async def tick(self, now: datetime | None = None) -> str | None:
        now = now or datetime.now(timezone.utc)
        db = self.state.db
        due = await asyncio.to_thread(db.jobs, True)
        due = due_jobs(due, now)
        if not due:
            return None
        job = due[0]                       # one at a time; the rest are due next tick
        if self.state.runner.busy:
            await asyncio.to_thread(db.record_job_run, job["id"], "skipped",
                                    "S-CLAW was busy with something else.")
            return None
        try:
            task_id = self.state.runner.start(job["task_text"], unattended=True)
        except TaskBusy:
            await asyncio.to_thread(db.record_job_run, job["id"], "skipped",
                                    "S-CLAW was busy with something else.")
            return None
        await asyncio.to_thread(db.record_job_run, job["id"], "started", "", task_id)
        log.info("scheduled job started", extra={"fields": {"job": job["name"], "task": task_id}})
        # The outcome is recorded when the task finishes, by watch().
        asyncio.create_task(self.watch(job["id"], task_id))
        return task_id

    async def watch(self, job_id: str, task_id: str) -> None:
        """Wait for the job's task to end, then write down what actually happened."""
        await self.state.runner.wait()
        db = self.state.db
        task = await asyncio.to_thread(db.get_task, task_id)
        status = (task or {}).get("status") or "unknown"
        detail = (task or {}).get("error") or ""
        if not detail and task and task.get("result"):
            detail = str(task["result"].get("final_answer") or "")[:500]
        if status == "stopped" and not detail:
            detail = "It needed your approval, and nobody was there to give it."
        await asyncio.to_thread(db.record_job_run, job_id, status, detail, task_id)

    async def loop(self) -> None:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - one bad job must not stop the rest
                log.warning("scheduled job tick failed", exc_info=True)
