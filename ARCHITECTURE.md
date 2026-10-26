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
│ computer/       driver.py (interface, 1 COM thread) · windows_uia.py ·          │
│                 launcher.py (Start menu, system tools refused)                  │
│ models/         auto.py + hardware.py (built-in brain manager)                  │
│ documents/      readers.py (PDF, Word, Excel, text)                             │
│ tools/          document_tools.py (reports, spreadsheets, text, edit+backup)    │
│ models/         base.py interface · ollama.py · openai_compat.py (llama.cpp)    │
│ permissions/    policy.py: risk levels, allow/ask/deny, folder scoping          │
│ storage/db.py   SQLite: tasks + audit events                                    │
│ logging_setup   JSON logs with secret redaction                                 │
└───────────────────────────────────────────────────────────────┬─────────────────┘
        HTTP localhost (built-in brain)         Playwright        UI Automation
   engine (Ollama now, bundled llama.cpp     Edge/Chrome        Windows apps
   in release); model picked for this PC     (own profile)      (pywinauto)
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

## Brain selection
`settings.model.mode`: `builtin` (default) → ModelManager (hardware → role models → engine,
keep_alive 2m, num_thread = cores − 1/2); `custom` → developer adapter. Vision
(`describe_screen`) uses the built-in seeing model when the computer can hold one.

## Task memory and honesty (Batch 4)
Each task has a `TaskMemory`: text read (web, files, apps), files opened, files produced, and
taint flags. Reports may cite only opened sources; spreadsheets are checked against the text
read; injection-like content raises later actions to "ask". After 2 failed steps the model is
asked for a diagnosis and new plan (max 2). Outcome = counts from recorded steps + files +
warnings; the model's own summary is shown separately.

## Desktop safety
Effective risk per action (`ToolSpec.risk_for`): clicking something labelled Send/Delete/Buy…
becomes destructive. Pre-checks run before approval. Before/after snapshots decide "checked".

## Planned additions
- Installer bundling Python runtime and Ollama; signing (Batch 5)
