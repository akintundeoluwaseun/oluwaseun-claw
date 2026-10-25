# Test results

## Batch 1 — 25 October 2026

**Environment:** Linux x86_64 cloud workspace (not Windows), Python 3.13.17, Node 22.23.4,
Electron 45.0.0 under Xvfb with `--no-sandbox` (required only because the workspace runs as root).

**Model server:** a labelled **test double** (`backend/tests/fake_model_server.py`) that speaks
the Ollama and llama-server HTTP APIs with scripted replies. Real model weights could not be
downloaded (ollama.com and huggingface.co are blocked from the workspace). No result below
comes from a real model.

| Command | Result |
|---|---|
| `python -m compileall -q claw tests` | pass |
| `python -m pytest -q` | **46 passed** (1 deprecation warning from Starlette's TestClient) |
| `npm run check` (node --check on all JS) | pass |
| `npm test` (route allowlist) | **2 passed** |
| `node tests/e2e.mjs` (real Electron + real backend + test double) | **12/12 checks passed** |
| Manual: `python -m claw.main --port 18765` + curl | `/health` 200; `/settings` without token 401; with token returns clear "Could not connect to Ollama" message; token absent from log file |

### End-to-end checks (desktop/tests/e2e.mjs)
1. Backend launched by the desktop app and reported ready
2. Model pill shows the configured model
3. Renderer bridge exposes no token
4. Disallowed route refused by the main process
5. Plan rendered with 3 steps
6. Status shows "Plan ready"
7. Read-only step shows "Runs without asking"
8. Task saved to history
9. Settings → Test connection reports ready
10. Remote model address refused with a readable message
11. Model server outage shown as an error (no invented plan)
12. Failed task recorded in history

### Bug found and fixed during testing
- Permission policy defaulted read-only actions to "ask" while settings defaulted to "allow".
  Both now share `DEFAULT_MODES`.
- `node --test tests/` failed on Node 22 (directory argument); now targets the test file.

### Not run
- Anything on Windows 10 (no Windows machine in the workspace).
- Any real model (Ollama/llama.cpp with real weights).
- PowerShell scripts (`setup.ps1`, `start.ps1`, `check.ps1`) — written but not executed.
