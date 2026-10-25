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
| SQLite (Python stdlib) | — | Public domain | Task history |

## Development and test only
| Component | Version | License |
|---|---|---|
| pytest | 9.1.1 | MIT |
| pytest-asyncio | 1.4.0 | Apache-2.0 |
| playwright-core (npm) | 1.64.1 | Apache-2.0 |

## Separate programs the user installs
| Program | License | Note |
|---|---|---|
| Ollama | MIT | Not bundled |
| llama.cpp | MIT | Not bundled |
| Model weights (e.g. Qwen) | Per model card | Not bundled — check each model card |

## To finish in Batch 5
A full transitive dependency license scan (pip-licenses / license-checker) and
copying of required notice files into the installer.
