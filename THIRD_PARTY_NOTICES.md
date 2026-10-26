# Third-party notices

Oluwaseun Claw is MIT-licensed. It depends on the following components. No
third-party source code has been copied into this repository; all are used as
installed packages or separate programs.

## Bundled or installed with the app
| Component | Version | License | Used for |
|---|---|---|---|
| Electron | 45.0.0 | MIT | Desktop shell (includes Chromium and Node.js; their notices ship inside Electron's `LICENSES.chromium.html`) |
| FastAPI | 0.162.0 | MIT | Local HTTP API |
| Starlette (via FastAPI) | as resolved by pip | BSD-3-Clause | ASGI framework |
| Uvicorn | 0.54.0 | BSD-3-Clause | ASGI server |
| Pydantic | 2.14.1 | MIT | Validation |
| HTTPX | 0.28.1 | BSD-3-Clause | Model server client |
| Playwright for Python | 1.64.1 | Apache-2.0 | Browser control (includes a Node.js driver; see its NOTICE) |
| SQLite (Python stdlib) | — | Public domain | Task history |
| mss | 10.2.0 | MIT | Screenshots |
| pywinauto (Windows only) | 0.6.9 | BSD-3-Clause | Windows UI Automation |
| comtypes (Windows only) | 1.4.17 | MIT | COM access for pywinauto |
| pywin32 (Windows only) | 312 | PSF-2.0 | Windows APIs for pywinauto |
| six (Windows only) | 1.17.0 | MIT | pywinauto dependency |
| openpyxl | 3.1.5 | MIT | Excel files |
| et-xmlfile | 2.0.0 | MIT | openpyxl dependency |
| python-docx | 1.2.0 | MIT | Word files |
| lxml | 6.1.3 | BSD-3-Clause | python-docx dependency |
| pypdf | 6.21.2 | BSD-3-Clause | Reading PDFs |
| Manrope (font, via @fontsource-variable/manrope 5.3.0) | — | SIL OFL 1.1 (`desktop/src/renderer/fonts/OFL-Manrope.txt`) | Interface typeface, bundled locally |

## Development and test only
| Component | Version | License |
|---|---|---|
| pytest | 9.1.1 | MIT |
| pytest-asyncio | 1.4.0 | Apache-2.0 |
| playwright-core (npm) | 1.64.1 | Apache-2.0 |

## Separate programs the user installs
| Program | License | Note |
|---|---|---|
| Microsoft Edge / Google Chrome | Proprietary | Already on the user's computer; controlled, not bundled |
| Chromium (optional, `setup.ps1 -Chromium`) | BSD-3-Clause and others | Downloaded by Playwright; not bundled |
| Ollama | MIT | Development builds only; release builds will bundle llama.cpp instead (Batch 5) |
| llama.cpp | MIT | Not bundled |
| Model weights (e.g. Qwen) | Per model card | Not bundled — check each model card |

## To finish in Batch 5
A full transitive dependency license scan (pip-licenses / license-checker) and
copying of required notice files into the installer.
