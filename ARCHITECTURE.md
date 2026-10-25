# Architecture

```
┌──────────────────────── Electron desktop app (desktop/) ────────────────────────┐
│  Renderer (sandboxed page)        Preload bridge          Main process          │
│  index.html / app.js  ──IPC──▶  window.claw.api()  ──▶  backend.js             │
│  no Node, strict CSP              5 functions only        • spawns Python       │
│                                                           • holds session token │
│                                                           • route allowlist     │
└───────────────────────────────────────────────────────────────┬─────────────────┘
                                         HTTP 127.0.0.1:<random port>, X-Claw-Token
┌──────────────────────────── Python agent runtime (backend/claw/) ───────────────┐
│ api/app.py      FastAPI routes, token + Host guard, error format                │
│ config.py       Settings schema, validation → plain-English errors, atomic save │
│ agent/          planner.py (task → validated plan), schemas.py (step states)    │
│ models/         base.py interface · ollama.py · openai_compat.py (llama.cpp)    │
│ permissions/    policy.py: risk levels, allow/ask/deny, folder scoping          │
│ storage/db.py   SQLite: tasks + audit events                                    │
│ logging_setup   JSON logs with secret redaction                                 │
└───────────────────────────────────────────────────────────────┬─────────────────┘
                                         HTTP localhost
                              Ollama (:11434)  or  llama-server (:8080)
```

## Key decisions
- **Custom shell over forking Interpreter Workstation or UI-TARS Desktop** — see `docs/REPO_AUDIT.md`.
- **Electron (not Tauri)** — no Rust toolchain needed; Node 22 is the only JS requirement.
- **Python backend** — Playwright, pywinauto and pyautogui (Batches 2–3) are Python libraries,
  so the agent runtime lives where the automation libraries are.
- **No LangGraph / LiteLLM** — the execution loop will be a small explicit state machine with
  hard step and retry limits; two thin adapters cover the local servers. A cloud adapter can
  be added later by implementing `ModelAdapter`.
- **Structured output** — plans are requested with a JSON schema (Ollama `format`,
  llama-server `response_format.schema`) and always re-validated with Pydantic; one
  corrective retry, then an honest failure.

## Step lifecycle
`proposed → approved | denied → attempted → verified | failed` (also `skipped`).
Batch 1 produces only `proposed` steps. The UI labels every step "Not run".

## Data locations
`%APPDATA%\OluwaseunClaw\` → `settings.json`, `claw.db`, `logs\claw.log` (override with `CLAW_DATA_DIR`).

## Planned additions
- `backend/claw/browser/` — Playwright session, dedicated profile, tools (Batch 2)
- `backend/claw/computer/` — pywinauto UIA, screenshots, input (Batch 3)
- `backend/claw/tools/` — tool registry with schemas and risk levels (Batch 2)
- `backend/claw/agent/executor.py` — bounded execute/verify/replan loop (Batch 2–4)
