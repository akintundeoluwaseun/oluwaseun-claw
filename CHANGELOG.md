# Changelog

## 0.2.1 — 2026-10-25 (interface redesign + background mode)
### Added
- Redesigned main window: custom title bar, grouped task list, large task box with example
  tasks, timeline of steps, docked approval sheet, outcome card; light and dark themes.
- Quick bar: always-on-top pill at the top of the screen; click or press Ctrl+Shift+Space,
  type a task, press Enter. Shows live activity, "Needs your OK", and a stop button.
- Tray icon with status (idle / working / needs you) and menu: open, new task, stop, show
  quick bar, start with Windows, quit. Closing the window keeps Claw running.
- Desktop notifications when a task finishes or needs approval (click opens the task).
- Keeps the computer awake while a task runs (setting).
- Start with Windows (setting; launches hidden in the tray).
- App and tray icons; bundled Manrope font.

## 0.2.0 — 2026-10-25 (Batch 2)
### Added
- Tool system with schemas, risk levels, validation and pre-checks (13 tools).
- Browser control through Playwright with a dedicated profile (Edge default on Windows):
  web search, open address/result, read page, links, follow link, click button, tabs.
- Browser-history search (titles/addresses only, always asks or off).
- `save_links` to authorized folders (no overwrite, only links seen in the task).
- Executor loop and background runner: Run, Stop, approvals, limits, retries, audit events.
- UI: Run task, live activity, approval card, Stop, outcome summary, browser/limits settings.
- Database v2 with migration; unfinished tasks marked interrupted after restart.
- Local test website and 29 new backend tests; e2e test extended to 18 checks.
### Changed
- Ctrl+Enter now runs the task; "Plan only" is a separate button.

## 0.1.0 — 2026-10-25 (Batch 1)
### Added
- Repository audit and architecture decision (custom Electron + Python runtime).
- Python backend: settings with validation and readable errors, health check,
  Ollama and llama.cpp (OpenAI-compatible) adapters, model status/probe,
  task planner with schema-validated JSON and one corrective retry,
  permission policy with risk levels and folder scoping, SQLite history and
  audit events, JSON logging with secret redaction.
- Electron desktop app: starts the backend with a per-launch token, route
  allowlist, sandboxed UI with task input, Plan button, progress, results,
  history search, settings drawer (model, permissions, folders), error banner.
- Windows scripts: setup, start, check. Linux check script.
- Tests: 46 backend, 2 desktop unit, 12-check end-to-end.

### Not included yet
- No step is executed; plans are proposals only.
