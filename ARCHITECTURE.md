# Architecture

```
┌──────────────────────── Electron desktop app (desktop/) ────────────────────────┐
│  Renderer (sandboxed page)        Preload bridge          Main process          │
│  index.html / app.js  ──IPC──▶  window.claw.*        ──▶  backend.js             │
│  no Node, strict CSP              (no token)              • starts the backend   │
│  Home · Task · Documents ·                                  (frozen exe, or      │
│  Settings (brain manager)                                    Python in dev)      │
│  quickbar.html (always on top)                            • holds session token  │
│                                                           • page route allowlist │
│                                                           • main-only routes     │
│                                                             (paths from dialogs) │
│                                                           • tray, notifications  │
└───────────────────────────────────────────────────────────────┬─────────────────┘
                                         HTTP 127.0.0.1:<random port>, X-Claw-Token
┌──────────────────────────── Python agent runtime (backend/claw/) ───────────────┐
│ api/app.py      FastAPI routes, token + Host guard, error format                │
│ config.py       Settings schema, plain-English validation, atomic save          │
│ agent/          planner · executor (bounded loop, replans, taint) · runner      │
│ tools/          43 tools: browser, files, documents, desktop, PDF/OCR           │
│ documents/      readers.py (Word/Excel/text) · ocr.py (Tesseract) ·              │
│                 pdf_pipeline.py (text vs scan per page, OCR, rotation, cache,   │
│                 searchable copy, page-aware chunks) · service.py (jobs)         │
│ runtime/        engine.py (llama-server lifecycle) · catalog.py (Standard/Pro)  │
│                 · hub.py (licence/size/checksum, resumable download) ·          │
│                 store.py (bundled/downloaded/imported brains) · brain.py        │
│ models/         base.py · openai_compat.py (llama-server) · ollama.py (optional)│
│ browser/ computer/ permissions/ storage/ logging_setup                          │
└──────┬───────────────────────┬──────────────────────┬──────────────┬───────────┘
       │ subprocess, 127.0.0.1  │ subprocess            │ Playwright    │ UI Automation
  llama-server (MIT)       tesseract (Apache-2.0)   Edge/Chrome     Windows apps
  random port + API key    1 thread, time limit     (own profile)   (pywinauto)
  Qwen3-VL GGUF + mmproj   eng + osd data
```

## Packaged app (Windows)
```
Oluwaseun Claw\
  Oluwaseun Claw.exe            Electron
  resources\app.asar            desktop/src
  resources\backend\            claw-backend.exe (PyInstaller, no Python needed)
  resources\engine\             llama-server.exe + ggml DLLs
  resources\tesseract\          tesseract.exe + DLLs + tessdata\eng, osd
  resources\models\<id>\        manifest.json + GGUF (edition's brain)
%APPDATA%\OluwaseunClaw\        settings.json, claw.db, logs\, models\ (downloads), documents\ (OCR cache)
```
The main process sets `CLAW_RESOURCES` so the backend finds the engine, OCR and bundled brain.
Installers: electron-builder makes the unpacked app; Inno Setup makes `Setup.exe` (Pro adds
`.bin` parts because one Inno file holds ~4.2 GB).

## How a task runs
1. `POST /tasks/run` → runner creates the task and returns at once.
2. The brain is made ready: built-in mode starts `llama-server` with the active brain (memory
   check, load wait, crash restart), or developer mode connects to a custom server.
3. Planner asks for a step plan (JSON schema); malformed or cut-off replies are retried, then
   reported honestly.
4. Executor loop, one step at a time: tool exists? → arguments valid? → repeated? → pre-check →
   permission (allow / ask / deny, raised by taint and labels) → run with timeout → record
   verified / done-but-unchecked / failed → observation back to the model, untrusted text inside
   `<untrusted>` tags.
5. The outcome is built from recorded steps; the model's own summary is shown separately.

## How a document is read
1. The user picks a file (main-process dialog) → `POST /documents/open` (main-only) → a job runs
   in a worker thread with real progress (`checking n/N`, `ocr n/M`).
2. Each PDF page: pypdfium2 text; ≥ 25 letters/digits → "from the file's text". Otherwise the
   page is rendered at 300 DPI (grayscale) and OCR'd with Tesseract (TSV → paragraphs + mean
   word confidence). Low confidence or few words + OSD available → rotate and retry.
3. Per page: source (text / ocr / empty), status (ok / low_confidence < 60% / failed / empty),
   confidence, rotation, note. Cached by file SHA-256 + engine + language.
4. Search (snippets with page numbers), page-aware chunks (≤ 6,000 chars) for summaries
   (map over chunks → combine; ≤ 40 chunks), searchable copy (original text pages + Tesseract
   PDF pages, merged with pypdf, never overwriting).
5. None of this needs the brain; only summarising/asking does.

## Key decisions
- **Custom shell over forking agent frameworks** — `docs/REPO_AUDIT.md`.
- **llama.cpp, not Ollama** — one MIT executable Claw can ship, start, stop and watch; JSON-schema
  constrained output; vision via mmproj. Ollama stays as an optional developer adapter.
- **Tesseract + pypdfium2, not OCRmyPDF** — no Ghostscript (AGPL), no extra installs; OCR only
  the pages that need it.
- **Two editions** (Standard 4B, Pro 8B) because one installer can't know the computer.
- **Structured output** — `response_format` JSON schema, always re-validated with Pydantic.

## Brain selection
`settings.model.mode`: `builtin` (default) → `Brain.active_model(selected)`: the selected brain if
present, else bundled → downloaded → imported, preferring the recommended one; `custom` → developer
adapter (OpenAI-compatible or Ollama). The engine unloads after `idle_unload_minutes`.

## Task memory and honesty
`TaskMemory`: text read (web, files, apps, documents), files opened and produced, taint flags.
Reports cite only opened sources; injection-like content raises later actions to "ask"; after 2
failed steps the model is asked for a new plan (max 2).

## Data locations
`%APPDATA%\OluwaseunClaw\` (override with `CLAW_DATA_DIR`).

## Planned additions
- Code signing; first Windows build and test of the installers.
- More OCR language packs (download from tessdata with licence and checksum checks).
