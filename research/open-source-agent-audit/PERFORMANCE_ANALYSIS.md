# PERFORMANCE_ANALYSIS.md

## Rule observed throughout this document

**No code was built, run or benchmarked during this audit.** Nothing here is a measured
speed, and no project is scored for performance. Every statement below is about **code
structure** — what a project does to avoid being slow, found by reading source. Where I write
"this is faster", I mean "this avoids an identified cost", not "this was timed".

This follows the user's instruction: *"Do not invent numerical performance scores without
actual benchmarks"* and *"Do not generate fake benchmarks."*

**The only real performance numbers available to this project are S-CLAW's own**, measured
earlier in this session on real hardware with a real model: invoice read 127 s → 106 s on the
Standard brain between builds 53 and 54; held-out capability accuracy 56% → 69% after three
prompt changes; mean steps 4.2 → 3.1. Those are the baseline. Any change below should be
measured the same way with `scripts/brain_bench.py`.

---

## 1. Where the time actually goes in an app like S-CLAW

Reading six implementations makes the cost structure clear. For a local-model desktop agent,
the expensive things, in order:

1. **Tokens through the model.** On a 2B–8B local model on consumer CPU, prompt processing and
   generation dominate everything else by orders of magnitude. Halving prompt size is worth
   more than any amount of code optimisation.
2. **Number of model round-trips.** Each step is a full prompt re-process. A plan that takes
   3 steps instead of 4.2 is ~25% less model work — which is exactly where S-CLAW's own
   measured improvement came from.
3. **Failed and retried work.** A malformed tool call that errors and is retried costs two
   round-trips and produces nothing. A hung request costs unbounded wall-clock.
4. **Process and resource startup.** Launching a browser per task, reloading a model, cold
   caches.
5. **Everything else** — the Python, the IPC, the SQLite. Essentially free by comparison.

Every genuinely useful performance technique found in the six clones attacks 1–4. None of them
attacks 5, and that is itself a finding: **none of these projects optimises its own glue
code.** They optimise tokens, round-trips, failures and process reuse.

---

## 2. Attacking prompt size

### 2a. Goose: a UI that shows what is filling the window — "Context X-ray"

- **Path:** `goose/ui/desktop/src/components/context_xray/` — `ContextXrayDialog.tsx` (229
  lines), `CapacityMeter.tsx`, `BreakdownList.tsx`, `categories.ts` (43 lines),
  `ContextXrayDialog.test.tsx`. Total 669 lines. Backed by
  `goose/ui/desktop/src/acp/contextReport.ts` which exports a `ContextCategory` type.
- **Verification:** `categories.ts` read in full; the `.tsx` files by size only.

`categories.ts` gives the full taxonomy of what occupies a context window, which is the
useful part:

| Category | Label shown to the user |
|---|---|
| `system_prompt` | System prompt |
| `extension_instructions` | Extension instructions |
| `additional_instructions` | Instructions & hints |
| `turn_context` | Turn context |
| `tool_definitions` | Tool definitions |
| `compaction_summary` | Compaction summary |
| `messages` | Conversation |

Each has a distinct colour with a dark-mode variant (`categoryColorClass`), and all seven
labels go through `defineMessages` for i18n — so this is a shipped, translated feature, not a
debug panel.

**Why this matters for S-CLAW more than for Goose.** S-CLAW's window is **8192 tokens**, which
is small, and S-CLAW already spends a budgeted `CATALOGUE_BUDGET = 1800` / `FULL_CATALOGUE_BUDGET
= 4800` on tool descriptions. In Goose's taxonomy that is the `tool_definitions` slice — and
the fact that Goose gives it its own named, coloured category confirms that tool definitions
are a *first-class consumer* of the window, worth showing separately rather than lumping in
with the prompt.

Two concrete payoffs for S-CLAW:

- **As an engineering tool:** S-CLAW's catalogue budget was tuned by reasoning about limits
  (`MIN_DETAILED = 10`, `MIN_NAMED = 25`, trimming by steps of 5 — which once overshot the
  `MIN_NAMED` floor and produced 23 instead of 25). A breakdown view turns that tuning from
  arithmetic into observation.
- **As a premium UI feature:** the user asked for the app to look "extraordinarily premium."
  A capacity meter that shows *why* the brain ran out of room is a legible, high-value piece
  of UI that no competitor's user ever sees by default. It is also honest, which fits this
  project's rules.

**Reuse: 3 — architectural reference only** (React/TS against Goose's ACP types), but the
*taxonomy* is **1 — directly reusable**: seven category names are not code.

### 2b. Letting the model ask for tools instead of being given all of them

`goose/crates/goose-local-inference/src/tool_emulation.rs` prompts a tiny model to emit JSON
discovery arguments in ```` ```list_functions ```` and ```` ```get_function_details ````
fences (module doc, read).

This inverts S-CLAW's current strategy. S-CLAW fits as much of the catalogue into the prompt
as the budget allows, trimming names and detail to hit 1800/4800 tokens. Goose's tiny-model
path sends *no* catalogue and lets the model request what it needs.

**The trade-off is real and must be stated honestly.** Discovery costs an extra round-trip
(cost driver 2) to save prompt tokens (cost driver 1). Which wins depends on how many steps a
task takes and how large the catalogue is. With S-CLAW's catalogue at 1800–4800 tokens of an
8192 window — 22–59% of the entire window spent before the task is described — the arithmetic
plausibly favours discovery for longer tasks, and plausibly does not for one-step tasks like
"open Notepad". **This is a measurable question, not a decision to take on faith**, and
`scripts/brain_bench.py` can answer it. Do not implement it as an improvement; implement it as
an experiment.

### 2c. Prompt caching declared per (provider, model) — Goose

- **Path:** `goose/crates/goose-provider-types/src/cache_semantics.rs` (342 lines)
- **Verification:** `READ`, first 45 lines

Its module doc states the design: *"Prompt-cache semantics declared per (provider, model),
instead of implied by whichever format module a request flows through."*

```rust
pub enum CacheSemantics {
    /// Caller places markers; reuse needs an exact match of the marked bytes.
    ExplicitBreakpoints { max_breakpoints: usize },
    /// The longest matching stored prefix is reused implicitly.
    ImplicitTolerant,
    /// Only extends a prompt reproduced byte-for-byte from the start.
    ImplicitStrict,
    /// No known prompt cache.
    Uncached,
}
```

`CacheSemantics::for_model(provider_name, model_name)` then maps real providers:
`anthropic`, `minimax`, `zai`, `kimi_code` → `ExplicitBreakpoints { max_breakpoints: 4 }`;
`aws_bedrock` / `databricks` / `gcp_vertex_ai` → the same **but only** when the model name
contains `"claude"`; `openrouter` / `litellm` → the same when the model id starts with
`"anthropic/"`; `openai` / `azure_openai` / `github_copilot` → `ImplicitStrict` if
`is_openai_responses_model(model_name)` else `ImplicitTolerant`; `moonshot`,
`custom_deepseek`, `groq`, `together`, `fireworks-ai`, `mistral`, `zhipu`, `alibaba` →
`ImplicitTolerant`; `snowflake`, `sagemaker_tgi` → `Uncached`.

**The two best decisions here:**

1. **The unknown-pair default is `ImplicitStrict`,** documented as *"safe for every cache."*
   Unknown providers get the most conservative behaviour, so adding a provider cannot silently
   break caching or produce wrong reuse. This is the same instinct as S-CLAW's
   `PermissionPolicy.__init__` forcing DESTRUCTIVE=ALLOW → ASK: **the default is the safe
   value, not the convenient one.**
2. The gateway/aggregator cases (`openrouter`, `litellm`, `bedrock`, `vertex`) are handled by
   inspecting the *model* name, because the provider name alone does not determine the cache
   behaviour. That is a detail you only get right after being bitten.

**Relevance to S-CLAW, stated precisely.** For the **local** brain this has no direct
application: `llama-server` has its own KV-cache/prefix-reuse behaviour, which this file does
not describe and I did not investigate. The relevance is twofold and real: (a) the user intends
the brain to run **online**, and the moment S-CLAW supports a cloud provider, prompt-cache
semantics decide whether a long system prompt costs money and latency on every turn or once;
(b) the *principle* — **prompt-stability as a performance property** — applies locally too.
Any prefix cache, local or remote, only pays off if the prompt prefix is byte-stable. If
S-CLAW injects a timestamp, a random id or a reordered tool catalogue near the top of the
prompt, it defeats prefix reuse on every turn. **That is worth auditing in S-CLAW's own
prompt construction, and it is free to check.**

**Reuse: 3 — architectural reference only.**

### 2d. Token accounting that does not lie — Agent Zero

`agent-zero/helpers/tokens.py` (read, first 40 lines): `APPROX_BUFFER = 1.1`,
`TRIM_BUFFER = 0.8`, `count_tokens(text, encoding_name="cl100k_base")` via `tiktoken` with
`disallowed_special=()`, `approximate_tokens()` = count × 1.1, and
`sanitize_embedded_image_data_urls()` replacing `data:image/…;base64,…` with
`[embedded image data omitted from token estimate]`.

Three performance-relevant points:

- **Asymmetric buffers.** 1.1 when asking "will it fit", 0.8 when deciding how much to cut. A
  mis-estimate fails safe in both directions. S-CLAW uses a single `CHARS_PER_TOKEN = 3.5`
  divisor with no margin — so an underestimate becomes a truncated or rejected request, which
  costs a wasted round-trip, which the user experiences as an error *and* as slowness.
- **`disallowed_special=()`.** Without it, `tiktoken` *raises* on `<|endoftext|>`, which a
  model can emit. This is a crash, not a slowdown, but it is the kind that looks like a hang.
- **The image sanitiser is not optional for S-CLAW.** The brain is Qwen3-**VL**; screenshots
  are routine and get inlined as base64. An unsanitised estimate on an inlined screenshot is
  wrong by orders of magnitude, so every budget silently blows and every trim decision is
  garbage. S-CLAW should sanitise before estimating regardless of which estimator it uses.

**Dependency note:** `tiktoken` would be a **new dependency**, against the standing rule. And
`cl100k_base` is OpenAI's tokeniser, not Qwen3's, so even with it the count is approximate for
S-CLAW's actual brain. **The buffers and the sanitiser are the valuable parts and neither needs
`tiktoken`** — they can be applied to the existing divisor. That is the recommendation.

### 2e. Structured compaction — Goose

`goose/crates/goose-context-management/src/lib.rs` (70 lines, read in full):
`DEFAULT_COMPACTION_THRESHOLD: f64 = 0.8`; a two-trait API (`CompactionInput` /
`CompactionOutput`) so the caller keeps its own conversation representation; an **optional**
token estimator (`Option<&dyn TokenEstimator>`); `impl CompactionInput for Vec<Message>` as a
free default; and re-exports `StructuredSummary` and **`FileActivity`**.

`FileActivity` is the performance-relevant detail. Compaction normally throws away "which
files were touched", and the agent then re-discovers them — extra round-trips, cost driver 2.
Tracking file activity as **structured data in the summary** rather than hoping prose
preserves it avoids that re-discovery. For S-CLAW, whose tasks are heavily file- and
document-shaped (PDF edit, table extract, merge, rewrite, batch image), this is the right
shape: after a summary the brain should still know the working set.

`OpenHands/src/hooks/use-await-context-compaction.ts` (164 lines) and
`use-compact-context-action.ts` (119 lines) — **not read** — indicate compaction is both a
user-triggerable *action* and an *awaited* event in the UI. That is a design choice worth
noting: compaction is slow and visible, so OpenHands shows it rather than hiding it.

---

## 3. Attacking failed and hung work

This is where the most immediately actionable findings are, because a hang is unbounded and a
retry is pure waste. All of the following are verified from
`eigent/backend/app/agent/toolkit/hybrid_browser_toolkit.py` (1,038 lines, declarations
verified by grep with line numbers).

| Technique | Declaration | Cost it avoids |
|---|---|---|
| Per-command timeouts | `_command_timeout_seconds` `:147`, `_env_timeout_seconds` `:74`, `_timeout_value_to_seconds` `:58` | One global timeout is either too short for navigation or too long for a click |
| Fail all pending on transport death | `_fail_all_pending(exc)` `:141` | **Unbounded** wall-clock; the app looks frozen |
| Tab caps with LRU | `_max_session_tabs` `:179`, `_max_managed_tabs_per_endpoint` `:185`, `_track_and_limit_tabs` `:208`, `_touch_session_tab` `:194`, `_forget_session_tab` `:201` | Memory growth → swapping → everything slow |
| Navigation lock | `_navigation_lock_key` `:168`, `_navigation_lock_wait_seconds` `:172`, `_endpoint_lock_key` `:95` | Racing navigations produce wrong results, then retries |
| No proxy for localhost | `_ensure_local_no_proxy()` `:319` | A system proxy intercepting localhost — total failure (**S-CLAW already does this, via `trust_env=False`**) |
| Connection pool | `class WebSocketConnectionPool` `:620`, `get_connection` `:627`, `close_connection` `:698` | Browser launch per task (cost driver 4) |

### The two to act on, and why

**`_fail_all_pending`.** This is the mechanism behind a complaint already on record from the
user: *"I just told it thank you / And it's taking a year to reply."* A transport that dies
without failing its in-flight work leaves futures unresolved forever. S-CLAW has three such
transports — HTTP to `llama-server`, HTTP to its own FastAPI backend on `127.0.0.1`, and CDP to
Chromium. Each needs a defined behaviour when it dies, and "the request never returns" is not
one.

**`_ensure_local_no_proxy` — CORRECTION: S-CLAW already solves this, and solves it better.**
On a Windows machine with `HTTP_PROXY`/`HTTPS_PROXY` set — normal on a corporate laptop —
requests to `127.0.0.1` can be routed into the proxy and fail, and S-CLAW depends on
`127.0.0.1` for both its backend (with a per-launch token) and `llama-server`. I checked
S-CLAW's source after writing this section: **every** S-CLAW HTTP client already passes
`trust_env=False` — `backend/claw/runtime/engine.py:225`,
`backend/claw/models/openai_compat.py:139`, `backend/claw/models/ollama.py:87` and `:116`.
That disables proxy-environment inheritance outright rather than patching `NO_PROXY` around
it, which is the stronger fix. **No action needed; disregard any recommendation elsewhere to
add a localhost proxy exclusion.** Recorded here because the failure mode is real and the
existing defence must not be removed by accident.

Neither of these is a micro-optimisation: each converts an unbounded or total failure into a
bounded, named one. One of the two turns out to be already in place.

### Repair instead of retry

`openclaw/packages/tool-call-repair/` (4,296 non-test lines) is also a performance technique,
not only a correctness one. A malformed tool call that errors costs a wasted round-trip plus a
retry round-trip and produces nothing — the most expensive possible outcome. Repairing it
locally costs microseconds.

Its own cost controls are worth noting, because a repairer can itself become the slow path:
`MAX_SCAN_CHARS = 20_000`, `MAX_JSON_CANDIDATES = 20`, `MAX_JSON_CANDIDATE_CHARS = 8_000`, and
a **prefilter regex** that skips the expensive path entirely for ordinary prose. That prefilter
is the right shape — bounded work, and zero cost in the common case.

---

## 4. Token usage as structured data — Goose

- **Path:** `goose/crates/goose-provider-types/src/conversation/token_usage.rs` (297 lines)
- **Verification:** `DECL`

Declarations: `pub struct ProviderUsage` `:7`, `pub enum CostSource` `:31`,
`pub struct ProviderStats` `:37`, `pub struct DraftStats` `:46`, `pub struct Usage` `:102`.
Builders: `ProviderUsage::new(model, usage)` `:56`, `.with_stats()` `:70`,
`.with_cost(cost, source)` `:75`, `.with_finish_reasons(Vec<String>)` `:81`,
`.with_response_id()` `:86`, `.with_request_id()` `:91`; and on `Usage`: `new(...)` `:150`,
`with_cache_tokens(...)` `:175`, `from_cache_exclusive_input(...)` `:187`.

Three design points:

- **`CostSource` as an enum.** A cost is not just a number — it records *how it was
  determined*. That is the difference between a reported figure and an honest one, and it is
  the same discipline this project's rules demand everywhere else.
- **Cache tokens are modelled explicitly,** with two constructors
  (`with_cache_tokens`, `from_cache_exclusive_input`) because providers report cached input
  differently — some include cached tokens in the input count, some exclude them. Getting this
  wrong makes a cache look useless or free.
- **`finish_reasons: Vec<String>`** is retained. A truncation ("length") versus a stop is the
  difference between "the model finished" and "we silently lost the end of the answer", and
  keeping it means that can be detected rather than guessed.

**For S-CLAW:** if token usage is recorded per turn with its source, a *real* performance
baseline becomes possible — tokens per task, turns per task, time per token — which is what
would let the next optimisation be measured rather than argued. That is the prerequisite for
any future performance claim this project makes.

**Reuse: 3 — architectural reference only.**

## 5. Honest UI-side detail worth copying — OpenHands

`OpenHands/src/hooks/use-context-window-usage.ts` (52 lines, read, first 40):

```ts
function toContextWindowUsage(usage): ContextWindowUsage | null {
  const contextWindow = usage?.context_window ?? 0;
  if (contextWindow <= 0) {
    return null;
  }
  return { perTurnToken: usage?.per_turn_token ?? 0, contextWindow };
}
```

When the context window is unknown or zero, it returns `null` — so the UI shows **nothing**
rather than a meter reading 0%, or a fabricated capacity. It reads `per_turn_token` and
`context_window` from a conversation-metrics query keyed by `conversation?.session_api_key`
(note: the same per-session key pattern S-CLAW uses).

This is small but exactly aligned with this project's rules — *"Do not fabricate … connection
status"*, *"Never convert BLOCKED or NOT TESTED into PASS."* **An unknown value must render as
unknown, not as zero.** If S-CLAW adds a context meter (§2a), this is the behaviour it needs,
and it connects back to `MODEL_INTEGRATION.md` §2: if the served window is probed rather than
assumed, the probe can fail, and then the meter must say so.

---

## 6. Cross-project comparison of *structural* performance measures

Presence/absence of a technique, from what I verified. **"Not found" means I did not find it,
not that it is absent** — only Goose and Eigent were examined closely on these axes.

| Technique | goose | eigent | openclaw | hermes | agent-zero | OpenHands |
|---|---|---|---|---|---|---|
| Served-window probe for local server | n/a (in-process) | not found | not found | **yes** | not found | not found |
| Compaction as a reusable library | **yes** | not found | not found | yes (compressor) | plugin | UI hooks |
| Context breakdown shown to user | **yes** (X-ray) | not found | not found | not found | `_context_window` plugin | usage hook |
| Prompt-cache semantics per model | **yes** | not found | partial (`prompt-cache.runtime.ts`) | `agent_cache_pressure.py` | `cache.py` | not found |
| Tokeniser-based counting | not found | not found | not found | not found | **yes** (`tiktoken`) | not found |
| Token-estimate image sanitising | not found | not found | not found | not found | **yes** | not found |
| Per-command timeouts | not found | **yes** | not found | not found | not found | not found |
| Fail-all-pending on transport death | not found | **yes** | not found | not found | not found | not found |
| Resource caps (tabs/connections) | not found | **yes** | not found | not found | not found | not found |
| Connection pooling | not found | **yes** | not found | not found | not found | not found |
| Malformed-tool-call repair | emulation parser | not found | **yes** (dedicated pkg) | not found | not found | not found |
| CPU feature pre-flight gate | **yes** | n/a | n/a | not found | n/a | n/a |
| Per-model sampling/tool settings | **yes** | row in DB | catalogue | config | not found | not found |
| Structured token/cost accounting | **yes** | not found | pricing module | not found | not found | metrics store |

**What the table says.** The techniques are **scattered** — no single project has them all.
Goose owns local inference, context management and accounting. Eigent owns runtime robustness.
OpenClaw owns tool-call repair and catalogue modelling. Hermes owns the served-window problem.
Agent Zero owns token counting and memory. OpenHands owns Windows-install testing and honest
UI nulls.

**This is the strongest argument for the user's own stated position** — *"I do not want six
different AI frameworks running together. I want one coherent application with carefully
selected components."* There is nothing to adopt wholesale, because no project is
comprehensively good. There are about a dozen specific techniques to adopt, most of them
small, and the correct outcome is S-CLAW's existing architecture plus those techniques.

---

## 7. What I could not establish

- **No timings.** No project was built or run. No comparative speed claim exists in this audit,
  and none should be invented from it.
- **`openclaw/packages/retry/` was not read.** Backoff and jitter policy is unestablished
  anywhere. This is the most important performance-adjacent gap, because retry policy is
  precisely where "slow as fuck" is either caused or fixed.
- **Model-request timeouts** (as distinct from browser-command timeouts) were **not found in
  any project**. What any of them does when a local model stops responding mid-generation is
  unknown. For S-CLAW this is a real question — a stalled `llama-server` is a plausible cause
  of the hangs the user has reported — and this audit does not answer it.
- **Streaming internals** were not read anywhere: chunk handling, backpressure, cancellation.
- **`llama-server`'s own prefix/KV cache behaviour** was not investigated; no llama.cpp source
  was read. The prompt-stability recommendation in §2c is sound in principle but its magnitude
  for S-CLAW's local brain is unmeasured.
- **Goose's Electron main process** (`ui/desktop/src/main.ts`, 3,125 lines) was not read, even
  though it is the closest analogue to S-CLAW's own shell and would be the place to find
  Electron-specific startup and IPC cost handling. Largest single gap on the UI/runtime side.
- **`eigent`'s `camel-ai` dependency** was never inspected, so Eigent's non-browser toolkit
  performance characteristics are unknown.

---

## 8. Recommended measurement plan (before any optimisation)

S-CLAW already has the only real numbers in this document, and the harness that produced them.
The right next step is not to implement a technique but to extend the baseline so that each
technique can be judged:

1. **Record per-task: tokens in, tokens out, round-trips, wall-clock, outcome.** Goose's
   `ProviderUsage`/`Usage` shape (§4) is the model, including `finish_reasons` so truncation is
   detectable.
2. **Probe and log the served context window** (`MODEL_INTEGRATION.md` §2). Until this is
   known, every budget number is unverified and so is every conclusion drawn from one.
3. **Check prompt prefix stability** — does S-CLAW's prompt begin with identical bytes every
   turn? Free to check, and it gates any cache benefit, local or cloud.
4. **Then** test one change at a time against `scripts/brain_bench.py`, in this order of
   expected value per unit of effort: tiny-model prompt techniques → tool-call repair →
   `_fail_all_pending` (localhost-no-proxy is already done) → token buffers and image sanitising →
   discovery-instead-of-catalogue as an experiment.

Each of those is independently measurable with the existing harness, and none requires adopting
another framework.
