# Test results

## Batch 2 — 25 October 2026

**Environment:** Linux x86_64 workspace, Python 3.13.17, Node 22.23.4, Electron 45.0.0 (Xvfb,
`--no-sandbox` because the workspace runs as root), Playwright 1.64.1 driving a preinstalled
**Chromium 153.0.8010.12** via `CLAW_BROWSER_EXECUTABLE` (Playwright's own browser download and
the public internet are blocked from the workspace).

**Model:** scripted **test double** only (`backend/tests/fake_model_server.py`). The browser,
local test website, files, database and permission checks are all real.

**Website:** local **test fixture** (`backend/tests/site_server.py`): a search page, four articles
(one with a prompt-injection text), and a contact form.

| Command | Result |
|---|---|
| `python -m compileall -q claw tests` | pass |
| `python -m pytest -q` | **75 passed** (46 from Batch 1 + 13 browser tools + 16 executor/runner) |
| `npm run check` | pass |
| `npm test` (route allowlist) | **3 passed** |
| `CLAW_BROWSER_EXECUTABLE=… scripts/check.sh` (includes e2e) | **18/18 end-to-end checks passed** |

### Batch 2 acceptance criteria — what was demonstrated
| Criterion | Evidence |
|---|---|
| Open a browser | Real Chromium launched by the backend (browser tests, e2e) |
| Search for a topic | `web_search` against the local test search page; non-matching article excluded |
| Read a page and extract information | `read_page` returns main text without nav/footer; `extract_links` |
| Open a selected result | `open_search_result` → correct article |
| Collect and save URLs | `save_links` wrote the file; e2e confirmed the file on disk |
| Find a previously visited page via history | Real Chromium history of the agent's own profile searched after visits |
| Report errors instead of inventing results | Invented URL refused; 404 reported as failure; model outage → "Failed"; missing browser → clear message |

### Safety behaviours tested
- Saving a file asks first; declining stops the task and writes nothing.
- Clicking a form button asks first; stopping the task while waiting → form never submitted (checked on the server).
- Settings "Never" blocks without asking.
- History search always asks (even though read-only), or is refused when set to Never.
- Page text is wrapped in `<untrusted>` tags; the injection text sits inside them.
- Unknown tools, bad arguments, three failures in a row, repeated identical actions, step limit — all stop or reject.
- Non-web addresses (`file:`, `javascript:`, `chrome:`) refused. File names cannot leave the authorized folder.
- Links not seen during the task are refused before the user is asked to approve.

### Bugs found and fixed during Batch 2
- The user could be asked to approve a `save_links` step that was always going to be refused → added
  pre-checks that run before approval.
- `scripts/check.sh` e2e needs `CLAW_BROWSER_EXECUTABLE` when Playwright's Chromium is not installed → documented.

### Not run
- Any real model (qwen2.5 / qwen3 via Ollama or llama.cpp).
- Live DuckDuckGo or Bing pages.
- Microsoft Edge or Chrome as the controlled browser; Chrome/Edge history files on Windows.
- Anything on Windows 10; PowerShell scripts.

## Batch 1 — 25 October 2026
46 backend tests, 2 desktop unit tests, 12 e2e checks passed (Linux, test-double model).
Bugs fixed: permission default mismatch; Node 22 `--test` directory argument.
