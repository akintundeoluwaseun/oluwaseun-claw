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

## Considered and not used (see docs/REPO_AUDIT.md)
OCRmyPDF (MPL-2.0, but needs Ghostscript, AGPL), PaddleOCR (Apache-2.0, heavy runtime),
PDF-OCR (a web app), DynaLM (unverified clients).
