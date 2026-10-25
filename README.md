# Oluwaseun Claw

A local-first AI agent for Windows 10. Type what you want done in plain English;
the agent plans it with a model running on your own computer (no paid API) and,
in upcoming versions, carries it out in your browser and desktop apps with
permission checks at every step.

**Status:** v0.1.0 (Batch 1). The agent plans tasks and shows what each step would
touch and whether it needs your approval. It does **not** execute steps yet.
See `PROJECT_STATUS.md`.

## Quick start (Windows 10)
1. Install Python 3.12, Node.js 22, and Ollama.
2. `ollama pull qwen2.5:7b`
3. `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`
4. `powershell -ExecutionPolicy Bypass -File scripts\start.ps1`

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
