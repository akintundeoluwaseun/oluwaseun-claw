# Oluwaseun Claw

A local-first AI agent for Windows 10. Type what you want done in plain English;
the agent plans it with a model running on your own computer (no paid API) and
carries it out step by step, with permission checks at every step.

**Status:** v0.5.0. Claw thinks with its own brain on your computer (llama.cpp engine, Qwen3-VL
model; no keys, no Ollama), works in a browser, operates Windows apps through UI Automation, reads
scanned PDFs with OCR (Tesseract) and shows which text came from a scan and how sure it is,
reads and writes documents and spreadsheets in folders you allow, re-plans when stuck, guards
against instructions hidden in web pages and documents, and runs in the background with a quick
bar, tray icon and notifications. Not yet run on Windows or with the real Qwen3-VL weights — see
`PROJECT_STATUS.md`.

## Quick start (Windows 10, developers)
1. Install Python 3.12 and Node.js 22.
2. `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`
3. `powershell -ExecutionPolicy Bypass -File scripts\start.ps1`
   (also fetches the llama.cpp engine and installs Tesseract OCR)
4. In the app, download the recommended brain once (Settings → Claw's brain).
5. Installers: `scripts\build-release.ps1 -Edition Standard` / `-Edition Pro`.

Full guide: `docs/INSTALL.md` · Models: `docs/MODELS.md` · Security: `docs/SECURITY.md`

## Layout
```
backend/   Python agent runtime (FastAPI, Pydantic, SQLite), OCR pipeline, llama.cpp manager
desktop/   Electron app
docs/      Install, models, security, repo audit
packaging/ Inno Setup installer script
scripts/   setup / start / check / build-release
```

## License
MIT. Third-party components: `THIRD_PARTY_NOTICES.md`.
