# Follow-up run — 27 October 2026 (open-source evaluation and integration)

Continues `docs/TEST_RUN_2026-10-27.md`. Same container, same four limits: no
Windows desktop, no reachable model weights, no provider credentials, no public
internet.

**Backend suite: 369 passed, 8 skipped, 0 failed (3m52s).** The 8 skips are the
seven real-`llama-server` engine tests (no engine binary here) and one
screenshot test that needs a display — unchanged, and for the same reasons.

---

## What was researched, and how

39 open-source projects were checked against the repository itself — not against
a search result. `api.github.com` is refused by this container's egress proxy
(403), but `raw.githubusercontent.com`, `pypi.org` and `registry.npmjs.org` are
reachable, which is enough for the two things that matter most:

- **existence and licence** — the project's own `LICENSE` file, fetched and read;
- **maintenance** — the latest release on PyPI or npm, with its upload date.

All 39 were reached. Full table with decisions and reasons:
`docs/OPEN_SOURCE_EVALUATION.md`.

**Three licences were classified wrongly by the automatic matcher and corrected
by hand.** This is the part worth keeping:

| Project | Automatic guess | Actually |
|---|---|---|
| remotion-dev/remotion | MIT | the **Remotion License** — not OSI; paid above a company-size threshold |
| OHF-Voice/piper1-gpl | AGPL-3.0 | **GPL-3.0** |
| yacy/yacy_search_server | none found | **GPL-2.0**, in `gpl.txt` rather than `LICENSE` |

Had the matcher's output been used directly, Remotion would have entered a
commercial product under a licence it does not have.

## What was decided

Nothing about the engine, the browser driver, the Windows library or the speech
engine changes: **llama.cpp, Playwright, pywinauto and sherpa-onnx are already
the right components** and are already here. The 27 October gaps are a missing
desktop, missing weights, missing credentials and missing internet, and no
dependency fixes any of those.

Adopted or planned, in order of value:

1. **A search-provider interface** — implemented today (below).
2. **LiteLLM** (MIT) as the Claw Online gateway, when there is a server to host.
   It removes the per-user API key; it does not remove the compute bill.
3. **CalDAV** written against the protocol, with Radicale (GPL, separate
   process) as a local test fixture.
4. **Silero VAD** (MIT) or sherpa's own, when voice work resumes.
5. **MarkItDown** (MIT), after its dependency tree is read.

Rejected on licence grounds alone: Remotion, PyMuPDF (AGPL-or-pay), piper1-gpl
(GPL), wppconnect (LGPL), Firecrawl (AGPL server). Rejected as redundant or
unverifiable: LocalAI, TGI, browser-use (it owns an agent loop Claw already has),
and two single-author Windows agents whose quality could not be checked at all.

## What was implemented

### A search-provider interface (Priority 3)

`claw/browser/search.py`. The engine is now a value, not a hard-coded branch:
each provider carries how to build its query URL, how to read its result layout,
and what to tell the user. Four providers: DuckDuckGo, Bing, **a SearXNG server
of the user's own**, and a custom address.

SearXNG is reached over HTTP as a separate service. It is **AGPL-3.0**, so Claw
talks to it and never bundles or links it — and it is not a source of internet
access: it needs its own.

| Test | Result |
|---|---|
| Each provider builds its own address; `/search` typed twice does not double | PASS |
| An unknown engine is refused; a custom address without `{query}` is refused | PASS |
| Choosing SearXNG without an address is refused by settings validation | PASS |
| A real search against a real local search page returns parsed results | PASS |
| A layout Claw cannot read falls back to the page's links, and never presents the search host's own navigation as results | PASS |

### Evidence on every search result (Priority 3, item 4)

`web_search` now records the provider, the result page's URL and title, the HTTP
status, the time it was fetched and how long it took. Without that, a stale
answer looks exactly like a fresh one.

### What was *not* implemented, and why

- **No new runtime dependency was installed.** Every candidate above would enter
  a signed Windows installer; adding one on a Linux container that cannot build
  or test that installer would be adding risk I could not measure.
- **No hosted inference gateway was built.** LiteLLM is the right choice, but a
  gateway with no server, no compute and no budget is a configuration file
  pretending to be a service.
- **No WhatsApp library was adopted.** All three are a terms-of-service risk to
  the user's account; that is the user's decision, not mine.

## Verdicts

`docs/CAPABILITY_MATRIX.md` carries one line per capability with PASS /
MOCK-ONLY / BLOCKED / FAIL / NOT IMPLEMENTED and the evidence for each.

Unchanged and still true: **no real model has answered, in either edition; no
Windows desktop has run the acceptance tests; no public search has been made.**
Research does not move any of those, and none of them is reported as moved.

## Documents written or updated today

| File | What it is |
|---|---|
| `docs/OPEN_SOURCE_EVALUATION.md` | 39 projects, verified, with a decision and a reason each |
| `docs/CAPABILITY_MATRIX.md` | every capability with a verdict and its evidence |
| `docs/WINDOWS_ACCEPTANCE.md` | the tests that need Windows, a microphone or internet, written to be handed to someone who has them |
| `docs/SECURITY.md` | the model never acts; what enforces that, and the known weaknesses |
| `docs/KNOWN_ISSUES.md` | the four environmental blockers, and the newly untested parts |
| `docs/EDITIONS.md` | Claw Online and Claw Local (written earlier today) |
