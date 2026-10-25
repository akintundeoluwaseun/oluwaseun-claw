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
│ agent/          planner.py · executor.py (bounded loop) · runner.py (background,│
│                 approvals, stop) · schemas.py (step states)                     │
│ tools/          base.py (spec, schema, risk, precheck) · browser_tools · file   │
│ browser/        session.py (Playwright, own profile) · extract.py · history.py  │
│ models/         base.py interface · ollama.py · openai_compat.py (llama.cpp)    │
│ permissions/    policy.py: risk levels, allow/ask/deny, folder scoping          │
│ storage/db.py   SQLite: tasks + audit events                                    │
│ logging_setup   JSON logs with secret redaction                                 │
└───────────────────────────────────────────────────────────────┬─────────────────┘
                    HTTP localhost                         Playwright (CDP)
       Ollama (:11434) or llama-server (:8080)         Edge / Chrome / Chromium
                                                       (dedicated profile)
```

## How a task runs (Batch 2)
1. `POST /tasks/run` → runner creates the task and returns at once.
2. Planner asks the model for a step plan (shown to the user as guidance).
3. Executor loop, one step at a time: model returns `{"action":"tool","tool":…,"args":…}` →
   tool exists? → arguments valid? → same action repeated? → pre-check →
   permission (allow / ask → approval card / deny) → run with timeout (one retry if transient) →
   record verified / done-but-unchecked / failed → observation back to the model, with page text
   inside `<untrusted>` tags.
4. Stops on: model says finish, permission refused, Stop pressed, 3 failures in a row,
   repeated action, step limit, model error.
5. The outcome (counts per result) is built from recorded steps; the model's summary is shown
   separately and labelled as the agent's own words.

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
Plan steps: `proposed`. Executed steps are recorded as events:
`requested → (awaiting_approval → approved | denied) → attempted → verified | done_unverified | failed`,
or `rejected` (unknown tool / invalid arguments / failed pre-check).

## Data locations
`%APPDATA%\OluwaseunClaw\` → `settings.json`, `claw.db`, `logs\claw.log`, `browser-profile\`
(override with `CLAW_DATA_DIR`).

## Planned additions
- `backend/claw/computer/` — pywinauto UIA, screenshots, input (Batch 3)
- Replanning, file/document/spreadsheet tools, stronger injection defences (Batch 4)
