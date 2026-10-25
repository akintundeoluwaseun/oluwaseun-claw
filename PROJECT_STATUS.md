# Project status — Oluwaseun Claw

**Current batch:** Batch 2 complete in the build workspace (scripted model, Linux, Chromium).
Not yet run with a real local model or on Windows 10.
**Next batch:** Batch 3 — Desktop control.
**Last updated:** 2026-10-25

## Completed
- **Batch 1:** audit, architecture, backend foundation, Electron shell, scripts, tests.
- **Batch 2:**
  - Tool system: 13 tools, each with a schema, risk level, argument validation, optional pre-check.
  - Browser (Playwright): dedicated profile; Edge by default on Windows; open, search, read page,
    extract links, follow link, click button, tabs.
  - Browser-history search: titles/addresses/time only; always needs your approval or is off.
  - `save_links`: Markdown file in an authorized folder; never overwrites; refuses links not seen in the task.
  - Executor loop with step limit, failure limit, repeat detection, per-step timeout, one retry for
    transient errors, approval waiting, untrusted-content wrapping, and an outcome assembled from recorded steps.
  - Background task runner: Run, Stop, approvals over the API; unfinished tasks marked "interrupted" on restart.
  - UI: Run task / Plan only, live activity list, approval card, Stop button, outcome summary,
    browser and limits settings.
  - Database schema v2 with automatic migration from v1.

## What the app can do today
Take a task in English, plan it, and carry out browser steps one at a time with permission checks.
It asks before saving files, clicking form buttons, or reading browser history. It can save
collected links to a file and reports exactly which steps were done, checked, failed or refused.

## Remaining work
Batches 3–5 (see `IMPLEMENTATION_PLAN.md`).

## Known issues / limits
- **No real model has driven the agent yet.** All runs used a scripted test-double model.
  How well qwen2.5/qwen3 follow the action format is unknown until tested on real hardware.
- **Live DuckDuckGo/Bing result parsing is unverified** (no internet in the workspace). A generic
  link fallback exists if their page layout differs.
- **Chrome/Edge history on Windows is unverified.** History search is verified only on the agent's own
  Chromium profile.
- **Edge as the default browser is unverified** (Playwright `channel="msedge"`); tested with Chromium 153.
- Never run on Windows 10; PowerShell scripts not executed.
- Planning ("Plan only") is still one blocking request with no cancel; "Run task" can be stopped.
- One task runs at a time.

## Exact startup commands (Windows 10)
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # once
ollama pull qwen2.5:7b                                       # once
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```
In Settings: Test connection → choose model → add a folder for saved files → Save.

## Next action
On a Windows 10 laptop with Ollama: run setup + check, then run the Batch 2 acceptance tasks with a
real model (search + save links; find a page in history) and record results in `TEST_RESULTS.md`.
Then start Batch 3, step 1: pywinauto UI Automation adapter for listing and focusing windows.
