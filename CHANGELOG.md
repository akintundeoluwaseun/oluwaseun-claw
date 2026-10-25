# Changelog

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
