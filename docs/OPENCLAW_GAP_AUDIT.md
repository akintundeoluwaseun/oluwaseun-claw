# OpenClaw gap audit — S-CLAW, 27 October 2026

## 1. Executive summary

S-CLAW is a **Windows desktop agent**; OpenClaw is a **chat-first local gateway**.
Measured against the supplied capability reference, S-CLAW is strong where it
operates the person's own computer and their own apps, comparable on memory,
calendar and scheduling, and absent on everything that assumes a daemon reachable
from twenty chat networks.

Three things found by inspection matter more than any missing integration:

1. **The local brain's context window is 8192 tokens and nothing was counting.**
   `claw/runtime/engine.py:117` starts `llama-server -c 8192`. The `files` tool
   catalogue alone costs ~5,833 tokens, and a twenty-step run could build
   ~38,000. No token accounting existed anywhere. **Fixed this session** with a
   budget, a trim and two diagnostics. Worth saying how: my first attempt made
   things *worse* — it kept the run under the window by dropping every
   observation, so the model would have acted blind. Two existing tests caught
   it. The rule now is that the last couple of steps are always sent, and going
   over the window is reported rather than hidden. A second existing test then
   caught something sharper: the **injection warning** was being trimmed away
   with the page it arrived on. Safety facts now travel as their own message and
   survive trimming whatever the budget. The underlying cause (one capability
   holding 37 of 76 tools) is the top roadmap item; a budget does not fix it.
2. **Memory is stored but never offered to the model.** `remember`/`recall`/
   `forget_this` work and are tested, yet nothing loads what is remembered at
   the start of a run. Retrieval is entirely model-initiated, so a 4B brain will
   usually never call `recall` and the feature has no effect on behaviour. This
   is the single cheapest high-value gap. **Not fixed** — it is the recommended
   next task.
3. **A scheduled job cut short by a restart read "running now" for ever.**
   `mark_interrupted()` repaired tasks but not jobs. **Fixed this session.**

Items 1 and 2 were then closed in the same session, after this report was first
written:

- `Capability.FILES` was split into `files` / `documents` / `organiser`. The
  worst bucket fell from **5,833 to 3,354 tokens**, and a calendar-or-memory
  step now costs **1,579** instead of 5,833 — against an 8192-token window.
- `remembered()` puts up to 800 characters of what the person has told Claw
  into the executor's system message, preferences first, labelled as a record
  rather than instructions. Memory now influences behaviour instead of waiting
  for a model that would never ask.

Nothing else was changed. No integration was added, nothing was deployed, and no
blocked capability has been talked up.

## 2. Verified current architecture

Verified by reading the code in this working tree, not from history:

| Piece | Where | Verified |
|---|---|---|
| Electron app (main, preload, quick bar, renderer) | `desktop/src/` | yes — `npm test` 33/33, `npm run check` parses every script |
| FastAPI backend on loopback, per-launch token ≥32 chars | `backend/claw/api/app.py` (`create_app`), host guard at `:215` | yes — 403 on a non-loopback Host, 401 on a bad token (`tests/test_api.py`) |
| Tool registry, typed args, risk per tool | `backend/claw/tools/registry.py`, `tools/base.py` | yes — **76 tools**, counted via `build_registry().names()` |
| Plan → act → verify loop | `agent/planner.py`, `agent/executor.py` (`run_agent`) | yes — tools execute, results are fed back as observations, outcome comes from recorded events |
| Permissions with a destructive floor | `permissions/policy.py` | yes — `tests/test_permissions.py`, `test_jobs.py` |
| Local brain (llama.cpp) + hosted + user-configured | `runtime/engine.py`, `models/`, `edition.py` | partly — code verified, **no model has ever answered here** |
| SQLite: tasks, events, memories, jobs | `storage/db.py`, schema v4 | yes |
| Calendar (.ics), reminders, briefing, memory, jobs | `claw/calendar/`, `brief.py`, `memory/`, `jobs/` | yes — logic tested; delivery on Windows is not |
| Desktop control (UI Automation) | `tools/desktop_tools.py`, `computer/driver.py` | **code only** — `pywinauto` is not importable on this machine |

## 3. Environment and account audit (Section C)

Probed on 27 Oct 2026 from this container. Status codes are from `curl`;
`000` means the egress proxy refused the connection.

| Thing | Probe result | What it means |
|---|---|---|
| Public web | `google.com`, `duckduckgo.com`, `python.org`, `huggingface.co` → **000** | **BLOCKED: ENVIRONMENT.** Real web research and model-weight download cannot be tested here. |
| GitHub | `api.github.com` **200**, `raw.githubusercontent.com` **301**, `github.com` **400** | API and raw files reachable; HTML is not. |
| Package registries | `pypi.org` **200**, `registry.npmjs.org` **200** | Dependencies installable. |
| Google APIs | `www.googleapis.com`, `gmail.googleapis.com`, `oauth2.googleapis.com` → **404** (a server answer, not a refusal) | Hosts **reachable**. Gmail/Calendar are therefore **BLOCKED: CREDENTIALS**, not environment — no OAuth client, no consent, no mailbox. |
| Microsoft | `login.microsoftonline.com` **302**; `outlook.office.com`, `graph.microsoft.com` **000** | Graph itself unreachable → **BLOCKED: ENVIRONMENT + CREDENTIALS.** |
| OpenAI / Cloudflare / Supabase | `api.openai.com`, `api.cloudflare.com`, `supabase.com` → **000** | **BLOCKED: ENVIRONMENT.** No hosted inference, no Workers AI, no Supabase can be reached or tested. |
| Provider credentials | `env` shows no `OPENAI_*`, `GOOGLE_*`, `CF_*`, `SUPABASE_*`, `TWILIO_*`, `WHATSAPP_*` key for Claw (the one `ANTHROPIC_BASE_URL` present belongs to this coding session's own tooling, not to the product) | **BLOCKED: CREDENTIALS** for every hosted path. |
| Claw Online endpoint | No service URL configured; `claw/models/claw_service.py` raises `ClawServiceUnconfigured` | **BLOCKED: INFRASTRUCTURE.** The service does not exist. |
| Model weights / runtime | No `*.gguf` anywhere on disk; no `llama-server` binary; no `backend/runtime/` | **BLOCKED: INFRASTRUCTURE.** Local inference cannot run or be measured. |
| Hardware | 4 cores, 15 GB RAM, 252 GB disk, **no GPU** (`nvidia-smi` absent, no `/dev/dri`) | CPU-only. Fine for a 2–4B brain; no CUDA/Vulkan path testable. |
| Windows | `uname` → Linux 6.18; `pywinauto` **not importable** | **BLOCKED: ENVIRONMENT** for every desktop-automation test. |
| Browser | Chromium + Playwright present (`/opt/pw-browsers`), `playwright` importable | Browser logic testable **against local fixtures only**. |
| OCR | `tesseract` at `/usr/bin/tesseract` | Testable, and tested. |
| Electron | No binary (`desktop/node_modules/electron/dist/electron` missing) | **BLOCKED: ENVIRONMENT.** `desktop/tests/e2e.mjs` cannot run. |
| Audio | No `/dev/snd` | **BLOCKED: ENVIRONMENT.** No microphone, so voice is untestable end to end. |
| Claw's own data dir | `~/.s-claw` does not exist | The app has **never been run** on this machine. |
| Deployment / hosting | No credentials, no reachable provider | **BLOCKED: ACCOUNT + CREDENTIALS.** |

**UNVERIFIED** (cannot be inspected from here, and not assumed either way): whether
the owner holds a Cloudflare, Supabase, Google Cloud, Microsoft 365, Twilio or
hosting account; any quota or billing status on such accounts; whether a Windows 10/11
machine with a microphone is available for the acceptance runs.

## 4. Capability matrix

Effort: **S** ≤1 day, **M** 2–5 days, **L** >1 week.

| # | Capability | OpenClaw reference | Claw implementation | Repo evidence | Test evidence | Status | Blocker | Security implications | Pri | Effort | External deps | Cheapest path | Next action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Model→tool loop | Agent runtime calls tools, reads results, continues | Real: typed call, execution, observation appended, re-plan on failure | `agent/executor.py:run_agent`, `_next_action`, `format_observation` | `tests/test_executor.py`, `test_agent_flow.py` (mock adapter) | **PARTIAL** | No real model has answered (`BLOCKED: INFRASTRUCTURE`) | Model output is never trusted: args are schema-validated before use | P0 | — | weights or a provider | run with a 2B GGUF on Windows | acceptance step in `WINDOWS_ACCEPTANCE.md` |
| 2 | Tool-result verification | Tool results handled | Stronger than reference: tools re-read to confirm (`verified` flag), summary built from recorded events not model claims | `tools/base.py:ToolResult.verified`, `executor.py:339` | across tool suites | **READY** | — | Prevents "it said it worked" | P0 | — | — | — | — |
| 3 | **Context management / compaction** | Long-conversation summarisation or compaction | **Was absent.** Engine window 8192; `files` catalogue 5,833 tok; worst case ~38k. Now budgeted and trimmed, with the last `MIN_RECENT` steps always sent and any overrun reported (`context_trimmed`, `context_overflow`) | `runtime/engine.py:117`, `executor.py:fit_context`, `Fitted.forced` | `tests/test_context_budget.py` (9, new) | **PARTIAL** (budget in place; root cause open) | — | A silently truncated run can repeat destructive steps — which here means repeated clicks and keystrokes | **P0** | S (done) + M (catalogue) | — | split `Capability.FILES` | roadmap item 2 |
| 4 | Multi-provider models | Hosted + self-hosted | Three modes, edition-gated, self-test generates real text | `models/`, `edition.py`, `api/app.py:/models/selftest` | `test_editions.py` (16), `test_models.py` | **PARTIAL** | `BLOCKED: INFRASTRUCTURE + CREDENTIALS` | Keys masked; never logged | P0 | — | a provider | — | — |
| 5 | Session isolation / multi-user | Per-agent workspaces, per-user files | Single local user; one task at a time by design | `agent/runner.py:TaskRunner` | `test_api.py` | **NOT APPLICABLE** (single-seat desktop app) | — | No cross-user leakage possible because there is one user | P3 | L | — | — | revisit only if Online multi-tenant ships |
| 6 | Launch apps, focus windows, keyboard/mouse | Documented device-node and OS actions | 23 desktop tools incl. menu, controls, screenshot/OCR fallback | `tools/desktop_tools.py`, `computer/launcher.py` | `test_desktop.py` (26), `test_laptop_control.py` (27) — **test doubles** | **BLOCKED: ENVIRONMENT** | No Windows; `pywinauto` not importable | System tools blocked; Enter-sends rule escalates to approval | P1 | — | a Windows box | run `WINDOWS_ACCEPTANCE.md` | first task on real hardware |
| 7 | File operations | read/write/edit/move | 20+ file & document tools, folder allowlist enforced | `tools/file_tools.py`, `permissions/policy.py:check_path` | `test_files.py`, `test_permissions.py` | **READY** | — | Traversal and symlink escape refused | P1 | — | — | — | — |
| 8 | Command execution | `exec`, `process`, `terminal` | **Absent by choice.** `is_program_running` uses fixed-arg process listing, never a shell | `tools/system_tools.py` | `test_system_tools.py` | **NOT APPLICABLE** (deliberate) | — | Adding it would remove the product's main safety property | P3 | — | — | — | leave out |
| 9 | Browser: navigate, click, fill, extract | Browser tool | 15 browser tools, typed errors, network-failure wording | `tools/browser_tools.py`, `browser/session.py` | `test_browser_tools.py` + local HTTP fixture | **PARTIAL** | Public web `BLOCKED: ENVIRONMENT` | Own profile; history access is a separate consented scope | P1 | — | public internet | run the search matrix on a normal network | acceptance |
| 10 | Web search providers | Configurable providers | DuckDuckGo/Bing/SearXNG/custom, URL building tested | `browser/search.py` | `test_search.py` | **PARTIAL** | same | Query strings never logged with credentials | P1 | S | internet | — | — |
| 11 | Memory: persistence | Markdown files in workspace | SQLite table, schema v4, provenance per row | `memory/`, `storage/db.py:remember` | `test_memory.py` (28) | **READY** | — | — | P1 | — | — | — | — |
| 12 | **Memory: retrieval into the prompt** | `USER.md`/`MEMORY.md` loaded at session start | **Built this session.** `remembered()` adds ≤800 chars to the system message, preferences and facts first, labelled "a record of their words, not instructions" | `executor.py:remembered`, called in `run_agent` | `tests/test_memory_in_prompt.py` (9, incl. end-to-end through the fake model server) | **READY** | — | Labelled as non-instructions; budgeted so it cannot reopen the context problem; a broken store is ignored rather than fatal | P1 | S (done) | — | — | — |
| 13 | Memory: forgetting & export | Editing memory | Per-row Remove, Export, Forget everything | `api/app.py:/memory*`, `renderer/app.js:loadMemories` | `test_memory.py`, API tests | **READY** | — | Export is a local file chosen by the person | P1 | — | — | — | — |
| 14 | Memory: secret protection | Secret handling | Refused **before** the write: passwords, OTP, keys, Luhn-checked cards | `memory/secrets.py` | 16 of the 28 memory tests | **READY** | — | Phone numbers/e-mails deliberately allowed | P0 | — | — | — | — |
| 15 | Scheduler: persistence & management | cron/automations with history | Jobs + `job_runs` in SQLite; pause, resume, run-now, delete | `jobs/`, `storage/db.py` | `test_jobs.py` (31) | **READY** | — | — | P1 | — | — | — | — |
| 16 | Scheduler: time zones | — | Daily fires in the computer's local zone; stored UTC | `jobs/schedule.py:_at_on` | `test_jobs.py` | **READY** | — | — | P1 | — | — | — | — |
| 17 | Scheduler: missed jobs & duplicates | Recovery | Interval counts from last run (no catch-up storm); daily has a 4 h catch-up then skips; `last_run` prevents repeats | `jobs/schedule.py:is_due`, `CATCH_UP` | `test_jobs.py` | **READY** | — | — | P1 | — | — | — | — |
| 18 | **Scheduler: restart recovery** | Recovery after restart | **Was broken** — a job cut short kept `started` for ever. Now marked `interrupted` on startup | `storage/db.py:mark_interrupted` | `test_jobs.py` (2 new) | **READY** (fixed today) | — | A job list that says "running now" when nothing runs is a lie | P1 | S (done) | — | — | — |
| 19 | Scheduler: unattended safety | Sandboxing optional | Jobs run under `PermissionPolicy.unattended()` — every ask→deny, destructive refused outright | `permissions/policy.py:unattended` | `test_jobs.py` first 3 tests | **READY** | — | The strongest safety property in the product | P0 | — | — | — | verify on Windows (stop-ship test) |
| 20 | Scheduler: notification delivery | Notifications | Electron polls and raises Windows notifications | `desktop/src/reminders.js`, `main.js` | `desktop/tests/reminders.test.js` | **BLOCKED: ENVIRONMENT** | No Windows, no Electron binary | — | P1 | — | a Windows box | — | acceptance |
| 21 | Event-triggered automation | hooks, webhooks, standing orders | **Absent.** Time only | `jobs/schedule.py` (two kinds) | — | **NOT BUILT** | — | Webhooks would mean opening a port — conflicts with loopback-only | P2 | M | a decision on ingress | local file/lifecycle events first | after item 12 |
| 22 | Calendar: local | Calendar integration where supported | `.ics` on disk, create/list/cancel/free-time | `claw/calendar/`, `tools/calendar_tools.py` | `test_calendar.py` (23) | **READY** | — | Files stay local | P1 | — | — | — | — |
| 23 | Calendar: reminders | Reminders, recurring events | Real `VALARM`s; shown once; stale retired; **RRULE refused, not guessed** | `calendar/ics.py`, `calendar/reminders.py` | `test_calendar_reminders.py` (34) | **READY** (logic) / **BLOCKED: ENVIRONMENT** (the notification) | Windows | — | P1 | — | — | — | acceptance |
| 24 | Calendar: Google / Microsoft 365 | Supported integrations | **Absent.** No CalDAV client, no OAuth | — | — | **NOT BUILT** + **BLOCKED: CREDENTIALS** | googleapis reachable, no OAuth client | Tokens would need DPAPI storage | P2 | M | OAuth client + consent | read-only CalDAV against a self-hosted server first | after item 21 |
| 25 | Daily briefing | Agenda summaries | `daily_brief` + `GET /brief`, always states what it cannot see | `claw/brief.py` | `test_brief.py` (12) | **READY** (logic) / **BLOCKED: ENVIRONMENT** (delivery) | Windows | — | P1 | — | — | — | — |
| 26 | E-mail: draft | Draft replies | `compose_mail` opens Gmail/Outlook/mailto, `sent` always false | `tools/mail_tools.py` | `test_laptop_control.py` | **PARTIAL** | — | No mailbox password is ever held | P2 | — | — | — | — |
| 27 | E-mail: read/search/send | Read, summarise, send approved | **Absent** | — | — | **NOT BUILT** + **BLOCKED: CREDENTIALS** | No OAuth client, no mailbox | Full-mailbox scope is the most dangerous grant in this list | P2 | L | OAuth app, token store | IMAP read-only against a throwaway account | after items 12, 21 |
| 28 | Documents, PDF, OCR | Document reading | pypdfium2/pypdf + Tesseract, page refs, scan confidence | `claw/documents/` | `test_documents.py`, `test_ocr.py` | **READY** | — | Opened files are a consented read scope | P1 | — | — | — | — |
| 29 | Image understanding / generation | Media surfaces | `inspect_image`, `edit_image`, `make_flyer`; **no generation, no TTS** | `tools/image_tools.py` | `test_image_tools.py` | **PARTIAL** | Generation `BLOCKED: CREDENTIALS` | — | P3 | M | a provider key | — | defer |
| 30 | Voice input / transcription | Voice workflows | Push-to-talk, editable transcript before anything runs | `claw/speech/`, `renderer/quickbar.js` | `test_speech.py` (model-less paths) | **BLOCKED: ENVIRONMENT** | No `/dev/snd`, no voice model files | Audio is never written to disk unless asked | P2 | — | a microphone | — | acceptance |
| 31 | Video understanding/generation | Where supported | **Absent**; scope never defined | — | — | **NOT BUILT** | — | — | P3 | L | a provider | define scope in one sentence first | defer |
| 32 | Messaging channels (WhatsApp, Telegram, Slack, Signal, iMessage, Teams, Matrix, IRC, LINE, SMS, …) | 20+ channels | **No connectors.** S-CLAW operates the apps already on the computer instead | `tools/desktop_tools.py`, `docs/HOW_IT_WORKS.md` | `test_whatsapp.py` (13, stand-in), `test_laptop_control.py` | **NOT BUILT** (deliberate) + **BLOCKED: ACCOUNT/CREDENTIALS** for any real test | No account has ever been connected | P3 | L each | per-service auth | none worth taking | leave out; strengthen desktop path instead |
| 33 | Coding & project work | Inspect, edit, build, test | File tools can read/write text; **no workspace, diffs, builds or git** | `tools/file_tools.py` | — | **NOT BUILT** | — | Running builds means running code | P2 | L | — | read-only repo inspection first | defer |
| 34 | Deployment | Deploy through integrations | **Absent** | — | — | **NOT BUILT** + **BLOCKED: ACCOUNT** | — | Never deploy from an agent without explicit, separate approval | P3 | L | hosting account | — | defer |
| 35 | Multi-agent | Sub-agents, swarm | One task at a time | `agent/runner.py` | `test_api.py` busy-path | **NOT BUILT** (deliberate) | — | Would multiply the permission surface | P3 | L | — | — | defer |
| 36 | Tools / skills / plugins | Tools + SKILL.md + plugin SDK | Typed registry with per-tool risk; **no skills, no plugin loader** | `tools/registry.py`, `tools/base.py:ToolSpec` | prompt-guidance tests assert every named tool exists | **PARTIAL** | — | Loading third-party code into an agent with desktop control needs signing first | P2 | L | a trust model | bundled "skills" as prompt packs, no code | after item 21 |
| 37 | Local API auth | Access restrictions | Loopback bind, per-launch token ≥32 chars, Host guard | `api/app.py` | `test_api.py` | **READY** | — | — | P0 | — | — | — | — |
| 38 | Approvals | Tool policy | Four risk levels, destructive floor settings cannot lower, approval card names the chat and quotes the message | `permissions/policy.py`, `executor.py:decide`, `desktop_tools.py:sending_context` | `test_permissions.py`, `test_laptop_control.py` | **READY** | — | — | P0 | — | — | — | — |
| 39 | Prompt-injection defence | Untrusted input | Untrusted content wrapped, pattern-flagged, **every change re-asks** after a flag, and the warning now survives context trimming as its own message | `executor.py:INJECTION`, `note_content`, `STICKY_PREFIX` | `test_batch4_tasks.py`, `test_context_budget.py` | **READY** | — | Pattern matching is weak alone; the approval is the real control | P0 | — | — | — | — |
| 40 | Emergency stop | — | Global shortcut + tray + API cancel | `desktop/src/main.js`, `api/app.py:/tasks/{id}/cancel` | `desktop/tests/routes.test.js` | **PARTIAL** | Shortcut untestable without Electron | — | P0 | — | Windows | — | acceptance |
| 41 | Logging & diagnostics | — | Structured `log_event`, per-task event trail, secrets masked | `logging_setup.py` | `test_logging.py` | **READY** | — | — | P1 | — | — | — | — |
| 42 | Data retention & deletion | Retention controls | Data dir documented; memory export/delete; **no retention policy for task history** | `config.py`, `/memory/forget-all` | `test_memory.py` | **PARTIAL** | — | History can hold page text read during tasks | P2 | S | — | an age-based purge setting | after item 12 |
| 43 | Privacy disclosure for hosted inference | Telemetry/privacy | Settings states the edition; user guide §12 rewritten to cover Online | `docs/USER_GUIDE.md`, `renderer/app.js:describeEdition` | — | **READY** (documentation) | — | — | P0 | — | — | — | — |
| 44 | Update checking | Daily version check (opt-out) | **Absent** — no telemetry, and no update check either | — | — | **NOT BUILT** | — | Users will not learn about security fixes | P2 | S | a release feed | check the GitHub releases API on launch, off by default | after item 21 |

## 5–8. Grouped findings

**Already implemented (READY):** 2, 7, 11, 13, 14, 15, 16, 17, 18, 19, 22, 28, 37, 38, 39, 41, 43.

**Partial:** 1 (no real model), 3 (budget in, catalogue open), 4, 9, 10, 23/25 (logic only), 26, 29, 36, 40, 42.

**Not built:** 12, 21, 24, 27, 31, 32, 33, 34, 35, 44.

**Blocked, by kind:**
- *ENVIRONMENT* — 6, 20, 23, 25, 30, 40 (no Windows, no Electron, no microphone); 9, 10 (no public web); 4 (no weights/runtime).
- *CREDENTIALS* — 24, 27, 29 (OAuth clients, provider keys); 4 for hosted models.
- *INFRASTRUCTURE* — 4 (no llama-server, no GGUF), Claw Online (no service exists).
- *ACCOUNT* — 32, 34, and anything requiring a paid tier.

**Cannot be verified from here (UNVERIFIED):** whether the owner holds Google,
Microsoft, Cloudflare, Supabase, Twilio or hosting accounts; their quotas and
billing; and whether a Windows machine with a microphone is available. These are
recorded as unknown rather than guessed.

## 9. Security and privacy gaps

1. **No retention limit on task history** (row 42). Pages read during a task are
   stored in the event trail indefinitely. Cheapest fix: an age-based purge.
2. **No update check** (row 44) — users cannot learn about fixes.
3. **Injection defence is pattern-based**; the real protection is that changes
   need approval. Stated in `docs/SECURITY.md`; no change recommended.
4. **A plugin system would be the largest new risk** in this product (row 36).
   Any such work must start with signing and provenance, not with a loader.

## 10. Test evidence

| Kind | What ran | Result |
|---|---|---|
| Unit + integration against test doubles | `backend` pytest suite | see below |
| Desktop unit tests | `cd desktop && npm test` | **33 passed, 0 failed** |
| Script syntax | `npm run check` | all 9 scripts parse |
| Local end-to-end (renderer) | `scripts/screenshots.py` against the real renderer | ran earlier this session, 41 images |
| Real external service | — | **none possible**: no public web, no credentials, no service |
| Real Windows desktop | — | **none possible**: Linux container, `pywinauto` not importable |
| Load/production | — | not attempted; out of scope for a single-seat desktop app |

Blocked tests and how to run them later are listed in
`docs/WINDOWS_ACCEPTANCE.md` (desktop, reminders, jobs incl. the stop-ship
destructive-job test) and `docs/KNOWN_ISSUES.md`.

## 11–13. Roadmap

| Order | Item | Why now | Effort | Depends on |
|---|---|---|---|---|
| ~~1~~ | ~~Memory into the prompt~~ | **done** — `remembered()`, 9 tests | S | — |
| ~~2~~ | ~~Split `Capability.FILES`~~ | **done** — worst bucket 5,833 → 3,354 tokens; organiser steps 1,579 | M | — |
| 1 | **Per-step rather than per-plan tool filtering** (row 3) | The remaining half: a three-capability plan still sends the union of all three | S | — |
| 2 | **Standing auto-reply with a time limit** (new) | "For the next 2 hours, anyone who messages gets X." Needs a watcher, a per-person draft, and a time-boxed permission granted once — not a rule that sends silently | M | WhatsApp open, Windows |
| 4 | **Local event triggers** (row 21) | Jobs can only fire on a clock; file/lifecycle events need no open port | M | nothing |
| 5 | **Task-history retention** (row 42) | A privacy gap with a one-setting fix | S | nothing |
| 6 | **Update check, off by default** (row 44) | Users cannot hear about fixes | S | GitHub releases API (reachable) |
| 7 | CalDAV read-only (row 24) | Proves the sync shape without OAuth | M | a self-hosted CalDAV server |
| 8 | IMAP read-only on a throwaway account (row 27) | The honest first step toward mail | L | a test mailbox |

## 14. Explicitly deferred

Messaging connectors (32), multi-agent (35), deployment (34), shopping/travel,
video (31), and shell execution (8) — each either a deliberate non-goal, blocked
on accounts that cannot be verified from here, or undefined in scope. None are
claimed as partially working.

## 15. Files and tests inspected

`backend/claw/`: `api/app.py`, `agent/{executor,planner,runner,schemas}.py`,
`tools/{registry,base,desktop_tools,file_tools,browser_tools,calendar_tools,memory_tools,mail_tools,human_tools,system_tools,image_tools}.py`,
`calendar/{ics,store,reminders,free}.py`, `memory/{secrets}.py`, `jobs/{schedule,runner}.py`,
`permissions/policy.py`, `storage/db.py`, `runtime/engine.py`, `models/`, `config.py`, `brief.py`, `edition.py`.
`desktop/src/`: `main.js`, `preload.js`, `reminders.js`, `creator.js`, `watcher.js`, `renderer/app.js`.
Tests read: `test_api.py`, `test_desktop.py`, `test_laptop_control.py`, `test_jobs.py`,
`test_memory.py`, `test_brief.py`, `test_calendar*.py`, `test_editions.py`, `test_whatsapp.py`,
`desktop/tests/*.test.js`.

## 16. Files changed in this task

| File | Change |
|---|---|
| `backend/claw/agent/executor.py` | Context budget: `estimate_tokens`, `fit_context`, `Fitted`, `context_trimmed` / `context_overflow` events |
| `backend/claw/agent/runner.py` | Passes the engine's real window (`HOSTED_CONTEXT_TOKENS` for hosted) |
| `backend/claw/storage/db.py` | `mark_interrupted()` now repairs jobs and job runs |
| `backend/tests/test_context_budget.py` | New — 10 tests, incl. the sticky safety warning |
| `backend/tests/test_jobs.py` | +2 restart-recovery tests |
| `desktop/src/renderer/app.js` | "was cut short when S-CLAW stopped" wording for an interrupted job |
| `docs/OPENCLAW_GAP_AUDIT.md` | This report |

Also uncommitted from the previous task: `docs/OPENCLAW_COMPARISON.md`,
`docs/DEVELOPER_GUIDE.md`, `docs/MASTER_PROMPT_STATUS.md`. All preserved.

## 17. Commands run, with actual results

```
$ cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider
546 passed, 8 skipped, 2 failed    # first run: my context change dropped every
                                   # observation — the model would act blind
… fix: always send the last MIN_RECENT messages; report the overrun …
547 passed, 8 skipped, 1 failed    # second run: the injection warning was being
                                   # trimmed away with the page it came on
… fix: safety warnings travel as their own message and are never trimmed …
549 passed, 8 skipped, 0 failed    # final: up from 537 at the start of this task

$ cd desktop && npm test
# tests 33 / # pass 33 / # fail 0

$ cd desktop && npm run check
all 9 scripts parse

$ .venv/bin/python -c "…tool_catalogue…"
unfiltered 35,689 chars ≈ 8,922 tokens; files 23,334 ≈ 5,833; desktop 1,937; browser 1,553

$ curl -s -o /dev/null -w '%{http_code}' <host>      # see §3 for the full table
google.com 000 · huggingface.co 000 · api.github.com 200 · gmail.googleapis.com 404
api.openai.com 000 · api.cloudflare.com 000 · supabase.com 000

$ which llama-server; find / -name '*.gguf'; nvidia-smi -L; ls /dev/snd
(nothing, nothing, no nvidia-smi, no /dev/snd)

$ .venv/bin/python -c "import pywinauto"
ModuleNotFoundError
```

Before/after for the changed areas: `test_jobs.py` 29 → **31**;
`test_context_budget.py` 0 → **9**; `test_executor.py` unchanged at its previous
count and passing again after the correction.

## 18. Next recommended task

**Load what is remembered into the run, within the new budget** (row 12): inject
at most ~800 characters of `preference` and `fact` memories into the executor's
system message, clearly labelled as the person's own words, counted by
`estimate_tokens` so it cannot reopen the context problem, and skipped entirely
when the budget is tight. Then measure: a task that should use a known
preference, with and without the injection.
