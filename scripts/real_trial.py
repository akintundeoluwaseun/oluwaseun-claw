"""Real trial: run everyday tasks through S-CLAW's own API with the REAL brain on a real Windows machine,
approving every request like a user would, and write down exactly what happened.

    python scripts/real_trial.py --port 18765 --token T --out report-dir [--tasks-file tasks.json]

The backend must already be running (python -m claw.main --port ...). Nothing here is simulated:
the model's replies, the desktop, the browser and the files are all real. The report lists, per task,
the final status, every step with its outcome and detail, errors, the model's answer, and timings.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_TASKS = [
    "Open Notepad, type 'S-CLAW desktop-control test', save it as claw-test.txt in Documents, reopen it, and verify the exact contents.",
    "Search the web for free open-source video editing software, open a good result, and save its title and URL.",
    "Read invoice.pdf in my Documents folder and tell me the total amount due.",
    "Find all PDF files in my Documents folder.",
    "What windows are open right now?",
    "Make a promotional flyer for my software TechDesk and save it in Documents.",
    "Copy sales.csv from Documents into a new folder called Backup.",
    "Create a spreadsheet of five Nigerian states and their capitals and save it in Documents.",
    "Open WhatsApp and tell me which chats have unread messages.",
    "What is on my calendar today?",
]


class Api:
    def __init__(self, port: int, token: str):
        self.base = f"http://127.0.0.1:{port}"
        self.token = token

    def call(self, method: str, path: str, body=None, timeout=60):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"X-Claw-Token": self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"null")
            except ValueError:
                return e.code, None


def run_task(api: Api, text: str, limit_s: int) -> dict:
    t0 = time.time()
    code, body = api.call("POST", "/tasks/run", {"task": text})
    if code not in (200, 201, 202) or not (body or {}).get("id"):
        return {"task": text, "status": "could_not_start", "http": code, "error": body, "seconds": 0}
    tid = body["id"]
    after, events, approvals_answered = 0, [], []
    status = "created"
    while time.time() - t0 < limit_s:
        code, st = api.call("GET", f"/tasks/{tid}/events?after={after}")
        if code != 200:
            time.sleep(2)
            continue
        for e in st["events"]:
            events.append(e)
            after = max(after, e["id"])
        for a in st.get("approvals") or []:
            api.call("POST", f"/approvals/{a['id']}", {"approve": True})
            approvals_answered.append({"tool": a.get("tool"), "risk": a.get("risk"), "args": a.get("args")})
        status = st["status"]
        if status not in ("created", "planning", "running", "awaiting_approval"):
            break
        time.sleep(1.5)
    else:
        api.call("POST", f"/tasks/{tid}/cancel")
        status = "timed_out_by_trial"
    code, task = api.call("GET", f"/tasks/{tid}")
    result = (task or {}).get("result") or {}
    steps = [{k: s.get(k) for k in ("tool", "args", "outcome", "detail")} for s in result.get("steps", [])]
    model_events = [e for e in events if e["kind"] in ("model_reply_rejected", "replanned", "model_error", "failed", "rejected", "stopped", "pushed_back", "started_for_brain", "tool_name_corrected", "skill_used")]
    return {
        "task": text, "id": tid, "status": status, "seconds": round(time.time() - t0, 1),
        "error": (task or {}).get("error"), "answer": result.get("final_answer"), "counts": result.get("counts"),
        "steps": steps, "approvals": approvals_answered, "warnings": result.get("warnings"),
        "plan": ((task or {}).get("plan") or {}).get("steps"),
        "problem_events": [{"kind": e["kind"], "data": e.get("data")} for e in model_events][:30],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tasks-file")
    ap.add_argument("--per-task-seconds", type=int, default=900)
    a = ap.parse_args()
    api = Api(a.port, a.token)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tasks = json.loads(Path(a.tasks_file).read_text()) if a.tasks_file else DEFAULT_TASKS
    report = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "brain": api.call("GET", "/brain")[1],
              "settings": api.call("GET", "/settings")[1], "tasks": []}
    for i, t in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] {t}", flush=True)
        r = run_task(api, t, a.per_task_seconds)
        report["tasks"].append(r)
        print(f"    -> {r['status']} in {r['seconds']}s; steps: "
              + ", ".join(f"{s['tool']}={s['outcome']}" for s in r.get("steps") or []) + (f"; error: {r['error']}" if r.get("error") else ""),
              flush=True)
        (out / "trial.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    lines = ["# Real trial", ""]
    for r in report["tasks"]:
        lines.append(f"## {r['task']}\n- status: **{r['status']}** ({r['seconds']} s)")
        if r.get("error"):
            lines.append(f"- error: {r['error']}")
        for s in r.get("steps") or []:
            lines.append(f"- step `{s['tool']}` → {s['outcome']}: {str(s['detail'])[:300]}")
        if r.get("answer"):
            lines.append(f"- answer: {str(r['answer'])[:500]}")
        for p in r.get("problem_events") or []:
            lines.append(f"- event {p['kind']}: {json.dumps(p['data'], default=str)[:300]}")
        lines.append("")
    (out / "trial.md").write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
