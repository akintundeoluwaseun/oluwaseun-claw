# Project status — Oluwaseun Claw

**Current batch:** Batch 3 complete in the build workspace (Linux). The Windows UI
Automation driver and the live Google service have not been run yet.
**Next batch:** Batch 4 — multi-step autonomy and product features.
**Version:** 0.3.0 · **Last updated:** 2026-10-25

## Completed
- **Batch 1:** audit, architecture, backend foundation, Electron shell, scripts, tests.
- **Batch 2:** tool system, browser control (Playwright, own profile), history search,
  save links, executor loop with approvals/stop/limits, background runner.
- **Interface + background mode:** premium redesign (light/dark), quick bar
  (Ctrl+Shift+Space), tray icon, notifications, start with Windows, keep awake, close to tray.
- **Brain:** welcome screen with one choice — Online (user's free Google key, model picked
  automatically, falls back on daily limits) or Offline (hardware-based model choice, automatic
  download with progress, unload when idle). Key encrypted with DPAPI.
- **Batch 3:** Windows UI Automation driver, app launcher (system tools refused), 12 desktop
  tools with before/after checks, screenshots, screen reading via the brain, click-at fallback,
  3 read-only file tools, consequential-label escalation, stop shortcut Ctrl+Alt+X.

## What the app can do today
Take a task in English (main window or quick bar), plan it, and carry it out step by step in a
browser and in Windows apps, reading files in allowed folders, asking before anything that
changes things, and reporting exactly what was done and checked. Runs in the background.

## Remaining work
Batches 4–5 (see `IMPLEMENTATION_PLAN.md`).

## Known issues / limits
- **Not yet run on Windows 10.** The UI Automation driver is written against pywinauto 0.6.9's
  source but unexecuted; see the checklist in `docs/DESKTOP.md`. PowerShell scripts not run.
- **Not yet run against Google's live API** (no internet in the build workspace). Request format
  follows Google's docs; Claw falls back to the older JSON-schema field if the newer is rejected.
- **No real model has driven a task yet**; all runs used scripted stand-ins.
- Offline mode needs the Ollama engine installed separately until Batch 5 bundles it.
- Desktop steps can't run on a locked screen; admin windows, UAC and games are not supported.
- Live DuckDuckGo/Bing parsing, Edge as controlled browser, Chrome/Edge history: unverified.
- "Plan only" cannot be cancelled; one task at a time.
- 28 tools in the prompt is heavy for the smallest offline models.

## Exact startup commands (Windows 10, developers)
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # once
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```
Then choose Online (paste a free key from aistudio.google.com/apikey) or Offline.

## Next action
Batch 4, step 1: replanning when a step fails twice, plus document/spreadsheet tools (save a
report with sources, create a spreadsheet from collected data).
