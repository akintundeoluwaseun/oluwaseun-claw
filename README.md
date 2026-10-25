# Oluwaseun Claw

A local-first AI agent for Windows 10. Type what you want done in plain English;
the agent plans it with a model running on your own computer (no paid API) and
carries it out step by step, with permission checks at every step.

**Status:** v0.3.0 (Batches 1–3). Claw thinks Online (free Google AI key) or Offline
(built-in, chosen and downloaded automatically), works in a browser, operates Windows
apps through UI Automation, reads files in folders you allow, and runs in the background
with a quick bar, tray icon and notifications. Not yet run on Windows 10 or with a real
Google key — see `PROJECT_STATUS.md`.

## Quick start (Windows 10, developers)
1. Install Python 3.12 and Node.js 22.
2. `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`
3. `powershell -ExecutionPolicy Bypass -File scripts\start.ps1`
4. Choose Online or Offline on the welcome screen.

Full guide: `docs/INSTALL.md` · Models: `docs/MODELS.md` · Security: `docs/SECURITY.md`

## Layout
```
backend/   Python agent runtime (FastAPI, Pydantic, SQLite)
desktop/   Electron app
docs/      Install, models, security, repo audit
scripts/   setup / start / check
```

## License
MIT. Third-party components: `THIRD_PARTY_NOTICES.md`.
