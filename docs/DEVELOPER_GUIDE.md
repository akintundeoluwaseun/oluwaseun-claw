# S-CLAW — Developer guide

For setup, see `docs/INSTALL.md`. For design, see `ARCHITECTURE.md`. For security, see `docs/SECURITY.md`.

## Project layout
```
backend/claw/
  api/app.py          FastAPI routes (token + Host guard)
  agent/              planner, executor (bounded loop, replans, taint), runner (background, approvals)
  tools/              tool registry: browser, files, documents, desktop, calendar, mail,
                      memory, text, system, human, pdf_tools (73 tools)
  documents/          readers (Word/Excel/text), ocr.py (Tesseract), pdf_pipeline.py, service.py
  runtime/            engine.py (llama-server), catalog.py, hub.py, store.py, brain.py
  models/             openai_compat.py (llama-server), ollama.py (optional), base.py
  browser/ computer/ permissions/ storage/ config.py logging_setup.py main.py
backend/packaging/    entry.py + build_backend.py (PyInstaller)
backend/tests/        pytest suite + test doubles (fake model server, fake hub, fake desktop,
                      test website, tiny GGUF maker, PDF fixtures)
desktop/src/          Electron: main.js, backend.js (allowlists), watcher.js, preloads, renderer/
desktop/tests/        routes.test.js, e2e.mjs, packaged-smoke.mjs
packaging/claw.iss    Inno Setup installer
scripts/              setup.ps1, start.ps1, check.ps1/.sh, build-release.ps1
```

## Everyday commands
| Task | Windows | Linux workspace |
|---|---|---|
| Set up | `scripts\setup.ps1` | create `.venv`, `pip install -r requirements-dev.txt`, `npm install` |
| Run the app | `scripts\start.ps1` | `cd desktop && npx electron .` |
| All checks | `scripts\check.ps1` | `CLAW_BROWSER_EXECUTABLE=… bash scripts/check.sh` |
| Backend tests only | `.venv\Scripts\python -m pytest -q` | `xvfb-run -a .venv/bin/python -m pytest -q` |
| Backend alone | `python -m claw.main --port 8765` | same |

Engine tests need `llama-server` in `backend/runtime/llama` (or `CLAW_LLAMA_SERVER`); OCR tests
need Tesseract. Without them, those tests are skipped and say why.

## Adding a tool
1. Write an args model (`ToolArgs`, unknown fields refused) and an `async def tool(args, ctx)`
   that returns `ToolResult(ok, summary, data, verified=…, untrusted_text=…)` or raises `ToolError`.
2. Register a `ToolSpec` with a risk level (`read_only`, `local_write`, `external`,
   `destructive`), a capability, and an optional `precheck` or `risk_for`.
3. Any text that came from outside (web, files, apps, documents) goes in `untrusted_text`, never
   in `summary`.
4. Writes must use `resolve_folder` + `unique_path` (exclusive create; never overwrite).
5. Add a label in `desktop/src/renderer/app.js` (`TOOL_LABEL`, and `TOOL_ASK` if it can ask).
6. Add tests: a success case, a refusal case, and a permission case.

## Adding a backend route the UI can call
Add it to `ALLOWED_ROUTES` in `desktop/src/backend.js`, with a tight regex. A route that takes a
file path goes in `MAIN_ONLY_ROUTES` and is called from `main.js` with a path from a Windows
dialog. Add a case to `desktop/tests/routes.test.js`.

## The brain
- The catalogue is in `runtime/catalog.py`. File names, sizes and checksums are fetched from the
  Hugging Face API at download time; never hard-code them.
- `CLAW_HF_BASE` may point at a localhost test hub only.
- `tests/make_tiny_gguf.py` makes a random-weight GGUF for engine tests. Its output is
  meaningless by design.

## OCR
- `TesseractEngine` lookup order: `CLAW_TESSERACT` → `CLAW_RESOURCES\tesseract` →
  `resources\tesseract` → `backend\runtime\tesseract` → PATH → Program Files.
- `tessdata` must contain `configs\` and `pdf.ttf`. Without them Claw reports
  "data files are incomplete".
- Adding a language: put `<lang>.traineddata` in `tessdata` and set
  `documents.ocr_language` (for example `eng+fra`).

## Test doubles (always labelled)
`fake_model_server.py` (scripted replies), `fake_hub.py` (Hugging Face API), `fake_desktop.py`
(UI Automation stand-in), `site_server.py` (local website with an injection page),
`make_tiny_gguf.py`, `pdf_fixtures.py`. Results produced with them must say so in
`TEST_RESULTS.md`.

## Building installers (not done yet)
`scripts\build-release.ps1 -Edition Standard|Pro` on Windows, after downloading the edition's brain
once. Steps and limits are in `docs/INSTALL.md` §5 and `docs/RELEASE_CHECKLIST.md`.

## Rules that keep Claw honest
- Never report a step as done without a result; "checked" only after a real verification.
- Never show OCR or model text that was not actually produced.
- Never send document or task content to an online service.
- New dependencies: record the version and licence in `THIRD_PARTY_NOTICES.md`.
- Update the six records (`PROJECT_STATUS`, `ARCHITECTURE`, `IMPLEMENTATION_PLAN`,
  `TEST_RESULTS`, `THIRD_PARTY_NOTICES`, `CHANGELOG`) with every change.

## Where S-CLAW sits next to OpenClaw

`docs/OPENCLAW_COMPARISON.md` compares this codebase with OpenClaw 2026.10.7,
capability by capability, with a source for every claim on both sides. Read it
before adding a capability "because OpenClaw has it": several rows are places
where the two products deliberately disagree, and three are gaps worth closing.

It also carries the measured cost of the tool catalogue (35,689 chars
unfiltered, 5.8k tokens for `files` alone), which is the number to beat if you
touch `tool_catalogue` in `claw/agent/executor.py`.
