# Third-party notices

Oluwaseun Claw is MIT-licensed. No third-party source code has been copied into this
repository; everything below is used as an installed package, a separate program, or data.
Licences were read from each package's own metadata (Python: `License-Expression`/classifiers
via `importlib.metadata`; npm: `package.json`) on 2026-10-26, plus the model card for weights.

## Shipped inside the installer
### Separate programs and data
| Component | Version | Licence | Used for | Notes |
|---|---|---|---|---|
| llama.cpp `llama-server` + ggml libraries | newest official Windows release at build time (tested here: source build d854d98, 0.7.0-dev) | MIT | Runs Claw's brain locally | Copy the release's `LICENSE` into `resources\engine` (build script keeps everything in the release zip) |
| xdotool, wmctrl (Linux, run as commands, not shipped) | system packages | BSD-3 / GPL-2 (separate programs) | Desktop control on Linux X11 | Installed by the person or the distro; not linked or bundled |
| segno | 1.6.6 | BSD-3-Clause | QR code for pairing the phone app | Python dependency |
| OpenClaw (github.com/openclaw/openclaw, commit b8b054c1) | ported code, not a dependency | MIT, Copyright (c) 2026 OpenClaw Foundation | Three pieces rewritten in Python: the DuckDuckGo HTML search parser (`backend/claw/browser/ddg_html.py`, from `extensions/duckduckgo/src/ddg-client.ts`), the JSON repair for model output (`backend/claw/agent/jsonfix.py`, from `packages/ai/src/utils/json-parse.ts`), and the SKILL.md skill format (`backend/claw/agent/skills.py`). Each file names its source. The MIT notice must ship with the app. |
| Microsoft Visual C++ runtime (`vcruntime140*.dll`, `msvcp140*.dll`, `vcomp140.dll`) | as installed on the build machine | Microsoft Visual Studio redistributable terms (app-local deployment of these files is permitted) | Lets llama-server start on PCs without the VC++ Redistributable | Copied by `build-release.ps1` into the engine folder |
| Tesseract OCR (UB Mannheim Windows build) | 5.x at build time (tested here: 5.3.4 Linux) | Apache-2.0 | OCR of scanned pages | The Windows build also contains Leptonica (BSD-2-Clause), libpng/zlib/libjpeg/libtiff/libwebp/openjpeg/giflib (permissive) and others; `build-release.ps1` copies the LICENSE/COPYING/AUTHORS files it finds. **Review the full DLL list on the first Windows build.** |
| Tesseract language data `eng.traineddata`, `osd.traineddata` (tessdata) | as shipped with that build | Apache-2.0 | English text, page orientation | Other languages are not bundled; more can be added as packs |
| Qwen3-VL 4B Instruct GGUF (Standard edition) | `Qwen/Qwen3-VL-4B-Instruct-GGUF`, Q4_K_M + mmproj F16 | Apache-2.0 (model card) | Standard brain | Checked again by the app before download and by the build script before bundling |
| Qwen3-VL 8B Instruct GGUF (Pro edition) | `Qwen/Qwen3-VL-8B-Instruct-GGUF`, Q4_K_M + mmproj F16 | Apache-2.0 (model card; same check) | Pro brain | Same checks |
| Electron | 45.0.0 | MIT | Desktop shell | Includes Chromium and Node.js; their notices ship in `LICENSES.chromium.html` |
| Manrope font (@fontsource-variable/manrope 5.3.0) | — | SIL OFL 1.1 (`desktop/src/renderer/fonts/OFL-Manrope.txt`) | Interface typeface | |
| CPython (inside the frozen backend) | 3.12 | PSF-2.0 | Runs the backend | Bundled by PyInstaller |

### Python packages (in the frozen backend)
| Package | Version | Licence |
|---|---|---|
| fastapi | 0.162.0 | MIT |
| starlette | 1.10.0 | BSD-3-Clause |
| uvicorn | 0.54.0 | BSD-3-Clause |
| click | 8.5.0 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| anyio | 4.15.1 | MIT |
| idna | 3.20 | BSD-3-Clause |
| pydantic / pydantic-core | 2.14.1 / 2.50.1 | MIT |
| annotated-types / annotated-doc / typing-inspection | 0.8.0 / 0.0.5 / 0.4.4 | MIT |
| typing-extensions | 4.16.0 | PSF-2.0 |
| opentelemetry-api (FastAPI dependency) | 1.45.1 | Apache-2.0 |
| httpx / httpcore | 0.28.1 / 1.0.9 | BSD-3-Clause |
| certifi | 2026.10.23 | MPL-2.0 (unmodified; source at github.com/certifi/python-certifi) |
| playwright | 1.64.1 | Apache-2.0 (includes a Node.js driver; see its NOTICE) |
| greenlet / pyee | 3.5.6 / 14.0.0 | MIT AND PSF-2.0 / MIT |
| mss | 10.2.0 | MIT |
| openpyxl / et-xmlfile | 3.1.5 / 2.0.0 | MIT |
| python-docx / lxml | 1.2.0 / 6.1.3 | MIT / BSD-3-Clause |
| pypdf | 6.21.2 | BSD-3-Clause |
| pypdfium2 (with PDFium binary) | 5.14.0 | BSD-3-Clause, Apache-2.0; PDFium BSD-3-Clause and its dependencies' licences (shipped in the wheel's `LICENSES` folder) |
| pillow | 13.0.0 | MIT-CMU |
| pywinauto (Windows) | 0.6.9 | BSD-3-Clause |
| pywinauto — *approach only*, see below | 0.6.9 | BSD-3-Clause |
| comtypes (Windows) | 1.4.17 | MIT |
| pywin32 (Windows) | 312 | PSF-2.0 |
| six (Windows) | 1.17.0 | MIT |
| SQLite (Python stdlib) | — | Public domain |

## Build tools (not shipped)
| Tool | Version | Licence | Note |
|---|---|---|---|
| PyInstaller | 6.16.0 | GPL-2.0-or-later with the bootloader exception | The exception allows distributing the frozen program under any licence |
| electron-builder | 26.17.0 | MIT | |
| Inno Setup | 6.x | Inno Setup License (permissive) | |

## Development and test only
| Component | Version | Licence |
|---|---|---|
| pytest | 9.1.1 | MIT |
| pytest-asyncio | 1.4.0 | Apache-2.0 |
| playwright-core (npm) | 1.64.1 | Apache-2.0 |
| gguf (writes the tiny random test model) | 0.19.0 | MIT |
| numpy (gguf dependency) | as resolved | BSD-3-Clause |
| pip-licenses (licence scan) | 5.0.0 | MIT |
| pip-audit (vulnerability scan) | 2.9.0 | Apache-2.0 |

## Optional, not shipped
| Program | Licence | Note |
|---|---|---|
| Ollama | MIT | Optional developer adapter only; Claw never requires it |
| Microsoft Edge / Google Chrome | Proprietary | Already on the user's computer; controlled, not bundled |
| Chromium (optional, `setup.ps1 -Chromium`) | BSD-3-Clause and others | Downloaded by Playwright; not bundled |

## Considered and not used (see docs/REPO_AUDIT.md and docs/AUDIT_V06.md)
Phase A: Selenium, Browser Use, Stagehand, Puppeteer (Playwright already covers forms and downloads);
PyAutoGUI, FlaUI, AutoHotkey, WinAppDriver, SikuliX, RobotJS, Nut.js (pywinauto + UI Automation already
cover launch, menus, scroll and typing; WinAppDriver is unmaintained; FlaUI is .NET; AutoHotkey would add
a second scripting runtime). No new dependency was added in Phase A.
Phase B (WhatsApp): whatsapp-web.js and Baileys were **not used** — both are unofficial clients that log in as
a linked device; WhatsApp can restrict accounts that use them, and the user chose the official app. The
WhatsApp Business Platform (Cloud API) was not used: it serves business numbers through Meta, not a person's
own chats. Claw reads the official WhatsApp Desktop app through Windows UI Automation (pywinauto, already
bundled). No new dependency was added.
Phase D (images): Pillow (already bundled) renders and edits; Photoshop is driven through its own COM/ExtendScript
interface with pywin32 (already bundled) only when the user has it installed. GIMP, Krita, ImageMagick, OpenCV and
ComfyUI were not added: each is a large extra install or model download for what Pillow already does here.
Fonts: the flyer uses fonts already on the computer (Segoe UI/Arial on Windows); none are bundled.

OCRmyPDF (MPL-2.0, but needs Ghostscript, AGPL), PaddleOCR (Apache-2.0, heavy runtime),
PDF-OCR (a web app), DynaLM (unverified clients).

## Voice input (offline speech recognition)

**sherpa-onnx** (https://github.com/k2-fsa/sherpa-onnx, Apache-2.0) — chosen and added as a
dependency. It installs as an ordinary Python wheel on Windows, so it needs no second native binary
beside llama-server, and it runs Whisper exports on CPU through ONNX Runtime (MIT). The engine sits
behind `claw/speech/base.py`, so it can be replaced without touching the command bar.

**Speech model weights** are Whisper exports (MIT, https://github.com/openai/whisper), downloaded on
request from Hugging Face. Nothing is bundled in the installer: file names, sizes, SHA-256 checksums
and the licence are read from the public API at download time and the licence is checked against an
allow-list before anything is written, exactly as for the brain.

Evaluated and **not** used:

- **whisper.cpp** (MIT) — the obvious alternative and a close call. It would mirror the existing
  llama-server runtime management, but it means shipping and updating a second compiled binary per
  platform for no accuracy gain over the same weights. Kept as the first candidate if sherpa-onnx
  proves unsuitable; the engine interface exists for that.
- **faster-whisper** (MIT) — pulls in CTranslate2 and, in practice, a CUDA/cuDNN story that makes a
  Windows installer considerably larger for a CPU-only use case.
- **Vosk** (Apache-2.0) — smaller and faster, but its English models are noticeably weaker on
  accented speech and proper nouns, which is the case that matters most here.
- **Windows Offline Transcribe**, **AuraScribe**, **Whisper Local** — useful as reference
  implementations; all are applications rather than libraries, and none is a maintained dependency
  suitable for redistribution.
- **Silero VAD** (MIT) — not added separately: sherpa-onnx already bundles voice-activity detection,
  and the bar records only while the user holds or clicks the microphone, so endpointing is not what
  decides when recording stops.
- **NAudio** (MIT) — a .NET library; Claw captures audio in the Electron renderer through the Web
  Audio API, so it has nothing to add.
- **WhisperX, pyannote** — speaker diarisation and alignment are not needed for single-speaker
  commands, and pyannote's models carry gated licences.

## Code adapted rather than imported

**pywinauto** — BSD-3-Clause, Copyright (c) 2017, Mark Mc Mahon and
Contributors. `claw/tools/desktop_tools.py:match_control` finds a control by
name using the approach in upstream's `pywinauto/findbestmatch.py`: score every
candidate label with `difflib.SequenceMatcher.ratio()` after cutting it at the
first tab or newline, and refuse rather than return a poor match. No upstream
source was copied; the algorithm is re-expressed over S-CLAW's own
`ControlInfo` records, because `pywinauto` installs on Windows only and this
logic must behave identically on the Linux test desktop.

**agentmem** — MIT, Copyright (c) 2025 agentmem contributors.
`claw/agent/executor.py:_relevance` ranks remembered facts using the shape
described in that project's README — tier weight, keyword overlap, recency
boost. None of its code is used: its retrieval path requires `chromadb` and
`sentence-transformers`, which S-CLAW does not ship.
