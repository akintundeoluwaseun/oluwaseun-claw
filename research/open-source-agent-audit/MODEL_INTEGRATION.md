# MODEL_INTEGRATION.md

The user named this "one of the most important areas". This document covers what each project
does about local models (Ollama, LM Studio, llama.cpp), cloud providers, model switching,
streaming, and failure/timeout handling — from source, with the gaps named.

**S-CLAW's current position, for reference:** `llama.cpp` `llama-server` as the local engine;
brain catalogue of Qwen3-VL 2B/4B/8B Instruct plus Qwen3-0.6B Tiny; `ALLOWED_LICENSES =
{"apache-2.0", "mit"}`; context window 8192; budgets `CATALOGUE_BUDGET = 1800`,
`FULL_CATALOGUE_BUDGET = 4800`, `CHARS_PER_TOKEN = 3.5`, `MIN_DETAILED = 10`,
`MIN_NAMED = 25`. The brain is intended to be able to run online as well as locally.

---

## 1. Discovering a local server that is already running

**Only Eigent has a complete, verified answer.** `eigent/src/components/Settings/Models/localModels.ts`
(read in full) is a table of local runtimes, each with an OpenAI-compatible base URL and a
discovery path:

| Runtime | Default endpoint | Model discovery | Parser |
|---|---|---|---|
| Ollama | `http://localhost:11434/v1` | `/api/tags` | `parseOllamaModels` |
| vLLM | `http://localhost:8000/v1` | — | `parseOpenAICompatibleModels` |
| SGLang | `http://localhost:30000/v1` | — | `parseOpenAICompatibleModels` |
| LM Studio | `http://localhost:1234/v1` | — | `parseOpenAICompatibleModels` |
| llama.cpp | `http://localhost:8080/v1` | `/v1/models` | `parseOpenAICompatibleModels` |

Type: `LocalModelOption { id, name, defaultEndpoint, fetchPath?, parseModels? }`. Helpers:
`toEndpointBaseUrl`, `getDefaultLocalEndpoint`, `getLocalPlatformName`. Provider id constants:
`OLLAMA_PROVIDER_ID`, `VLLM_PROVIDER_ID`, `SGLANG_PROVIDER_ID`, `LMSTUDIO_PROVIDER_ID`,
`LLAMA_CPP_PROVIDER_ID`.

Two design points worth stating plainly. **One** parser covers four of the five runtimes,
because they all expose OpenAI-compatible `/v1/models`; only Ollama needs its own. And both
`fetchPath` and `parseModels` are **optional** — a runtime with no discovery endpoint still
works, the user just types the model name. That optionality is what keeps the table from
becoming a maintenance burden.

**What this gives S-CLAW.** A user who already runs Ollama or LM Studio has a model
downloaded and warm in RAM. S-CLAW currently requires its own `llama-server` and its own
brain download. Pointing at an existing server is a short feature with a real payoff on first
run — and this table is the part that is tedious to get right.

**Hermes** also distinguishes local endpoints, via `is_local_endpoint(base_url)` from
`hermes-agent/agent/model_metadata.py` (function identified by its import in
`agent_init_ollama.py`; the function body was **not** read, so how it decides "local" is
unknown — presumably host-based).

**Goose** takes the opposite approach: it does not discover a local server, it *is* one.
`goose-local-inference` links llama.cpp in-process via the `llama-cpp-2` crate (established
from the comment about `common_chat_templates_get_caps` and `llama-cpp-2` 0.1.146), and
`goose/crates/goose/src/providers/local_inference.rs` (76 lines, read) is a thin shim
re-exporting `goose_providers::local_inference::*`. That shim uses a `GOOSE_LOCAL_MODEL_SETTINGS`
config key and an injection pattern — `set_string_param_resolver`,
`set_model_settings_resolver`, `set_model_settings_writer` — so the core does not depend on a
config implementation.

**OpenClaw, OpenHands, Agent Zero:** not established. OpenClaw certainly has provider
extensions (189 directories under `extensions/`) but I did not verify which handle local
runtimes. **Gap.**

---

## 2. The served context window — the single most important finding

### The problem, stated once

A local server does not necessarily serve the window the model advertises. Ollama's default
`num_ctx` is **2048** regardless of the model. A GGUF can advertise 256 K. `llama-server`
takes `--ctx-size` and may clamp it for VRAM. So there are three different numbers in play:

1. what the model's metadata says it supports,
2. what the server was configured to serve,
3. what the server will actually serve after clamping.

**Every token budget and every compaction threshold must be derived from (3).** If it is
derived from (1), the budget is too large and requests get truncated or rejected; worse, a
compaction threshold computed from (1) can sit *above* the real window and **never fire** —
a silent failure with no error message.

### Hermes is the only project surveyed that handles this explicitly

`hermes-agent/agent/agent_init_ollama.py`, read in full for its two functions. Its own
docstring: *"Init-time local-server (Ollama) num_ctx detection and the compressor clamp to it."*

`_configure_ollama_num_ctx(agent, _model_cfg, _config_context_length)` resolves the window in
strict precedence:

1. **Explicit config wins.** `model.ollama_num_ctx`, coerced with `int()`; a bad value is
   caught (`TypeError, ValueError`) and logged at debug. It does not raise, and it does not
   silently become a number.
2. **Probe, but only for a local endpoint.** Only if `agent.base_url` is truthy **and**
   `is_local_endpoint(agent.base_url)` does it call
   `query_ollama_num_ctx(agent.model, agent.base_url, api_key=_key or "")`. Note the guard it
   documents: *"api_key may be a callable (Entra token provider); detection needs a string"* —
   so `agent.api_key` is used only `if isinstance(agent.api_key, str)`, else `""`. A probe
   failure is caught broadly and logged at debug: detection is best-effort and never fatal.
3. **Cap the probe by explicit config.** Its comment: *"Cap auto-detected num_ctx to the
   explicit context_length (GGUF metadata can advertise 256K+ and Ollama would allocate that
   much VRAM); never override an explicit num_ctx."* So `_config_context_length` lowers a
   probed value but not an overridden one.
4. **Log which source the number came from.** Its comment: *"Name the real source: a config
   override is honoured on any local server, /api/show is Ollama-only."* The log line
   distinguishes `model.ollama_num_ctx` from "model max from Ollama /api/show", and only when
   `not agent.quiet_mode`.

`_clamp_compressor_to_ollama_num_ctx(agent)` then does the part that most implementations
miss: it lowers `agent.context_compressor.context_length` to the effective `num_ctx` when the
latter is smaller. Its comment describes the bug in full:

> Recalibrate the compressor to the served window: every request runs at num_ctx, so a trigger
> derived from the probed model window could sit above it and never fire. A config that sets
> only model.ollama_num_ctx (without model.context_length) previously left the compressor
> targeting the probed window while the server truncated/rejected at num_ctx — the compaction
> trigger could sit several times ABOVE the real served window and never fire.

It also notes the overlap with another issue ("#60103's silent-clamp dead zone; this is the
init-order half") — i.e. this was found twice, from two directions, in production.

### What this means for S-CLAW, concretely

S-CLAW's budgets (`CATALOGUE_BUDGET = 1800`, `FULL_CATALOGUE_BUDGET = 4800`) and its
`CHARS_PER_TOKEN = 3.5` divisor are all computed against a window of **8192**, which is an
assumed constant. If `llama-server` is launched with a smaller `--ctx-size` on a low-RAM
machine, or clamps it, those budgets are wrong and nothing will say so. Given the user has
reported that "almost all tasks are error, and it's even slow as fuck," a wrong window is a
plausible contributor and is cheap to rule out.

The recommended change, in Hermes' shape:

1. On brain start, **ask the server** what it serves, rather than assuming 8192.
2. Derive every budget from the answer.
3. **Log the source** of the number ("configured", "probed from server", "fallback default").
4. Clamp any compaction/trim threshold to the same number.

### CORRECTION: S-CLAW already does most of this

**I checked S-CLAW's own source after writing the above, and must correct it.** S-CLAW already
implements the llama.cpp half of this finding, and implements it well.

`backend/claw/models/openai_compat.py:68` defines `async def context_window(self) -> int | None`,
which queries **`/props`** and reads `n_ctx`, falling back to
`default_generation_settings.n_ctx`. Its docstring states the same failure mode Hermes
documents, independently:

> Worth asking rather than assuming, because llama.cpp clamps -c DOWN to the model's trained
> context: starting the engine with -c 8192 and a model trained at 2048 gives a server with
> 2048, and nothing told Claw. Budgeting against the figure that was requested rather than the
> one in force means a long run is cut off by a 400 from the server instead of being trimmed
> to fit.
>
> /props is llama-server's own report and sits at the root, not under the version prefix.
> Anything else answers 404, which is not an error worth raising: a provider that will not say
> simply gets the caller's default.

And it is wired up correctly. `backend/claw/agent/runner.py:228-245` compares the probed value
against what was asked (`state.brain.engine.ctx_size` for the builtin engine, else
`HOSTED_CONTEXT_TOKENS`), **logs when they differ** (`"model window differs from the one
requested"`, with `asked` and `actual`), swallows any probe exception with the comment *"never
let a window probe fail the task"*, and passes the result as `window_tokens=window` into
`run_agent`. `backend/claw/agent/planner.py:112` does the same via `_window()`, with *"not
knowing the window must never fail the plan"*.

So items 1, 3 and 5 of the §7 checklist are **already done for llama-server**, and the `/props`
mapping is no longer an assumption — it is S-CLAW's shipped implementation. This also means my
earlier framing of this as "the highest-value single file in the audit" was wrong, and the
credit belongs to S-CLAW's existing code.

**What is genuinely still missing, verified in source:**

1. **The catalogue budget does not derive from the probed window.**
   `backend/claw/agent/executor.py:1048` sets `CATALOGUE_BUDGET = 1800` and `:1053`
   `FULL_CATALOGUE_BUDGET = 4800` as **absolute constants**. `fit_context(messages,
   window_tokens)` at `:1207` *does* use the probed window (`:1234`,
   `budget = max(window_tokens - reserve, 512)`) — but the catalogue trimming at `:1116`
   (`budget = CATALOGUE_BUDGET if capabilities else FULL_CATALOGUE_BUDGET`) does not know the
   window at all. On a server that actually serves 2048, the catalogue alone claims 1800 of it
   — 88% — while `fit_context` independently budgets `2048 - reserve` for the message history.
   They cannot both be satisfied, and nothing reconciles them. **This is exactly the
   half-clamped state Hermes' `_clamp_compressor_to_ollama_num_ctx` exists to prevent**, and it
   is the one concrete, verified defect this comparison surfaces in S-CLAW's own code. The fix
   is to express the catalogue budget as a fraction of `window_tokens` with the current
   constants as the 8192 case, so a smaller window shrinks the catalogue instead of
   overcommitting the window.
2. **The Ollama path has no `num_ctx` handling at all.** `backend/claw/models/ollama.py`
   (153 lines) queries `/api/tags` for the model list but contains no reference to `num_ctx`.
   Since `OllamaAdapter` appears not to define `context_window()`, the `hasattr` guards in
   `runner.py` and `planner.py` mean an Ollama brain silently gets the **conservative default**
   rather than a probe — and Ollama's own default `num_ctx` is **2048**, which is the precise
   bug Hermes documents. For an Ollama brain, S-CLAW should probe `/api/show` and send `num_ctx`
   per request, exactly as Hermes does.
3. **No source label on the number.** `runner.py` logs `asked` vs `actual`, which is good, but
   does not record *how* `actual` was obtained (probe / config / default). Hermes' comment
   *"Name the real source"* is the remaining refinement, and it matters when diagnosing a user
   report.

**Verdict on A8, revised:** still a valuable file, but its value to S-CLAW is now narrow and
specific — the Ollama `num_ctx` path and the compactor-clamp discipline — rather than the whole
design. Reuse class unchanged (**2**), priority lowered.

### Nobody else surveyed does this

Goose runs llama.cpp in-process, so it knows the window directly from the loaded model and
`ModelSettings` — the problem does not arise in the same form. For OpenClaw, OpenHands and
Agent Zero I found no equivalent and did not look exhaustively. **Gap.**

---

## 3. Tool calling on small models

This is S-CLAW's measured bottleneck: capability-choice accuracy on a real Qwen3.5-2B moved
56% → 69% with three prompt changes, and steps 4.2 → 3.1. Two projects attack it directly,
from opposite ends.

### 3a. Goose: decide per model whether native tool calling is even possible

`goose/crates/goose-local-inference/src/llamacpp/mod.rs`. `ToolCallingMode` has three values —
`Auto`, `ForceNative`, `ForceEmulated` — and:

```rust
fn should_use_native_tool_calling(
    mode: ToolCallingMode, has_tools: bool, template_supports_native: bool,
) -> bool {
    has_tools && match mode {
        ToolCallingMode::Auto => template_supports_native,
        ToolCallingMode::ForceNative => true,
        ToolCallingMode::ForceEmulated => false,
    }
}
```

The interesting part is how `template_supports_native` is obtained: a **dry run of the chat
template**. `supports_native_tool_calling()` builds `OpenAIChatTemplateParams { messages_json,
tools_json: Some(tools_json), use_jinja: true, parse_tool_calls: true, add_generation_prompt:
true, parallel_tool_calls: false, enable_thinking, reasoning_format: if
settings.enable_thinking { Some("auto") } else { None }, … }` and calls
`loaded.model.apply_chat_template_oaicompat(template, &params)`. Then
`template_result_supports_native_tool_calling()` requires **both** `result.parse_tool_calls`
**and** a non-empty `result.parser`. An error from the template is caught, logged at debug
with `"llama.cpp chat template dry-run did not support native tool calling"`, and treated as
`false`.

Two things to note. There is an early `return false` if `tools_json` is absent or blank — no
tools, no native tool calling, regardless of mode. And the code is honest about why it is a
dry run rather than a capability query: llama.cpp exposes `common_chat_templates_get_caps` in
C++, but `llama-cpp-2` 0.1.146 has not bound it, so the dry-run stands in until it does.

Supporting machinery: `load_chat_templates()`, `select_generation_template()`,
`is_legacy_builtin_template_name()`, `missing_chat_template_error()`, and
`list_builtin_chat_templates()` exposed through `management.rs`. Templates are first-class
configuration, not a hidden detail.

**For S-CLAW:** the principle transfers without the code. S-CLAW ships a 0.6B Tiny brain
along 2B/4B/8B models, and a 0.6B will not emit reliable native calls. The lesson is **ask
the model's own template, don't assume by model name** — plus a user-visible override, since
`Auto` will sometimes be wrong. S-CLAW uses `llama-server` over HTTP rather than in-process
bindings, so the detection mechanism differs; `llama-server` reports template information
differently and that needs establishing against a running server.

### 3b. Goose: a prompt and a parser built for a tiny model

When native calling is off, `goose/crates/goose-local-inference/src/tool_emulation.rs` (760
lines) takes over. Its module doc:

> Models that do not have native tool-calling support are prompted to emit shell commands as
> `$ command` on a new line, JavaScript in ```` ```execute_javascript ```` fences, and JSON
> discovery arguments in ```` ```list_functions ```` or ```` ```get_function_details ````
> fences. The parser converts those patterns into Goose tool-call messages.

Implementation details that matter: it parses the model's output as **Markdown** using
`pulldown_cmark` (`Parser`, `Event`, `Tag`, `CodeBlockKind`) rather than regexing raw text, so
a fenced block is recognised structurally. Constants: `SHELL_TOOL = "developer__shell"`,
`CODE_EXECUTION_TOOL = "execute_javascript"`. Each recovered call gets a `Uuid`.

Note the shape of the emulated protocol: **one** format per intent, each as short as possible
(`$ ` for shell, a named fence for code), plus named fences for *discovery*
(`list_functions`, `get_function_details`) so a tiny model can ask what tools exist instead of
being handed a full catalogue up front. That last point is directly relevant to S-CLAW's
catalogue-budget problem: Goose's tiny-model path replaces "fit the catalogue into the prompt"
with "let the model ask."

And the prompt, `prompts/tiny_model_system.md` — **21 lines**, read in full, rendered by
`prompt_template::render_template` with `{os, working_directory, shell}` where `os` comes from
`cfg!(target_os=…)` → `"macos"`/`"linux"`/`"windows"`/`"unknown"`, `working_directory` from
`env::current_dir()`, `shell` from `$SHELL` defaulting to `/bin/sh`. A template failure logs a
warning and falls back rather than panicking.

Its seven techniques, in its own order:

1. Identity plus a behavioural rule in the first sentence: *"You act on the user's behalf —
   you do not explain how to do things, you DO them directly."*
2. Environment injected as plain facts: OS, shell, working directory.
3. The anti-narration rule, repeated: *"take action immediately. Do not describe what you
   would do or give instructions — execute the commands yourself."*
4. The output format in one line **with a literal example** — *"start a new line with $:"*
   then `$ ls`.
5. *"Keep your responses brief."*
6. A **complete worked exchange**: `User: how many files are in /tmp?` / `You: Let me check.`
   / `$ ls -1 /tmp | wc -l`. One example, showing a short acknowledgement *and* the action.
7. What happens next, and two negative rules: *"After a command runs, you will see its
   output"*, *"Do not repeat commands you have already run"*, and *"Do not use shell commands
   if you already know the answer."*

**For S-CLAW:** this is the cheapest experiment available. Techniques 3, 6 and 7 — anti-
narration, a single worked example, and don't-repeat/don't-tool-when-you-know — are not in
S-CLAW's planner prompt as far as the measured work went, and the harness to measure the
effect already exists (`scripts/brain_bench.py`, held-out capability accuracy, step count).
Apache-2.0, so **adapt the techniques, do not paste the text** — which also avoids importing
Goose's identity line.

### 3c. OpenClaw: repair whatever the model actually emitted

`openclaw/packages/tool-call-repair/` — 4,296 non-test lines. The complement to Goose's
approach: instead of constraining the format, accept any of four shapes and recover from them.
`attempt.ts` classifies `kind: "json_tool_call" | "xml_tool_call" | "bracketed_tool_call" |
"react_action"`.

Verified mechanics:

- A **prefilter** so prose costs nothing:
  `/(?:tool[_\s-]?calls?|function[_\s-]?call|["'](?:name|tool_name|function|arguments|args|input|parameters|tool_calls)["']|<\s*tool_call\b|Action\s*:|\[END_TOOL_REQUEST\])/i`
  — note it catches ReAct `Action:` and a literal `[END_TOOL_REQUEST]` sentinel, i.e. the
  formats small and fine-tuned models actually produce in the wild.
- **Bounded work:** `MAX_SCAN_CHARS = 20_000`, `MAX_JSON_CANDIDATES = 20`,
  `MAX_JSON_CANDIDATE_CHARS = 8_000`.
- **Field-name tolerance:** `readToolName()` accepts `name`, `tool_name`, `tool`,
  `function_name`; `hasToolArgs()` accepts `arguments`, `args`, `input`, `parameters`.
- **A schema-echo exclusion.** `hasToolArgs()` rejects records that look like a tool
  *definition* rather than a call — `typeof record.description === "string"`,
  `record.type === "function"`, `parameters?.type === "object"`, or `parameters?.properties`
  present. Comment: *"Keep tool-definition schemas literal."* This is a real small-model
  failure: the model echoes its own tool list back and a naive repairer executes it.
- **Safety rails in `contracts.ts`:** `allowedToolNames` (an allowlist), `maxPayloadBytes`, a
  `PlainTextToolCallNameMatcher { hasExactName, hasNamePrefix }`, and **protected ranges** —
  `PlainTextToolCallProtectedRange { start, end }`, a resolver
  `(text: string) => readonly …[]`, and `isOffsetInProtectedRanges(offset, ranges)`. A
  protected range is documented as a *"Source range that must remain literal user-visible
  text"*: a fenced code block the user asked to see must not be silently consumed and
  executed.
- Built on `@openclaw/normalization-core` (`extractBalancedJsonPrefix`, `safeParseJson`,
  `asOptionalRecord`, `normalizeOptionalString`) — JSON recovery is not hand-rolled.

**For S-CLAW:** of everything in this audit, this attacks S-CLAW's measured bottleneck most
directly, because it converts total failures into successes **without changing the model, the
prompt, or the tool count**. A small Python version — prefilter, four shape classifiers,
tolerant field names, the schema-echo exclusion, an allowlist of real S-CLAW tool names, and
protected ranges — is a fraction of 4,296 lines. The allowlist is what makes it safe: a
repaired call must name a tool that exists.

**Caveats, stated plainly.** The package is `"private": true` — not published to npm, so it
cannot be installed, only ported. It depends on another workspace package. It is TypeScript
and S-CLAW's backend is Python. And OpenClaw is the project the user is explicitly competing
with: MIT permits the port with notice retention, but see `CODE_REUSE_AND_LICENSES.md`.

### 3d. The two approaches are complements, not alternatives

Goose constrains the output format and writes a prompt a tiny model can follow. OpenClaw
accepts a messy format and repairs it. **S-CLAW should do both**, in this order: first the
prompt (free, measurable with the existing harness), then the repair layer (catches what the
prompt does not). Doing only the repair layer papers over a fixable prompt; doing only the
prompt leaves the residual failures as errors the user sees.

---

## 4. Reasoning / `<think>` handling

`goose/crates/goose-local-inference/src/thinking_output.rs` (81 lines, first 30 read):

```rust
pub(crate) struct ThinkingOutputFilter {
    enabled: bool,
    saw_structured_reasoning: bool,
    think_filter: ThinkFilter,
    pending_inline_thinking: String,
    accumulated_thinking: String,
}
```

built by `new(enable_thinking: bool, generation_prompt: &str)`, which — when thinking is
enabled and the prompt is non-empty — seeds the filter with the generation prompt
(`think_filter.push(generation_prompt)`). That handles the case where the chat template has
**already opened** a `<think>` tag before the model emits its first token; without it, the
filter never sees the opening tag and leaks reasoning to the user.
`push_structured_reasoning(&mut self, reasoning: &str) -> Option<String>` returns `None` for
empty input. Backed by `goose_provider_types::thinking::{FilterOut, ThinkFilter}`, i.e. the
`<think>` state machine itself lives in the shared types crate and is reused across providers.

The five fields are a map of the cases a correct implementation must handle: on/off; reasoning
arriving as a *structured field* versus inlined in the token stream (`saw_structured_reasoning`
distinguishes them); a tag split across stream chunks (`pending_inline_thinking`); and
retaining the reasoning for display or logging (`accumulated_thinking`).

**For S-CLAW:** Qwen3 emits `<think>` blocks, and S-CLAW streams. A naive implementation shows
the user a partial `<thin`, or leaks reasoning when a tag straddles a chunk boundary. This
struct is the specification. 81 lines, self-contained, Apache-2.0.

**Agent Zero and others:** not established. **Gap.**

---

## 5. Cloud providers and model switching

### OpenClaw: a provider is a plugin

`openclaw/extensions/` holds 189 directories, most of them providers: `alibaba`,
`amazon-bedrock`, `amazon-bedrock-mantle`, `anthropic`, `anthropic-vertex`, `apple-fm`,
`arcee`, `azure-speech`, `baseten`, `beam`, `bifrost`, `byteplus`, `celeris`, `cerebras`,
`chutes`, `clawrouter`, `cloudflare`, `cloudflare-ai-gateway`, `codex`, `cohere`, `comfy`, and
beyond. Each carries an `openclaw.plugin.json` manifest (format verified from
`extensions/cua-computer/openclaw.plugin.json`, read in full — see `PROJECT_ANALYSIS.md` §3).

Backed by a typed catalogue in `packages/model-catalog-core/src/`: `provider-id.ts`,
`canonical-model-key.ts`, `provider-model-id-normalization.ts`,
`provider-model-id-normalize.ts`, `configured-model-refs.ts`, `model-catalog-refs.ts`,
`model-catalog-types.ts`, `model-catalog-normalize.ts`, `model-catalog-pricing.ts`,
`model-catalog-reasoning.ts`, `model-inference-capabilities.ts`,
`decision-route-capabilities.ts`, `decision-answer-capabilities.ts`,
`remote-catalog-bundle.ts` — each with a `*.test.ts`. The existence of *two* separate
normalisation modules for provider model ids tells you how much of the real work is
reconciling the different names providers give the same model.

**`model-inference-capabilities.ts`, read in full** (13 lines) and worth quoting for its
comments:

```ts
/** Provider-declared facts for one physical route; never execution or grounding authority. */
export const ModelInferenceCapabilitiesSchema = z.object({
  /** Explicit declarations never infer chat support from text encoding or structured output. */
  chat: z.boolean(),
  decision: DecisionRouteCapabilitiesSchema.optional(),
});
```

Two rules in two comments. Capabilities are **declared by the provider, never inferred** from
incidental evidence like text encoding or structured-output support. And a declaration is a
*fact*, "never execution or grounding authority" — knowing a model *can* do something is not
permission for it to do it.

**For S-CLAW this is independent confirmation of an existing decision.** S-CLAW keeps nine
capabilities (BROWSER, DESKTOP, FILES, DOCUMENTS, DATA, DESIGN, ORGANISER, CODE, REASONING)
on one axis and a risk model (READ_ONLY / LOCAL_WRITE / EXTERNAL / DESTRUCTIVE) on another.
That separation is right and should not be collapsed. `remote-catalog-bundle.ts` further
suggests the catalogue can be refreshed from a remote bundle rather than only shipped in the
binary — relevant to S-CLAW's brain catalogue and the website, but **unread**.

**The recommendation this supports:** make a *model provider* a plugin in S-CLAW's own plugin
format. The user already wants a plugin installer, a website catalogue and third-party
authors; providers are the easiest plugin category to support (an endpoint, a key, a model
list) and the one that most directly serves "the brain is going to be online."

### Eigent: a provider is a validated database row

`eigent/server/app/model/provider/provider.py` (read, first 50 lines). `class Provider` fields:
`user_id` (indexed), `provider_name`, `model_type`, `api_key`, `endpoint_url`,
`encrypted_config: dict | None` (JSON), `prefer: bool`, `is_valid: VaildStatus`,
`execution_revision: str` (`String(32)`). `class VaildStatus(IntEnum)` has
`not_valid = 1`, `is_valid = 2` (spelling as in source).

Three ideas worth taking:

- **Validity is persisted state and starts false.** A provider is `not_valid` until a real
  check passes. This encodes the user's own standing rule — *"Do not claim that an API works
  unless an actual request has been made and its result verified"* — in the data model, so the
  honest answer is the default rather than a discipline someone has to remember.
- **`prefer: bool`** gives one provider precedence without reordering rows.
- **`execution_revision`**, commented *"Assigned by database triggers. It is random, never a
  hash of a key/token."* A deliberately random revision token, so it cannot leak anything
  about the key — a good habit, consistent with "Mask secrets by default."

**One thing S-CLAW must not copy:** `api_key` is a plain column. On Windows, keys belong in
Credential Manager / DPAPI, per the standing rules on secrets.

### Goose: a `Provider` trait plus injected configuration

`goose/crates/goose/src/providers/base.rs` (69 lines) holds the `Provider` trait —
`goose/AGENTS.md` line 103 states *"Provider: Implement Provider trait see providers/base.rs"*
(and that same file's line 131 names a non-existent agent path, so treat its claims as
hypotheses to check). `goose/crates/goose/src/providers/local_inference.rs` (76 lines, read) is
a shim re-exporting `goose_providers::local_inference::*`, using the
`GOOSE_LOCAL_MODEL_SETTINGS` config key and resolver/writer injection
(`set_string_param_resolver`, `set_model_settings_resolver`, `set_model_settings_writer`).
Local inference is therefore just another provider from the agent's point of view — the agent
loop does not know whether the model is local, which is the property that makes "same app,
local or online brain" tractable.

### Per-model settings

`goose/crates/goose-local-inference/src/management.rs` exposes `get_model_settings()` and
`update_model_settings()`, with DTO conversions that reveal the structure: a `ModelSettings`
contains a `SamplingConfig` (`sampling_to_dto` `:445`), a `ToolCallingMode`
(`tool_calling_to_dto` `:491`), and a `ChatTemplate` (`chat_template_to_dto` `:507`).
Settings are **per model**, not global, and versioned at the API boundary via DTOs rather than
exposing internal structs.

**For S-CLAW:** a 0.6B Tiny brain and an 8B brain should not share sampling parameters or a
tool-calling mode. S-CLAW's catalogue should carry per-brain settings.

### Gaps

- **Streaming:** no project's streaming implementation was read end to end.
  `thinking_output.rs` establishes that Goose filters *while* streaming, and
  `OpenHands/src/hooks/use-await-context-compaction.ts` (unread) suggests OpenHands awaits
  compaction in the UI. Beyond that, **nothing is established** about chunk handling,
  backpressure, or cancellation mid-stream.
- **Retries and timeouts at the provider layer:** `openclaw/packages/retry/src/` exists
  (`index.ts` + `index.test.ts`) and was **not read**. This is a notable gap, because retry
  and timeout policy is exactly where the user's complaints about slowness and errors would
  surface.
- **Fallback between providers:** not established anywhere. Eigent's `prefer` flag hints at
  preference ordering but I did not find or read fallback logic.
- **Cost/quota handling:** `model-catalog-pricing.ts` exists in OpenClaw and was **not read**.

---

## 6. Failure and timeout handling (what was actually found)

### Per-command timeouts, from the environment — Eigent

`eigent/backend/app/agent/toolkit/hybrid_browser_toolkit.py`:
`_timeout_value_to_seconds(value, *, fallback_seconds)` `:58`,
`_env_timeout_seconds(name, fallback_seconds)` `:74`, `_env_positive_int(name, fallback)` `:80`,
and the method `_command_timeout_seconds(self, command)` `:147`.

The timeout is **per command**, not global, and overridable from the environment without a
code change. `visit_page` and a click do not deserve the same budget. Every value has an
explicit fallback, so a missing or malformed environment variable degrades rather than fails.

### Fail all pending work when the transport dies — Eigent

`_fail_all_pending(self, exc)` `:141`. When the WebSocket dies, every in-flight command is
failed explicitly with the exception.

This is worth dwelling on, because it is the mechanism behind a user complaint already on
record. Without it, pending futures are never resolved, the caller waits forever, and the
product looks frozen — *"I just told it thank you / And it's taking a year to reply."* A
transport that can die must fail its pending work, loudly. S-CLAW has three such transports:
HTTP to `llama-server`, HTTP to its own FastAPI backend, and CDP to Chromium.

### Bound the resources an agent can accumulate — Eigent

`_max_session_tabs` `:179`, `_max_managed_tabs_per_endpoint` `:185`,
`_track_and_limit_tabs` `:208`, with `_touch_session_tab` `:194` / `_forget_session_tab` `:201`
and `_tab_registry_key` `:191`. An agent that opens a tab per step would otherwise exhaust
memory; the touch/forget pair is an LRU-shaped registry, so the cap evicts the least recently
used rather than refusing new work.

### Serialise navigations — Eigent

`_navigation_lock_key` `:168`, `_navigation_lock_wait_seconds` `:172`,
`_endpoint_lock_key(cdp_url)` `:95`. Two concurrent navigations on one page are serialised
with a bounded wait rather than racing.

### Do not let a system proxy eat localhost — Eigent

`_ensure_local_no_proxy(self)` `:319`. A configured system HTTP proxy will otherwise intercept
connections to `localhost`, breaking local CDP.

**This one is directly actionable for S-CLAW and is not hypothetical.** S-CLAW talks to
`127.0.0.1` for both its FastAPI backend (with a per-launch token) and `llama-server`. On a
corporate Windows machine with `HTTP_PROXY`/`HTTPS_PROXY` set — common — those connections can
be routed into the proxy and fail. The fix is to ensure `NO_PROXY` covers `127.0.0.1` and
`localhost` for S-CLAW's own clients. One line; prevents a failure mode that would look to the
user like "the app is broken on my work laptop."

### Connection pooling — Eigent

`class WebSocketConnectionPool` `:620`, `get_connection(...)` `:627`,
`close_connection(session_id)` `:698`, plus `_close_current_websocket` `:309` and
`cleanup_tab_tracking` `:594`. Browsers are reused across tasks, not launched per task — which
is both a speed and a resource-leak concern.

### Honest gaps on failure handling

- **`openclaw/packages/retry/` was not read.** Retry policy, backoff shape and jitter are
  therefore unestablished anywhere in this audit.
- **Model-request timeouts** (as opposed to browser-command timeouts) were not found in any
  project. What a project does when `llama-server` stops responding mid-generation is unknown.
- **`tool-call-repair/diagnostics.ts`** was not read; its name suggests repair failures are
  reported rather than silently dropped, which would matter for debugging, but that is
  inference from a filename.

---

## 7. Summary: the local-model checklist this audit produces

A list of behaviours S-CLAW's model layer should have, each traced to verified source.

**Rows marked "DONE" were found already implemented in S-CLAW's own code** when I checked it
after surveying the clones (see the CORRECTION in §2). Rows 11 and 13 are **partly** done:
`backend/claw/agent/jsonfix.py` (113 lines) already repairs nearly-valid JSON and extracts the
first `{...}` from chatter or fences — itself ported from OpenClaw with attribution in
`backend/claw/agent/OPENCLAW_LICENSE.txt`. What it does not cover is the non-JSON shapes
(XML `<tool_call>`, bracketed, ReAct `Action:`), the tool-name allowlist, protected ranges, or
the tool-definition-echo exclusion.

| # | Behaviour | Evidence | S-CLAW status |
|---|---|---|---|
| 1 | Probe the server for the window it actually serves; never assume | hermes `agent_init_ollama.py` | **DONE** (llama-server, `/props`) |
| 2 | Derive every budget and compaction threshold from the probed number | hermes `_clamp_compressor_to_ollama_num_ctx` | **GAP** — catalogue budget is a constant |
| 3 | Log which source the window came from (config / probe / default) | hermes, same file | partly — logs asked vs actual |
| 4 | Cap a probed window by explicit config (VRAM safety) | hermes, same file | n/a for llama-server (clamps down itself) |
| 5 | Never let detection failure be fatal — degrade and log at debug | hermes, same file | **DONE** |
| 6 | Gate local inference on CPU features before load, naming each missing one | goose `llamacpp/mod.rs:316` | **GAP** — `models/hardware.py` reads RAM/cores/GPU, no CPU flags |
| 7 | Decide native-vs-emulated tool calling per model, from its own template | goose `llamacpp/mod.rs:114` | not checked |
| 8 | Offer a three-state override (Auto / ForceNative / ForceEmulated) | goose, same file | not checked |
| 9 | Ship a dedicated short system prompt for tiny models | goose `prompts/tiny_model_system.md` | **GAP** — Tiny brain is in `runtime/catalog.py`, no Tiny-specific prompt |
| 10 | Let a tiny model *ask* what tools exist instead of prompting the catalogue | goose `tool_emulation.rs` | not checked |
| 11 | Repair malformed tool calls across JSON / XML / bracketed / ReAct shapes | openclaw `tool-call-repair` | partly — JSON only (`jsonfix.py`) |
| 12 | Allowlist repaired tool names; protect user-visible text ranges | openclaw `contracts.ts` | not checked |
| 13 | Reject tool *definitions* echoed back as calls | openclaw `attempt.ts` `hasToolArgs` | **GAP** |
| 14 | Filter `<think>` correctly while streaming, incl. template-opened tags | goose `thinking_output.rs` | **GAP** — no `<think>` handling found (but see note) |
| 15 | Keep per-model settings (sampling, tool mode, template), not global | goose `management.rs` | not checked |
| 16 | Let the user point at an existing Ollama / LM Studio / llama.cpp server | eigent `localModels.ts` | partly — `ollama.py` + `openai_compat.py` exist |
| 17 | Persist provider validity, starting at not-valid until verified | eigent `provider.py` | not checked |
| 18 | Per-command timeouts with env overrides and explicit fallbacks | eigent `hybrid_browser_toolkit.py` | not checked |
| 19 | Fail all pending requests when a transport dies | eigent `_fail_all_pending` | not checked |
| 20 | Exclude localhost from any configured system proxy | eigent `_ensure_local_no_proxy` | **DONE** — `trust_env=False` on every httpx client |

Items 1–5, 6, 9, 18–20 are small and independent. Items 1 and 20 should be checked first,
because both could already be causing errors the user has reported, and neither requires a
design decision.


### Notes on the status column

**Item 20 is already solved, and solved better than Eigent solves it.** Every S-CLAW HTTP
client passes `trust_env=False` — `backend/claw/runtime/engine.py:225`,
`backend/claw/models/openai_compat.py:139`, `backend/claw/models/ollama.py:87` and `:116`.
That disables proxy-environment inheritance outright rather than patching `NO_PROXY`, which is
the stronger fix. **The recommendation in `PERFORMANCE_ANALYSIS.md` §3 to add a localhost
proxy exclusion is therefore already satisfied; disregard it.**

**Item 14 needs a caveat before anyone acts on it.** I found no `<think>` handling in
`backend/claw/`, but S-CLAW's planner requests schema-constrained JSON
(`openai_compat.py:102`: `response_format = {"type": "json_object", "schema": json_schema}`),
and a grammar-constrained decode will not emit `<think>` tags in the first place. So this may
be a non-issue for the planner path and a real one only for free-text replies (chat, `see()`,
summaries). **Verify against a real Qwen3 brain before building anything** — exactly the sort
of claim that should not be acted on from a grep.

**Items 7, 8, 10, 12, 15, 17, 18, 19 remain genuinely unchecked** against S-CLAW's source. I
checked the ones where the clones offered a specific, searchable mechanism; the rest need a
deliberate read of S-CLAW's own code, which is listed as the first task in
`IMPLEMENTATION_ROADMAP.md`.
