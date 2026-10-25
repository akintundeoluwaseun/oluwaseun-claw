# Test results

## Batch 3 + brain + interface — 25 October 2026

**Environment:** Linux workspace (no Windows), Python 3.13.17, Node 22.23.4, Electron 45.0.0 under
Xvfb, Chromium 153 via `CLAW_BROWSER_EXECUTABLE`. Backend tests run under Xvfb so the real
screenshot test has a display.

**Stand-ins (all labelled TEST DOUBLE in code):** model server (Ollama API), Google Gemini API
(`tests/fake_gemini_server.py`, documented REST format), Windows desktop (`tests/fake_desktop.py`,
a simulated Notepad with Save As). Browser, files, database, permissions, Electron app: real.

| Command | Result |
|---|---|
| `xvfb-run python -m pytest -q` | **120 passed** |
| `npm run check` / `npm test` | pass / **3 passed** |
| `scripts/check.sh` end-to-end | **31/31 checks passed** |

### Batch 3 acceptance — what was demonstrated (on the stand-in desktop)
| Criterion | Evidence |
|---|---|
| Open an application | `launch_app` Notepad → new window detected (`test_open_type_save_in_notepad`) |
| Interact with its UI | numbered controls; click Save → Save As dialog detected |
| Type text | `type_into` read back and matched |
| Inspect the resulting state | before/after snapshots; "nothing visible changed" reported as not checked |
| Confirm success | full flow saved `notes.txt` with the typed text, 8/8 steps checked (`test_batch3_acceptance_flow`) |
| Accessibility before coordinates | `click_at` refused until a screenshot exists; coordinates bounds-checked |
| Real screen capture | mss full-screen and region PNG captured for real under Xvfb |

### Other checks added
- Online brain: key validation, wrong key message, key not in settings file or API replies,
  Flash-Lite chosen, daily-limit fallback to the next model, legacy schema-field fallback,
  screenshot sent as inline image, override can't redirect the key off this computer.
- Offline brain: picks scale with RAM/GPU, cores left free, think-then-see downloads with
  progress, smaller fallback when a tag is missing, unload, "Ollama not running" message.
- Desktop safety: system tools refused before approval; "Send to Teams" asks even with writes
  allowed; blocked key combos; locked screen message; stale control numbers refused.
- File tools: newest PDF first; outside-folder and binary files refused.
- E2E: first-launch welcome, wrong key refused, key connects, key never shown back, desktop step
  on a machine without desktop control fails with a clear reason and is counted as failed.

### Bugs found and fixed
- Settings dropped the `policy()` method during a refactor (caught by tests).
- Hardware detection was bound at import, ignoring test hardware profiles.
- "visual studio" was not flagged as ambiguous between two apps.
- Quick bar text "Claw needs you" was cut off; model chip stayed "ready" after an outage.

### Not run
- Windows UI Automation driver on Windows 10 (see checklist in `docs/DESKTOP.md`).
- Google's live API with a real key; any real model.
- Offline download from the real Ollama library; Ollama on Windows.
- Tray icon and notifications (no tray/notification service in Xvfb; code paths guarded).

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
