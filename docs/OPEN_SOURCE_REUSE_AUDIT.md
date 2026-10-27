# Open-source reuse audit — S-CLAW, 27 October 2026

Eight upstream projects inspected against demonstrated gaps. **One dependency
was added: none.** Three upstream ideas were adapted, one library that is
already a dependency was leaned on harder, and four candidates were rejected
with reasons. Two defects were found on the way.

Research note: `docs.openclaw.ai` and `api.github.com/repos/…` are blocked from
this container, so every fact below comes from a file fetched on 27 Oct 2026
from `raw.githubusercontent.com`, `pypi.org/pypi/<name>/json`, or
`registry.npmjs.org/<name>` — primary sources, quoted where it matters.

## 1. State of the S-CLAW features this touches

| Feature | Before today | Verified by |
|---|---|---|
| Tool catalogue sent to the model | capability-filtered, but schemas rendered as raw JSON Schema | `agent/executor.py:tool_catalogue` |
| Context budget | added earlier today: trim, keep recent, report overrun | `tests/test_context_budget.py` |
| Memory | stored, listed, exported; injected into the prompt earlier today, ordered by kind then date | `tests/test_memory_in_prompt.py` |
| Desktop control targeting | **by index only** — "control 7 from the last look" | `tools/desktop_tools.py:_control` |
| WhatsApp | reads chat names + unread counts through UI Automation; **no message identifiers exist on that surface** | `integrations/whatsapp.py:parse_chat_list` |
| Scheduler | SQLite jobs, interval + daily, catch-up, restart recovery, unattended policy | `tests/test_jobs.py` (31) |

## 2. Repositories inspected

| Project | Licence (verified) | Version / last release | How checked |
|---|---|---|---|
| pywinauto/pywinauto | **BSD-3-Clause** (`LICENSE`: "Copyright (c) 2017, Mark Mc Mahon and Contributors") | 0.6.9, 2025-01-06 | PyPI JSON + raw `LICENSE`, `findbestmatch.py`, `timings.py` |
| wwebjs/whatsapp-web.js | **Apache-2.0** | 1.34.7, 2026-04-24 | npm registry + raw `README.md` |
| WhiskeySockets/Baileys | **MIT** ("Copyright (c) 2026 Rajeh Taher/WhiskeySockets") | 7.0.0-**rc14**, 2026-07-29 | npm registry + raw `README.md` |
| oxgeneral/agentmem | **MIT** (PyPI metadata blank; `LICENSE` file confirms) | 0.3.0, 2025-04-14 | PyPI JSON + raw `LICENSE`, `README.md` |
| agronholm/apscheduler | **MIT** | 3.11.3, 2026-06-28 | PyPI JSON |
| microsoft/OmniParser | **MIT** code; weights differ (below) | — | raw `LICENSE`, `README.md` |
| browser-use/browser-use | **MIT** ("Copyright (c) 2024 Gregor Zunic"; PyPI metadata blank) | 0.13.14, 2026-10-26 | PyPI JSON + raw `LICENSE` |
| openclaw/openclaw | **MIT** | 2026.10.7 | raw `package.json`, docs (see `docs/OPENCLAW_COMPARISON.md`) |

## 3–4. What was considered, and the verdict

### pywinauto — `pywinauto/findbestmatch.py` → **ADAPT A SMALL MODULE**

`find_best_match(search_text, item_texts, items, limit_ratio=.5)` scores every
candidate with `difflib.SequenceMatcher.ratio()` after cutting each label at the
first tab or newline, and raises rather than return a poor match.

S-CLAW could only target a control **by number from the last look**, which moves
whenever the window does. `match_control()` in `tools/desktop_tools.py` now
takes a name, using exactly that approach, and `click_control`, `type_into` and
`read_control` accept `name` as well as `number`.

*Adapted, not imported*, for one reason: `pywinauto` is `sys_platform ==
"win32"` in `requirements.txt`, while this logic must behave identically on the
Linux test desktop. Importing it would mean two code paths and only one of them
tested. BSD-3 attribution is in the module docstring and
`THIRD_PARTY_NOTICES.md`.

One judgement the upstream algorithm does not make, added here: when the best
and second-best are within **0.15**, it asks instead of choosing. Measured on a
chat-like window, a genuine match beats its rival by 0.55–0.74, while "Send"
against "Send now" / "Send later" differ by 0.10 — near-identical labels with
very different consequences.

### whatsapp-web.js and Baileys → **INCOMPATIBLE** (both)

Evaluated separately, as asked.

- **whatsapp-web.js** (Apache-2.0) drives WhatsApp Web through **puppeteer**,
  which downloads its own Chromium. Its README states plainly: *"it is not
  guaranteed you will not be blocked by using this method. WhatsApp does not
  allow bots or unofficial clients on their platform, so this shouldn't be
  considered totally safe."*
- **Baileys** (MIT) speaks the protocol directly via `ws`, `libsignal` and
  `protobufjs` — no browser, far lighter. But its README says the maintainers
  *"do not in any way condone the use of this application in practices that
  violate the Terms of Service of WhatsApp"* and *"discourage any stalkerware,
  bulk or automated messaging usage"* — which is the use being considered. The
  current release is a **release candidate** (7.0.0-rc14).

Both would also be the first **runtime npm dependency** in this product:
`desktop/package.json` currently has `"dependencies": {}`. Neither is worth the
person's WhatsApp account, and neither can be tested here (no session, no
Windows, no public web).

**Taken instead:** `claw/integrations/standing_reply.py` — the requested
feature, draft-only. It is the honest fallback the brief allows.

### agentmem → **USE AS A REFERENCE**

MIT, so reuse would have been permitted. Its README describes the useful shape:
*"Hybrid search: FTS5 full-text keywords + vector semantic search, fused with
adaptive ranking"*, *"Importance scoring … by tier"*, *"Recency boost … with
configurable decay"*.

Its implementation is not usable here: PyPI lists `sentence-transformers` and
`chromadb` as hard requirements, which means a PyTorch stack inside a Windows
installer, to rank a few dozen short sentences. The *shape* is adapted in
`executor.py:_relevance` — kind weight (its "tier"), keyword overlap (its
FTS5 half), and a small recency bonus — with the source credited in the
docstring.

### APScheduler → **UNNECESSARY — EXISTING CODE IS SUFFICIENT**

Compared feature by feature against `claw/jobs/`:

| Need | APScheduler | S-CLAW today |
|---|---|---|
| Interval + daily schedules | `IntervalTrigger`, `CronTrigger` | `Schedule.parse`, two kinds, deliberately no cron |
| Persistence | job stores (SQLAlchemy, Mongo…) | `jobs` + `job_runs` tables, schema v4 |
| Missed runs | `misfire_grace_time`, `coalesce` | `CATCH_UP` (4 h) for daily; interval counts from last run |
| Restart recovery | job store reload | `mark_interrupted()` (fixed earlier today) |
| Time zones | `tzlocal` dependency | local zone via `astimezone`, stored UTC |
| Duplicate prevention | `max_instances` | `last_run` + the single-task runner |

Migrating would add a dependency (plus `tzlocal`), move job state into a second
store, and buy cron syntax — which was left out on purpose, because a cron line
nobody can read is a schedule nobody can check. **No change.**

### OmniParser → **INCOMPATIBLE (for now)**

Code is MIT, but the README is explicit that weights differ: *"Earlier
Ultralytics-based icon detectors retain their original AGPL license."* It needs
a GPU-class model to parse screenshots into controls. S-CLAW reads the
accessibility tree, which is faster, exact, and needs no model; OCR is already
the fallback. Worth revisiting only if UI Automation proves unreadable on real
Windows — which `docs/WINDOWS_ACCEPTANCE.md` will establish.

### browser-use → **INCOMPATIBLE**

MIT, actively released (0.13.14, yesterday). But PyPI shows hard pins —
`aiohttp==3.14.5`, `anyio==4.12.1`, `bubus==1.5.6` — plus `anthropic` and
`browser-use-sdk`, i.e. a second agent framework with its own model clients
inside ours. S-CLAW already drives Playwright directly with its own approval
layer. Nothing to import without importing an architecture.

### openclaw → **USE AS A REFERENCE** (done separately)

`docs/OPENCLAW_COMPARISON.md`. Its `tool_search` / `tool_describe` design
informed today's catalogue work, but was not needed: compacting the schemas was
enough.

## 5. Dependency and installer impact

**None.** `backend/requirements.txt` and `desktop/package.json` are unchanged.
Everything added uses the standard library (`difflib`, `json`, `re`) or code
already present. `THIRD_PARTY_NOTICES.md` gains an attribution for the
pywinauto-derived matching approach.

## 6. Risks

- **WhatsApp.** No automatic sending exists, and none should be added on the
  current signal: the accessibility surface has no message identifiers, so
  "reply to the new message" can only ever mean "reply because the unread count
  moved". Deduplication here is therefore per chat per window, not per message.
  Any future unattended sending needs its own authorisation, its own disclosure,
  and an honest account of the ToS risk quoted above.
- **Name-based control targeting** could click the wrong thing if two labels are
  close. That is why near-ties refuse rather than guess, and why the existing
  approval — which names the chat and quotes the message — still stands in front
  of every send.
- **Compact tool schemas** remove `maxLength` and friends *from what the model
  sees*. Every limit is still enforced by the same Pydantic models, and a
  rejected call comes back as a validation error the model can correct.
- **Privacy.** The standing reply stores chat names and timestamps, never
  message text — a test asserts it.

## 7. Tests

| Suite | Result |
|---|---|
| `tests/test_tool_catalogue.py` (new) | 9 passed |
| `tests/test_control_matching.py` (new) | 9 passed |
| `tests/test_standing_reply.py` (new) | 26 passed |
| `tests/test_memory_in_prompt.py` (+3 ranking) | 12 passed |
| `tests/test_desktop.py`, `test_laptop_control.py`, `test_whatsapp.py` | 66 passed |
| Full backend suite | **606 passed, 8 skipped, 0 failed** (from 559) |
| Desktop (`npm test`) | 33 passed, 0 failed |

All of these are unit or test-double tests. **No live test was possible**: no
Windows desktop, no WhatsApp session, no model weights, no public web. Nothing
below the line was simulated and reported as real.

## 8. Before and after — context tokens

Measured with `estimate_tokens(tool_catalogue(...))`, same method throughout:

| Catalogue | This morning | After the capability split | After compact schemas |
|---|---|---|---|
| Everything (no filter) | 8,922 | 8,922 | **4,214** |
| `files` | 5,833 | 3,354 | **1,474** |
| `documents` | (inside files) | 2,393 | **940** |
| `organiser` (calendar, memory) | (inside files) | 1,579 | **917** |
| `desktop` | 1,937 | 2,215 | **1,169** |
| `browser` | 1,553 | 1,775 | **930** |

Against the built-in engine's 8,192-token window with 1,024 reserved for the
reply: a file-handling step went from ~1,300 tokens of working room to ~5,700.

Two defects found while doing it:

1. **`_strip_titles` deleted any argument called `title`.** It removed JSON
   Schema's `title` annotations at every level — including the key inside
   `properties`. Ten tools have such an argument, and `create_event`
   **requires** it, so the model was asked for an argument it was never shown.
   Fixed; two tests pin it.
2. Measured rather than assumed: descriptions across all 76 tools are 5,421
   characters, their argument schemas 27,046. Five sixths of the catalogue was
   boilerplate.

## 9. Remaining blockers, and the cheapest next step

| Blocked | Why | Cheapest step |
|---|---|---|
| Any real WhatsApp behaviour | no session, no Windows; and the libraries that would give message ids are unofficial | run the standing reply draft-only on a real machine with a **test account**, and check what the chat list actually exposes |
| Control matching against real apps | `pywinauto` cannot import here | `docs/WINDOWS_ACCEPTANCE.md`, now with a name-targeting step |
| Everything model-related | no weights, no provider, no service | a 2B GGUF on a Windows laptop |

**Next step, cheapest and most valuable:** put the standing reply in front of a
person — a small Settings panel that shows which WhatsApp window it is for, the
expiry counting down, the drafts waiting, and a Stop button. The rules are
tested; what is missing is the surface, and without it the feature cannot be
used or audited by the person it belongs to.

## Change control

Branch `claude/ecstatic-ritchie-x6ao14`, nothing committed, pushed, published or
deployed as part of this task. No branch changes. No existing work was reset or
overwritten.
