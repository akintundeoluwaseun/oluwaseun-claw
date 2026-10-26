# Repository audit (Batch 1)

Audited 25 October 2026. Each repository was shallow-cloned from GitHub and its
LICENSE and README read directly. The GitHub API was not available from the
build workspace, so star counts and "latest release" tags were not collected;
"last commit" is the date of the newest commit on the default branch.
PyPI/npm versions come from `pip index versions` and `npm view`.

| # | Project | License (read from repo) | Last commit | Role decision |
|---|---|---|---|---|
| 1 | openinterpreter/interpreter-workstation | Apache-2.0 (+ CC docs license, trademark policy) | 2026-10-24 | **Not used as base** (see below) |
| 2 | bytedance/UI-TARS-desktop | Apache-2.0 | 2026-10-09 | **Not used as base** |
| 3 | OpenInterpreter/open-interpreter | Apache-2.0 | 2026-10-11 | Not used (runs model-written code) |
| 4 | browser-use/browser-use | MIT | 2026-10-22 | Candidate for Batch 2, decide after testing with local models |
| 5 | microsoft/playwright (python) | Apache-2.0 | 2026-10-23 | **Selected for Batch 2** (playwright 1.64.1) |
| 6 | docs.browser-use.com | — | — | Read via README; library path is Python ≥ 3.11 |
| 7 | ollama/ollama | MIT | 2026-10-24 | **Selected** default local runtime (HTTP API) |
| 8 | ggml-org/llama.cpp | MIT | 2026-10-25 | **Selected** second runtime via `llama-server` OpenAI-compatible API |
| 9 | QwenLM/Qwen3 | Apache 2.0 stated in README | 2026-01-09 | Recommended model family (weights license per model card) |
| 10 | QwenLM/Qwen2.5 | Apache 2.0 stated in README; some sizes differ, see MODELS.md | 2026-01-09 | Recommended model family |
| 11 | pywinauto/pywinauto | BSD-3-Clause | 2026-10-24 | **Selected for Batch 3** (UI Automation backend) |
| 12 | asweigart/pyautogui | BSD-3-Clause | 2023-06-07 | Batch 3 fallback for visual control only; little recent activity |
| 13 | FlaUI/FlaUI | MIT | 2026-08-13 | Not used: .NET; would add a second runtime. pywinauto covers UIA from Python |
| 14 | electron/electron | MIT | 2026-10-24 | **Selected** desktop shell (45.0.0) |
| 15 | tauri-apps/tauri | Apache-2.0 / MIT | 2026-10-24 | Not used: needs Rust toolchain for every developer |
| 16 | fastapi/fastapi | MIT | 2026-10-23 | **Selected** (0.162.0) |
| 17 | pydantic/pydantic | MIT | 2026-10-23 | **Selected** (2.14.1) |
| 18 | SQLite | Public domain | — | **Selected** (Python stdlib `sqlite3`) |
| 19 | langchain-ai/langgraph | MIT | 2026-10-25 | Not used: a small explicit loop is easier to audit and bound |
| 20 | BerriAI/litellm | MIT, except `enterprise/` folder under a separate license | 2026-10-24 | Not used: large dependency; mixed licensing; the two adapters cover local servers |

## Foundation comparison

**Interpreter Workstation.** Mature, Apache-2.0, supports local models and
per-agent file/app access. But: it builds with Node 22 + pnpm + Bun + Rust +
git submodules and downloads a prebuilt agent runtime (`oix`) owned by the
upstream Open Interpreter project; the repository is ~2,500 files; its README
does not state Windows 10 support; and its trademark policy requires a
modified public distribution to rebrand everything. Building on it means
maintaining a fork of a large TypeScript product whose agent core we do not
control. Its agent model (Open Interpreter) executes model-written code, which
conflicts with this project's rule that the model never gets unrestricted OS
access.

**UI-TARS Desktop.** Apache-2.0 and designed for GUI control, but tied to the
UI-TARS / Seed vision-language models (the README points to UI-TARS-1.5-7B) and
the repository's focus has moved to Agent TARS, whose examples use cloud
providers. A 7B vision model is a heavy requirement for typical laptops and
was not verifiable here.

**Custom shell (chosen).** Electron UI + small Python agent runtime that
talks to Ollama or llama.cpp over localhost. Each piece is small, permissively
licensed, runs natively on Windows, and lets safety (tool schemas, risk levels,
folder scoping, approval) sit in code we own. Browser and desktop control are
added as validated tools in Batches 2–3 using Playwright and pywinauto, which
the custom loop calls directly. Code from Workstation/UI-TARS may be studied
for ideas; none has been copied.

## Scanned documents and the local engine (audit added for v0.5)
Reviewed from each repository's README, licence and build requirements
(no code copied).

| Repository | Licence | What it is | Decision |
|---|---|---|---|
| ocrmypdf/OCRmyPDF | MPL-2.0 | Adds an OCR text layer to PDFs, using Tesseract, Ghostscript, qpdf, img2pdf | **Not used.** Needs Ghostscript (AGPL-3.0) for most inputs and several separate Windows installs; its useful idea (keep text pages, OCR only image pages, write a hidden text layer) is implemented directly with pypdfium2 + Tesseract's own PDF renderer. |
| tesseract-ocr/tesseract | Apache-2.0 | OCR engine with TSV (word confidence), OSD (orientation) and PDF (searchable) output; official Windows builds by UB Mannheim | **Used** as a separate program (subprocess). Tested here with 5.3.4. |
| PaddlePaddle/PaddleOCR | Apache-2.0 | Deep-learning OCR, very accurate on hard scans | **Not the default.** Needs the PaddlePaddle runtime (hundreds of MB, heavy CPU/RAM), which conflicts with "must not lag the PC". Could be an optional language/quality pack later. |
| "PDF-OCR" (repository given in the task) | per repository | A web application around OCR | **Not used.** It is a hosted/web app, not a local library; would send documents off the computer. |
| ggml-org/llama.cpp | MIT | Local inference engine; `llama-server` speaks an OpenAI-compatible API, supports GGUF, vision projectors (mmproj) and JSON-schema constrained output | **Used** as Claw's managed engine. Built from source here at d854d98 (0.7.0-dev; Qwen3-VL supported) and run in tests. |
| DynaLM (repository given in the task) | per repository | A wrapper/launcher around local model servers | **Not used.** Its own README says only its own client is verified; adds a layer without removing any need. |
| pypdfium2-team/pypdfium2 | BSD-3-Clause / Apache-2.0 (PDFium BSD-3-Clause) | Python binding to PDFium; text extraction and page rendering; Windows wheels include PDFium | **Used** for reading text pages and rendering scans at 300 DPI. |

## Not verified
- Latest GitHub release tags (API blocked in workspace).
- Model-weight licences: Qwen3-VL-4B-Instruct-GGUF's Hugging Face page states Apache-2.0 (read via a fetch on 2026-10-26); the app re-checks the licence through the Hugging Face API before every download. The 8B card was not opened here; the same runtime check applies.
- Any component actually running on Windows 10 (no Windows machine in workspace).
