# Oluwaseun Claw

A local-first AI agent for Windows 10. Type what you want done in plain English;
the agent plans it with a model running on your own computer (no paid API) and
carries it out step by step, with permission checks at every step.

**Status:** v0.4.0 (Batches 1–4). Claw thinks with a built-in brain on your computer (no keys,
no model picking), works in a browser, operates Windows apps through UI Automation, reads and
writes documents and spreadsheets in folders you allow, re-plans when stuck, guards against
instructions hidden in web pages, and runs in the background with a quick bar, tray icon and
notifications. Not yet run on Windows 10 or with a real model — see `PROJECT_STATUS.md`.

## Quick start (Windows 10, developers)
1. Install Python 3.12 and Node.js 22.
2. `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`
3. `powershell -ExecutionPolicy Bypass -File scripts\start.ps1`
4. Development builds need Ollama running; release builds will include the brain (Batch 5).

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
