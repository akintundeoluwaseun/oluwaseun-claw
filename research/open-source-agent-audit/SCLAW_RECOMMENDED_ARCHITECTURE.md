# SCLAW_RECOMMENDED_ARCHITECTURE.md

The user's constraint, verbatim:

> *"I do not want six different AI frameworks running together. I want one coherent application
> with carefully selected components."*

This document answers that. **Nothing here is implemented.** It is a proposal awaiting
approval.

---

## 1. The headline recommendation: keep S-CLAW's architecture

**S-CLAW's existing architecture is the right one and should not be replaced.**

Electron 45 shell · Python 3.13 FastAPI on `127.0.0.1` with a per-launch token ·
`llama.cpp` `llama-server` for the local brain · Playwright + Chromium for the web ·
pywinauto/UIA for the desktop · SQLite for state · PyInstaller + electron-builder +
Inno Setup 6 for the installer.

Three independent reasons from this audit:

1. **OpenHands, the only one of the six built the same way, validates the shape.** It is
   Electron + a local Python backend + `127.0.0.1:8000` + a session API key the launcher
   persists on first run. Same design, arrived at independently. (`PROJECT_ANALYSIS.md` §6)
2. **No project surveyed is comprehensively good.** The capability matrix in
   `PROJECT_COMPARISON.md` §2 shows no project holding more than about a third of the useful
   techniques. There is nothing to adopt wholesale because nothing is comprehensively better.
3. **S-CLAW is already ahead of the field in several specific places** — verified, not assumed:
   it probes `/props` for the served context window and logs asked-vs-actual
   (`openai_compat.py:68`, `runner.py:228`); it passes `trust_env=False` on every HTTP client,
   which is a stronger fix than Eigent's `NO_PROXY` patch; it already repairs model JSON with
   attribution (`jsonfix.py` + `OPENCLAW_LICENSE.txt`); and it keeps capability and risk on
   two separate axes, which is exactly what OpenClaw's `model-inference-capabilities.ts`
   comments insist on.

**So the proposal is additive.** Named seams inside the architecture S-CLAW already has. No
new framework, and — for the top items — no new dependency.

---

## 2. What to add, and where

Twelve additions. For each: the S-CLAW module it belongs in, the size, and the dependency cost.

### Tier 1 — safety and unbounded-cost failures (do these first)

#### 1. Turn taint → `backend/claw/agent/` + `backend/claw/permissions/policy.py`
**~65 lines. No new dependency.** From `openclaw/packages/agent-core/src/turn-taint.ts`.

Mark a tool result with where its content came from. When that source is untrusted — a web
page, a downloaded file, a plugin's output, the clipboard — the turn becomes **tainted**, and
the taint propagates forward onto assistant messages until the next *user* message clears it.

Then one rule in `PermissionPolicy`:

> Once the current turn is tainted, an EXTERNAL or DESTRUCTIVE action requires fresh
> confirmation, regardless of any standing approval.

**Why this is first.** S-CLAW browses the web and reads files on a user's real machine with a
2B model, which is *more* susceptible to injected instructions than a large one, not less.
S-CLAW's standing rules already say to treat web pages and files as untrusted — but there is
currently no mechanism that *knows* a given turn read one. Without it, a standing "yes, you
may write files" covers an action the user never intended. This is the gap between a stated
policy and an enforced one.

**Implementation notes.** Read the taint metadata strictly: only a literal `"network"` source
and a literal `True` flag count, so injected content cannot forge a *clean* state. Extend
beyond `"network"` to every untrusted source S-CLAW has. Scan backwards for the nearest
boundary, and treat a user message as clean.

#### 2. Derive the catalogue budget from the probed window → `backend/claw/agent/executor.py`
**A fix, not a feature. No new dependency.**

Verified defect. `executor.py:1048` sets `CATALOGUE_BUDGET = 1800` and `:1053`
`FULL_CATALOGUE_BUDGET = 4800` as **absolute constants**. Meanwhile `fit_context(messages,
window_tokens)` at `:1207` correctly budgets the message history from the *probed* window
(`:1234`). The two never meet. On a server that actually serves 2048 tokens — which
`openai_compat.py`'s own docstring says happens when llama.cpp clamps `-c` down to the model's
trained context — the catalogue alone claims 1800 of 2048, 88%, while `fit_context`
independently hands out `2048 - reserve` to the conversation.

Fix: express both budgets as a fraction of `window_tokens`, calibrated so that the present
constants are what an 8192 window produces. Then a smaller window shrinks the catalogue
instead of overcommitting. Keep `MIN_DETAILED` and `MIN_NAMED` as floors — and note this area
has bitten before: catalogue name-trimming once stepped by 5 past its `MIN_NAMED` floor and
produced 23 instead of 25.

This is Hermes' `_clamp_compressor_to_ollama_num_ctx` discipline (`MODEL_INTEGRATION.md` §2)
applied to the budget S-CLAW has that is not yet clamped.

#### 3. Repetition guard → `backend/claw/agent/` (new module)
**~110 lines. No new dependency.** Port from `hermes-agent/agent/repetition_guard.py` (Python,
MIT) — the upstream, not OpenClaw's TypeScript derivative.

A model in a degenerate loop spends its entire output budget echoing one fragment. Hermes'
own docstring records the incident: *"a 60k-char turn delivered as 31 Discord messages."* It is
unbounded in both tokens and wall-clock, and it is a plausible contributor to the user's
reports of errors and extreme slowness.

Three details that make the Hermes version worth porting rather than writing fresh:

- **`MIN_FRAGMENT_LENGTH = 400`** — the check does not run on short output, because *"short
  truncations trivially contain repeated tokens and are legitimately continued."*
- **The lists/tables false-positive guard.** If most lines are *distinct*, it is not a loop.
  **S-CLAW needs this specifically**: `table_extract`, `summarize_column` and folder listings
  all emit long, legitimately repetitive-looking output.
- **Do not replay the looped bytes.** Hermes defines
  `REPETITION_LOOP_INTERRUPTED = "[the reply degenerated into a repetition loop and was
  interrupted]"` with the comment that replaying the looped bytes *"re-seeds the loop on the
  next request and the corruption survives restarts."* Substitute a marker; never feed the
  garbage back.

#### 4. Tiny-brain system prompt → `backend/claw/agent/planner.py` / `persona.py`
**~25 lines of prose. No new dependency.**

S-CLAW ships a Qwen3-0.6B "Tiny" brain (`runtime/catalog.py:49`) but has no Tiny-specific
prompt. Goose's `tiny_model_system.md` is 21 lines and uses techniques S-CLAW's planner prompt
does not currently employ (`MODEL_INTEGRATION.md` §3b): an explicit anti-narration rule, a
single complete worked example, "do not repeat commands you have already run", and "do not use
a tool if you already know the answer".

**Adapt the techniques; do not paste the text** — it is Apache-2.0 and contains Goose's own
identity line.

**This is the cheapest item on the list and the one with a measurable outcome.** The harness
exists: `scripts/brain_bench.py`, held-out capability accuracy, mean step count. The prior
measured baseline is 56% → 69% and 4.2 → 3.1 steps from three prompt changes. Run it as an
experiment, keep what measures better, discard what does not.

### Tier 2 — turning errors into successes

#### 5. CPU pre-flight gate → `backend/claw/models/hardware.py`
**~30 lines. No new dependency** (read `/proc/cpuinfo` on Linux; on Windows, CPUID via
`platform`/registry, or a tiny `ctypes` probe).

`hardware.py` (119 lines) detects RAM (`_ram_windows`, `_ram_linux`), core count and NVIDIA
GPU — but **no CPU instruction flags**. Goose checks `fma`, `avx2`, `f16c`, `bmi2`, `sse4.2`
before loading a model and fails with a message naming *every* missing one
(`llamacpp/mod.rs:306-334`).

This is the direct answer to *"the brain was not compatible with Standard."* Today that is
discovered at inference time and surfaces as an error. A pre-flight check turns it into a named
reason the user can act on, before a download.

Pair it with the existing brain catalogue: a brain whose requirements this CPU does not meet
should not be offered.

#### 6. Extend tool-call repair beyond JSON → `backend/claw/agent/jsonfix.py` (or a sibling)
**~150 lines. No new dependency.**

`jsonfix.py` (113 lines) already handles the JSON case well — it repairs control characters and
backslashes (with a Windows-path rule that matters a lot here) and extracts the first `{...}`
from chatter or fences. What OpenClaw's `tool-call-repair` adds that S-CLAW lacks
(`MODEL_INTEGRATION.md` §3c):

- **The other three shapes**: XML `<tool_call>`, bracketed, and ReAct `Action:`.
- **A prefilter regex** so ordinary prose costs nothing.
- **Bounded work**: scan and candidate caps, so a rambling model cannot make the repairer the
  slow path.
- **Field-name tolerance**: `name` / `tool_name` / `tool` / `function_name`;
  `arguments` / `args` / `input` / `parameters`.
- **The tool-definition-echo exclusion** — reject a record that looks like a JSON Schema
  rather than a call. A small model echoing its own catalogue back is a real failure, and
  executing it would be worse than erroring.
- **A tool-name allowlist** — a repaired call must name a tool in S-CLAW's registry. This is
  what makes repair safe.
- **Protected ranges** — a fenced code block the user asked to see must not be silently
  consumed and executed.

The last two are not optional. Repair without an allowlist is a way to execute something the
model did not quite ask for.

#### 7. Unhandled tool calls as an explicit case → `backend/claw/agent/executor.py`
**~75 lines. No new dependency.** From `goose/crates/goose-agent/src/unhandled_tool_calls.rs`.

A tool call that matched nothing should be a named, logged, inspectable outcome — not a generic
error. On a 2B brain this is a *common* path. S-CLAW has felt the cost of its invisibility
already: four v1.8 scenarios were assessed as "no matching tool" when `rename_many` actually
covered one.

Making it explicit also produces the data that answers "which tools are missing?" from real
usage rather than from guessing.

#### 8. Ollama `num_ctx` → `backend/claw/models/ollama.py`
**~25 lines. No new dependency.**

`ollama.py` (153 lines) queries `/api/tags` for the model list but has no `num_ctx` handling,
and appears not to implement `context_window()` — so the `hasattr` guards in `runner.py:235`
and `planner.py:114` give an Ollama brain the conservative default. **Ollama's own default
`num_ctx` is 2048**, which is precisely the bug Hermes documents
(`MODEL_INTEGRATION.md` §2). Probe `/api/show`, send `num_ctx` per request, cap a probed value
by explicit config for VRAM safety, and label the source in the log.

### Tier 3 — the plugin ecosystem (the user's stated product direction)

#### 9. Extend the `PLUGIN.md` format → `backend/claw/plugins/pack.py`, `docs/PLUGINS.md`
**A format change. No new dependency.**

S-CLAW's plugin format is the user's own and should stay that way. Five fields from
`openclaw.plugin.json` are worth adopting — as S-CLAW's own field names, in S-CLAW's own file:

| Field | Why S-CLAW needs it |
|---|---|
| `categories` | The website catalogue needs grouping. Put it in the **contract**, not in website markup — OpenClaw has a whole `plugin-package-contract` package for exactly this. |
| `activation` | Not every plugin should load at startup. With dozens installed, startup cost and catalogue budget both matter. |
| `configSchema` (JSON Schema, `additionalProperties: false`) | A third-party plugin's settings must be validated, not trusted. |
| `configGroups` | Lets the **host render the settings UI from the manifest**, so a plugin needs no S-CLAW-side UI code. This is what makes third-party authoring practical. |
| `recommendedPrompts` | **The most valuable one.** It is how a plugin teaches a *small* brain what it is for — a mechanism S-CLAW has already proven works: the Blender plugin changed a real brain's plan from 5 steps starting "Open Blender" to 3 steps starting "Write a Blender Python script". Today that effect comes from `PLUGIN.md` prose. As a declared field it becomes reliable and documentable for third parties. |

Note OpenClaw's second recommended prompt for its computer-use plugin is deliberately
read-only ("Inspect an app… without controlling it") — the manifest encourages a safe first
interaction. Worth copying as guidance for plugin authors.

#### 10. A plugin `api/` channel → `backend/claw/plugins/`, `backend/claw/api/`
**A design addition. No new dependency.** From `agent-zero/plugins/_memory/{tools,api,helpers}/`.

Agent Zero's plugins contribute three ways at once: `tools/` (model-callable), `api/` (HTTP
endpoints the UI calls), `helpers/` (internal). S-CLAW's format covers skills and tools only.

The `api/` channel is the missing piece for the user's premium-UI goal: the Photoshop plugin he
describes would want its own settings or status panel, and that needs a plugin to serve
endpoints, not just tools. Agent Zero's numeric-prefix ordering (`_50_trim_cache.py`,
`_05_truncated_response.py`) is also a simple answer to "two plugins both want to modify the
context."

**Security note:** a plugin-served endpoint must sit behind the same per-launch token as the
rest of the backend, and must not be able to widen the permission surface. Which is why
item 11 comes with it.

#### 11. A principal on permission requests → `backend/claw/permissions/policy.py`
**Small. No new dependency.** From `goose/crates/goose-provider-types/src/permission.rs`
(`PrincipalType`).

Model "who is asking": the user, the brain, a plugin, the system. A plugin-originated
DESTRUCTIVE action must not inherit the user's standing approval. **This needs to land before
third-party plugins ship**, because retrofitting it afterwards means re-auditing every approval
path.

Goose also makes `PermissionConfirmation` a struct rather than a bool, so an approval carries
evidence of *what* was approved and cannot be silently reused for a different action. Worth
copying.

### Tier 4 — the evidence problem

#### 12. Windows-install E2E with a mock brain → `.github/workflows/`, `tests/`
**A CI addition. The mock brain is new code but ships nothing to users.**
From `OpenHands/playwright.windows-install.config.ts`.

This addresses something that has cost this project real time. S-CLAW is developed on Linux and
shipped to Windows, which has repeatedly forced honest BLOCKED statuses, and twice produced
incidents caught late:

- A mangled filename (`backend/hat(?:.?s| is) in)|`) committed in 2e3b246 that **Windows cannot
  check out**, breaking every Windows build at step 2. `tests/test_filenames_work_on_windows.py`
  now guards it.
- Two folder-peek tests that could only pass on Linux — one hardcoded `/etc`, one searched
  `json.dumps(...)` output for a path, which JSON-escapes backslashes so a Windows path can
  never match.

OpenHands' pattern: a CI job on **Windows** installs the packed artefact the way a user does,
then points Playwright at the running stack, with only a **mock LLM** started. The mock is what
makes it affordable — deterministic, free, no model download — while still exercising the real
installer, the real launcher, the real persisted session key and the real local port.

S-CLAW already has every ingredient: a per-launch token, a `127.0.0.1` backend, Playwright, and
a Windows runner in `build-windows.yml`. What it lacks is a mock-brain server and a test that
drives the **installed** app rather than the dev tree.

**Note the honest limit:** I read 22 lines of one config file. The pattern is established; the
workflow, the mock server and the specs were not read.

---

## 3. What to explicitly NOT do

| Don't | Why |
|---|---|
| **Don't adopt `camel-ai`** for desktop automation | `eigent/backend/pyproject.toml:9` pins `camel-ai[eigent]==0.2.91a7` — an **alpha**, with a custom extras group, uninspected. And Eigent's `pyautogui_toolkit.py` is a **40-line wrapper**; the breadth is camel's, not Eigent's. `pyautogui` is also coordinate-first, which works against S-CLAW's own rule: UIA first, OCR second, coordinates last. |
| **Don't port FAISS/LangChain memory** | Agent Zero's memory is the best surveyed, but costs `faiss-cpu` + `langchain-core` + `langchain-community` + an embedding model (a second local model to ship). Its genuinely valuable ideas — index integrity hashing, two deletion paths, exact-match alongside ranked match, on-disk partitioning, a memory dashboard — are all implementable on **SQLite FTS5 with zero new dependencies**. |
| **Don't add `tiktoken`** | Agent Zero's buffers (1.1 / 0.8) and base64-image sanitiser are the valuable parts and need no tokeniser. And `cl100k_base` is OpenAI's, not Qwen3's, so it would still be an approximation. |
| **Don't build sub-agents** | S-CLAW's bottleneck is a 2B model's single-step capability choice. A 2B model orchestrating other 2B models compounds the error rate. (If it ever happens: Eigent's `depth_limited_agent_toolkit.py` says bound the recursion.) |
| **Don't rewrite the agent loop as a state machine** | Goose's `machine.rs` is elegant, but the win is the **named seams** (pre-call, post-call, stop, max-turns, unhandled calls), not the pattern. Extract seams; don't re-architect. |
| **Don't collapse capability and risk into one axis** | The temptation arrives with plugins ("this plugin has DESKTOP capability so it may control the desktop"). OpenClaw's `model-inference-capabilities.ts` comments forbid exactly this: a declaration is a fact, *"never execution or grounding authority."* S-CLAW already has it right. |
| **Don't paste `tiny_model_system.md`** | Apache-2.0, and it contains *"You are goose, an autonomous AI agent created by AAIF"*. Adapt the techniques. |
| **Don't bundle model weights from any of these repos** | No weights were examined and none has verified redistribution terms. S-CLAW's `ALLOWED_LICENSES = {"apache-2.0", "mit"}` discipline should not be loosened. |
| **Don't use OpenClaw's names** | `openclaw.plugin.json`, the `__openclaw` metadata key, its UI strings. The user wants his own format; neither MIT nor Apache-2.0 grants trademark rights. |

---

## 4. The resulting architecture, in one picture

Nothing below replaces an existing component. Additions are marked **[NEW]**.

```
Electron 45 shell  (desktop/)
  renderer  ── premium UI, emergency stop (preserved)
            └─ [NEW] context breakdown panel: system prompt / tool definitions /
                     conversation / compaction summary — and NOTHING when the
                     window is unknown, never 0%        (goose context_xray taxonomy;
                                                         OpenHands null discipline)
  main      ── spawns backend, holds the per-launch token
        │
        │  HTTP, 127.0.0.1, per-launch token, trust_env=False  (already correct)
        ▼
FastAPI backend  (backend/claw/)
  agent/
    planner.py    ── [NEW] Tiny-brain prompt variant                    (goose)
    executor.py   ── [FIX] catalogue budget as a fraction of window_tokens (hermes)
                     [NEW] unhandled-tool-call outcome                   (goose)
                     [NEW] turn taint set on untrusted tool results      (openclaw)
    jsonfix.py    ── [NEW] XML / bracketed / ReAct shapes, prefilter,
                     allowlist, protected ranges, schema-echo exclusion  (openclaw)
    (new)         ── [NEW] repetition guard, with lists/tables guard     (hermes)
  permissions/
    policy.py     ── READ_ONLY / LOCAL_WRITE / EXTERNAL / DESTRUCTIVE (preserved)
                     [NEW] tainted turn ⇒ re-ask for EXTERNAL/DESTRUCTIVE
                     [NEW] principal: user / brain / plugin / system     (goose)
  models/
    hardware.py   ── [NEW] CPU instruction-flag gate, names every miss   (goose)
    openai_compat.py ── /props probe (already correct)
    ollama.py     ── [NEW] /api/show num_ctx probe + per-request num_ctx (hermes)
  plugins/
    pack.py       ── [NEW] categories, activation, configSchema,
                     configGroups, recommendedPrompts                    (openclaw)
                     [NEW] api/ channel + ordered hooks                  (agent-zero)
  runtime/, tools/, browser/, computer/, storage/  ── unchanged
        │
        ├── llama-server  (local brain, unchanged)
        ├── Playwright + Chromium  (unchanged)
        └── pywinauto / UIA  (unchanged — UIA first, OCR second, coords last)

CI  (.github/workflows/)
  build-windows.yml → release-brains.yml → build-unix.yml
                    → release-check.yml → promote-release.yml   (unchanged)
  [NEW] windows-install-e2e: install the Inno Setup artefact on Windows,
        drive the installed app with Playwright against a mock brain   (OpenHands)

Legal
  [NEW] THIRD_PARTY_NOTICES.md at repo root, shipped by the installer
        — promotes the existing backend/claw/agent/OPENCLAW_LICENSE.txt,
          adds pinned SHAs, adds a Hermes section
```

**Zero new runtime dependencies for items 1–11.** Item 12 adds CI-only code.

---

## 5. Does this answer what the user actually asked for?

The user's own framing, from this session, against what this proposal delivers:

| What he said | What this gives him |
|---|---|
| *"I'm actually competing with OpenClaw… the brain is going to be online"* | Items 1, 6, 11 harden the brain-to-tool path. The provider-as-plugin pattern (`MODEL_INTEGRATION.md` §5) is the route to an online brain without a release per provider. |
| *"It uses my software just like I will use them"* | Preserved and protected: UIA-first stays, and item 11 stops a plugin from quietly gaining the user's own authority. |
| *"there will be a place for plugin, and they can even download plugin from my website… People too can go and make their own plugin"* | Items 9 + 10: `configGroups` means a plugin's settings UI renders itself; `categories` makes the website catalogue part of the contract; the `api/` channel lets a plugin own a panel; `recommendedPrompts` is how a plugin teaches the small brain. |
| *"Hope you know that my skill is going to have my format"* | The format stays S-CLAW's. Only the **field set** is informed by OpenClaw — field names are S-CLAW's own. |
| *"I really love this app to be premium… make it look extraordinarily premium"* | The context-breakdown panel is a legible, honest, high-value piece of UI that no competitor's user normally sees. |
| *"almost all tasks are error, and it's even slow as fuck"* | Items 2, 3, 5, 6, 7 each target a distinct cause: an overcommitted window, an unbounded loop, an incompatible brain discovered too late, malformed calls that error, and unmatched calls that vanish. |
| *"it's taking a year to reply"* | Item 3 (the loop) plus the transport discipline in `PERFORMANCE_ANALYSIS.md` §3 — fail pending work when a transport dies, rather than waiting forever. |
| *"the brain was not compatible with some. I think standard."* | Item 5, directly. |
| *"If the development environment cannot run Windows applications, do not fabricate successful tests"* | Item 12 removes the need to: the installed app gets tested on Windows, in CI. |
| *"I expect you to be working 2-3 hours building something"* | Items 1–5 are each a single sitting, independent, and each measurable or testable on its own. |

---

## 6. What this proposal does NOT solve

Stated plainly, because the audit does not support claiming otherwise:

- **It does not make S-CLAW's 2B brain smart.** Items 3, 4, 6 and 7 stop a weak brain
  *failing*; they do not make it reason better. The measured ceiling — 69% held-out capability
  accuracy — is a property of the model. The honest long-term answers are a better local model,
  an online brain for hard tasks, or plugins that narrow the problem (which is the mechanism
  already proven to work).
- **It does not add semantic memory.** Deliberately deferred: the dependency cost is out of
  proportion today, and SQLite FTS5 is the zero-dependency path when it is needed.
- **It does not broaden desktop automation.** No reusable implementation was found in any of
  the six: Eigent's is camel-ai's, OpenClaw's is an external driver binary. S-CLAW's
  pywinauto/UIA executor remains the best foundation available to it, and nothing in this audit
  improves on it.
- **It is not benchmarked.** No speed claim is made anywhere. Each item needs measuring with
  `scripts/brain_bench.py` after it lands.
- **Several recommendations rest on partial reads.** The largest bodies of code in the
  best-structured projects went unread — `agent-loop.ts` (1,060 lines), `inference.rs` (675),
  `tool_approval.rs` (194), `agent.py` (1,614), `ui/desktop/src/main.ts` (3,125). Coverage is
  itemised in `PROJECT_COMPARISON.md` §5, and the follow-up reads are listed in
  `IMPLEMENTATION_ROADMAP.md`.
