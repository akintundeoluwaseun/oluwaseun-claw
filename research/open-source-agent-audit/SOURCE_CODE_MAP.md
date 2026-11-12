# SOURCE_CODE_MAP.md

Every component below was located in a local clone and the stated declarations were
observed. Paths are relative to `/home/user/research-clones/`.

**Reuse classification** (as requested):
1. **Directly reusable** — can be lifted with attribution, little or no change.
2. **Reusable with modifications** — the logic transfers; the code needs porting.
3. **Architectural reference only** — copy the idea, write our own code.
4. **Not recommended** — do not take.

**Verification key:**
- `READ` — file opened, content quoted in this audit.
- `DECL` — declarations observed via grep (names and line numbers verified; bodies not read).
- `NAME` — existence and size verified only; contents not examined.

---

## A. Local model integration

### A1. `goose-local-inference` — the whole crate
- **Repo:** goose (Apache-2.0)
- **Path:** `goose/crates/goose-local-inference/src/`
- **Size:** 8,140 lines across 16 top-level `.rs` files, plus `llamacpp/` (2,113 lines) and
  `prompts/`
- **Verification:** `DECL` for `management.rs` and `llamacpp/mod.rs`; `READ` for the specific
  functions below
- **Files, measured:** `hf_models.rs` 3,082 · `mlx.rs` 1,157 · `lib.rs` 1,134 ·
  `tool_emulation.rs` 760 · `management.rs` 699 · `native_tool_parsing.rs` 343 ·
  `multimodal.rs` 336 · `model.rs` 135 · `paths.rs` 120 · `thinking_output.rs` 81 ·
  `huggingface_auth.rs` 64 · `config_resolver.rs` 60 · `tool_parsing.rs` 52 ·
  `backend.rs` 50 · `prompt_template.rs` 43 · `provider_utils.rs` 24; and
  `llamacpp/` = `mod.rs` 778 + `inference_engine.rs` + `inference_native_tools.rs` +
  `inference_emulated_tools.rs`
- **Why it matters:** this is the richest local-inference implementation of the six, and it
  solves S-CLAW's actual problems — llama.cpp lifecycle, tool-calling on small models,
  `<think>` stripping, CPU capability gating, model download and eviction.
- **Reuse:** **3 — architectural reference only.** It is Rust; S-CLAW's backend is Python.
  The *decisions* transfer almost one-for-one. Sub-components below are individually valuable.

### A2. `check_cpu_supports_local_inference()` — CPU gating before load
- **Repo:** goose (Apache-2.0)
- **Path:** `goose/crates/goose-local-inference/src/llamacpp/mod.rs:316` (x86_64 arm) and
  `:338` (non-x86_64 arm, returns `Ok(())`)
- **Verification:** `READ`
- **What it does:** before any local model loads, checks for `fma`, `avx2`, `f16c`, `bmi2`,
  `sse4.2` via `std::arch::is_x86_feature_detected!`, collects the *missing* ones, and fails
  with a message built by `unsupported_cpu_features_error_message()` (`:306`) naming exactly
  which instruction sets this CPU lacks and telling the user to "switch to a non-local
  provider."
- **How it works:** compile-time `#[cfg(target_arch = "x86_64")]` split so non-x86 targets
  compile to an unconditional success; runtime feature detection on x86_64; the error names
  every missing feature, not just the first.
- **Why it is useful to S-CLAW:** this is the direct answer to "the brain was not compatible
  with Standard." Today S-CLAW discovers incompatibility by failing at inference time, which
  the user experiences as "error, and it's even slow as fuck." Goose's answer is a
  **pre-flight check that names the reason**. In Python this is `cpuinfo` /
  `/proc/cpuinfo` flags, or on Windows reading CPUID — a short function, not a port.
- **Dependencies:** none beyond `std` and `anyhow`.
- **Reuse:** **2 — reusable with modifications** (reimplement in Python; the feature list and
  the "name every missing feature" error shape are the reusable parts).

### A3. Tool-calling mode: native vs emulated
- **Repo:** goose (Apache-2.0)
- **Paths:**
  - `goose/crates/goose-local-inference/src/llamacpp/mod.rs:114` —
    `fn should_use_native_tool_calling(mode: ToolCallingMode, has_tools: bool, template_supports_native: bool) -> bool`
  - `:64` — `fn supports_native_tool_calling(...)`
  - `:56` — `fn template_result_supports_native_tool_calling(result: &ChatTemplateResult) -> bool`
  - `:127` — `fn is_legacy_builtin_template_name(...)`
  - `:210` — `fn load_chat_templates(...)`; `:266` — `fn select_generation_template(...)`
  - `:185` — `fn missing_chat_template_error(...)`
  - `llamacpp/inference_native_tools.rs`, `llamacpp/inference_emulated_tools.rs`
- **Verification:** `READ` for `:56`–`:130`
- **What it does:** decides, per request, whether to let the model emit real tool calls or to
  fall back to text-pattern emulation. `ToolCallingMode` has three values — `Auto`,
  `ForceNative`, `ForceEmulated`. In `Auto`, the decision comes from whether the model's own
  chat template supports it.
- **How it detects support — the clever part:** it performs a **dry run of the chat template**.
  `supports_native_tool_calling()` builds `OpenAIChatTemplateParams { ..., use_jinja: true,
  parse_tool_calls: true, ... }`, calls `loaded.model.apply_chat_template_oaicompat(template,
  &params)`, and then asks `template_result_supports_native_tool_calling()`, which requires
  **both** `result.parse_tool_calls` **and** a non-empty `result.parser`. A template error is
  caught and logged at debug level and treated as "not supported" — it does not fail the
  request. The code carries an honest comment that llama.cpp exposes
  `common_chat_templates_get_caps` in C++ but the `llama-cpp-2` 0.1.146 Rust binding does not
  expose it yet, so the dry-run stands in until it does.
- **Why it is useful to S-CLAW:** S-CLAW ships Qwen3-VL 2B/4B/8B and a Qwen3-0.6B Tiny. A 0.6B
  model will not reliably emit well-formed tool calls. Rather than one global setting, Goose
  asks the *loaded model's own template* and degrades to emulation automatically. S-CLAW uses
  `llama-server` (the HTTP server), which exposes template capability differently from the
  in-process binding, so the mechanism needs adapting — but the three-state mode and the
  "ask the model, don't assume" principle are directly applicable.
- **Reuse:** **3 — architectural reference only** (Rust + in-process llama.cpp bindings).

### A4. `tool_emulation.rs` — text-pattern tool calls for small models
- **Repo:** goose (Apache-2.0)
- **Path:** `goose/crates/goose-local-inference/src/tool_emulation.rs` (760 lines)
- **Verification:** `READ` (module doc + first 45 lines)
- **What it does:** per its own module doc — "Models that do not have native tool-calling
  support are prompted to emit shell commands as `$ command` on a new line, JavaScript in
  ```` ```execute_javascript ```` fences, and JSON discovery arguments in
  ```` ```list_functions ```` or ```` ```get_function_details ```` fences. The parser converts
  those patterns into Goose tool-call messages."
- **How it works:** parses the model's **Markdown** with `pulldown_cmark` (`Parser`, `Event`,
  `Tag`, `CodeBlockKind`) rather than regexing raw text, so a fenced code block is identified
  structurally. Constants `SHELL_TOOL = "developer__shell"` and
  `CODE_EXECUTION_TOOL = "execute_javascript"`. Emits `rmcp::model::CallToolRequestParams`
  with a `Uuid` per call.
- **Paired prompt:** `load_tiny_model_prompt()` renders
  `goose/crates/goose-local-inference/src/prompts/tiny_model_system.md` through
  `prompt_template::render_template` with a context of `{os, working_directory, shell}`,
  where `os` is resolved at compile time via `cfg!(target_os = ...)` to `"macos"` /
  `"linux"` / `"windows"` / `"unknown"`, `working_directory` from `env::current_dir()` and
  `shell` from `$SHELL` defaulting to `/bin/sh`. A template failure logs a warning and falls
  back — it does not panic.
- **Why it is useful to S-CLAW:** this is the *same problem* S-CLAW measured — the brain
  choosing the wrong capability or failing to emit a usable call. Goose's answer has two
  halves, and both are cheap: a **dedicated tiny-model system prompt**, and a **parser that
  accepts the sloppy format a tiny model actually produces**. See A5 for the stronger version.
- **Reuse:** **3 — architectural reference only** for the Rust; the prompt file itself is **1**.

### A5. `tiny_model_system.md` — the tiny-model system prompt
- **Repo:** goose (Apache-2.0)
- **Path:** `goose/crates/goose-local-inference/src/prompts/tiny_model_system.md` — **21 lines**
- **Verification:** `READ` in full
- **What it does:** the entire system prompt for a model too small to follow a normal agent
  prompt. Its technique, in order: (1) state the agent *acts* and does not explain — "you do
  not explain how to do things, you DO them directly"; (2) inject `{{os}}`, `{{shell}}`,
  `{{working_directory}}`; (3) "take action immediately. Do not describe what you would do or
  give instructions — execute the commands yourself"; (4) give the output format in **one
  line with a literal example** ("start a new line with `$`" then `$ ls`); (5) "Keep your
  responses brief"; (6) a **full worked example** of a user turn and the model's correct reply;
  (7) tell it what the tool result will look like and that it must not repeat commands; (8) a
  negative rule — "Do not use shell commands if you already know the answer."
- **Why it is useful to S-CLAW:** 21 lines, no framework, and it attacks exactly the failure
  modes measured on S-CLAW's own 2B brain (narrating instead of acting; repeating a step;
  reaching for a tool when none is needed). S-CLAW's held-out capability accuracy moved 56% →
  69% on three prompt changes; this file is a short list of further changes to try, and it is
  the single cheapest experiment in this audit. The one-worked-example and
  "don't-repeat-commands" techniques are not currently in S-CLAW's planner prompt.
- **Licensing note:** it is prose under Apache-2.0. Taking its *techniques* carries no
  obligation at all. Copying its text would require the Apache-2.0 notice, and would also
  import Goose's identity ("You are goose, an autonomous AI agent created by AAIF") — so
  **adapt, do not copy**.
- **Reuse:** **1 — directly reusable** as a model to imitate; **do not paste verbatim**.

### A6. `thinking_output.rs` — streaming `<think>` filter
- **Repo:** goose (Apache-2.0)
- **Path:** `goose/crates/goose-local-inference/src/thinking_output.rs` (81 lines)
- **Verification:** `READ` (first 30 lines)
- **What it does:** `struct ThinkingOutputFilter { enabled, saw_structured_reasoning,
  think_filter: ThinkFilter, pending_inline_thinking: String, accumulated_thinking: String }`,
  built by `new(enable_thinking: bool, generation_prompt: &str)` and fed by
  `push_structured_reasoning(&mut self, reasoning: &str) -> Option<String>`. Backed by
  `goose_provider_types::thinking::{FilterOut, ThinkFilter}`.
- **How it works:** two separate fields for *pending* and *accumulated* thinking, and a
  `saw_structured_reasoning` flag so a model that returns reasoning as a structured field is
  handled differently from one that inlines `<think>` tags in the token stream. It seeds the
  filter with the `generation_prompt` on construction when thinking is enabled — which handles
  the case where the template has already opened a `<think>` tag before the model emits a
  single token. `push_structured_reasoning` returns `Option<String>`, i.e. nothing is emitted
  for empty reasoning.
- **Why it is useful to S-CLAW:** S-CLAW's brain is Qwen3, which emits `<think>` blocks. Doing
  this correctly *while streaming* is fiddly — a naive implementation shows the user a partial
  `<thin` or leaks reasoning when the tag is split across chunks. The state fields here are a
  map of the cases you must handle.
- **Reuse:** **2 — reusable with modifications** (small, self-contained; the state design is
  the value).

### A7. `management.rs` — local model lifecycle
- **Repo:** goose (Apache-2.0)
- **Path:** `goose/crates/goose-local-inference/src/management.rs` (699 lines)
- **Verification:** `DECL` (public API observed by grep)
- **Public API, verified:** `list_models()` `:37` · `search_huggingface_models()` `:74` ·
  `huggingface_repo_variants()` `:87` · `download_model()` `:130` · `download_progress()`
  `:188` · `cancel_download()` `:194` · `delete_model()` `:208` · `model_exists()` `:218` ·
  `evict_model()` `:225` · `get_model_settings()` `:232` · `update_model_settings()` `:239` ·
  `list_builtin_chat_templates()` `:250`
- **Internals of note:** `model_settings_to_dto`/`from_dto` `:395`/`:420`,
  `sampling_to_dto`/`from_dto` `:445`/`:469`, `tool_calling_to_dto`/`from_dto` `:491`/`:499`,
  `chat_template_to_dto`/`from_dto` `:507`/`:519`, `explicit_model_selection()` `:529`,
  `mark_download_failed()` `:609`
- **Why it matters to S-CLAW:** S-CLAW already ships a curated brain catalogue
  (Qwen3-VL 2B/4B/8B + Tiny, `ALLOWED_LICENSES = {"apache-2.0", "mit"}`). The functions
  S-CLAW does **not** have and that this file shows are needed:
  `cancel_download` (a user on a slow connection must be able to stop),
  `evict_model` (free RAM without deleting the file — distinct from `delete_model`),
  `download_progress` as a *queryable* call rather than only a push stream, and
  **per-model settings** (`get`/`update_model_settings`, with separate sampling and
  tool-calling and chat-template sub-objects). The DTO pairs show settings are versioned at
  the boundary rather than shared as internal structs.
- **Reuse:** **3 — architectural reference only.** Take the API surface as a checklist.

### A8. Hermes: Ollama `num_ctx` detection and compactor clamp
- **Repo:** hermes-agent (MIT)
- **Path:** `hermes-agent/agent/agent_init_ollama.py`
- **Verification:** `READ` (first ~60 lines, both functions)
- **Functions:** `_configure_ollama_num_ctx(agent, _model_cfg, _config_context_length)` and
  `_clamp_compressor_to_ollama_num_ctx(agent)`
- **Dependencies within the repo:** `agent.agent_runtime_helpers._ra`,
  `agent.model_metadata.{is_local_endpoint, query_ollama_num_ctx}`
- **What it does:** establishes the *real* context window a local server will serve, in a
  strict precedence order, then re-points the compactor at that number.
- **How it works, exactly:**
  1. `agent._ollama_num_ctx` starts `None`. A config override `model.ollama_num_ctx` wins
     outright; a non-integer override is caught (`TypeError, ValueError`) and logged at debug,
     not raised.
  2. Otherwise, **only if** `agent.base_url` is set **and** `is_local_endpoint(agent.base_url)`,
     it probes with `query_ollama_num_ctx(agent.model, agent.base_url, api_key=...)`. Note the
     guard it carries: "api_key may be a callable (Entra token provider); detection needs a
     string" — so it coerces to `""` unless it is really a `str`. A probe failure is swallowed
     at debug level.
  3. A probed value is then **capped** by `_config_context_length`, with the comment "GGUF
     metadata can advertise 256K+ and Ollama would allocate that much VRAM"; an *explicit*
     `num_ctx` is never overridden.
  4. It logs the **source** of the number, distinguishing `model.ollama_num_ctx` from
     "model max from Ollama `/api/show`", with the comment "Name the real source: a config
     override is honoured on any local server, `/api/show` is Ollama-only."
  5. `_clamp_compressor_to_ollama_num_ctx` then lowers `agent.context_compressor.context_length`
     to the effective `num_ctx` when the latter is smaller.
- **The bug it documents, in its own words:** "A config that sets only `model.ollama_num_ctx`
  (without `model.context_length`) previously left the compressor targeting the probed window
  while the server truncated/rejected at num_ctx — the compaction trigger could sit several
  times ABOVE the real served window and never fire."
- **Why this mattered, and the correction:** S-CLAW runs
  `llama-server` with a window of 8192 and budgets against it (`CATALOGUE_BUDGET = 1800`,
  `FULL_CATALOGUE_BUDGET = 4800`, `CHARS_PER_TOKEN = 3.5`). Those budgets are only correct if
  8192 is what the server *actually serves*. If `llama-server` was started with a smaller
  `--ctx-size`, or clamps it for VRAM, every budget downstream is wrong and any compaction
  threshold derived from 8192 may never fire — silently. The fix is the one Hermes applies:
  **query the server for its served window, derive budgets from the answer, log which source
  the number came from.** For `llama-server` the analogue of `/api/show` is `/props` (and
  `/v1/models`); that mapping is an assumption and is recorded as such in
  `MODEL_INTEGRATION.md`.
- **Licensing:** MIT. Short, self-contained Python.
- **Reuse:** **2 — reusable with modifications** (Python already; swap the Ollama probe for a
  `llama-server` probe).

  **CORRECTION — S-CLAW already does the llama-server half of this.**
  `backend/claw/models/openai_compat.py:68` queries `/props` for `n_ctx`,
  `backend/claw/agent/runner.py:228-245` logs asked-vs-actual and never lets the probe fail the
  task, and `planner.py:112` does the same. So the `/props` mapping above is not an assumption
  — it is S-CLAW's shipped implementation, and my earlier description of this as "the
  highest-value single file in this audit" was wrong. What remains missing is narrower: the
  **catalogue budget does not derive from the probed window** (`executor.py:1048`/`:1053` are
  absolute constants while `fit_context` at `:1234` uses the window), and the **Ollama path has
  no `num_ctx` handling at all**. Full detail in `MODEL_INTEGRATION.md` §2.

### A9. Eigent: `localModels.ts` — local provider catalogue
- **Repo:** eigent (Apache-2.0, per-file copyright header present)
- **Path:** `eigent/src/components/Settings/Models/localModels.ts`
- **Verification:** `READ` in full
- **What it defines:** provider ids `OLLAMA_PROVIDER_ID`, `VLLM_PROVIDER_ID`,
  `SGLANG_PROVIDER_ID`, `LMSTUDIO_PROVIDER_ID`, `LLAMA_CPP_PROVIDER_ID`; a type
  `LocalModelOption { id, name, defaultEndpoint, fetchPath?, parseModels? }`; the table
  `LOCAL_MODEL_OPTIONS`; helpers `toEndpointBaseUrl`, `getDefaultLocalEndpoint`,
  `getLocalPlatformName`; and parsers `parseOllamaModels`, `parseOpenAICompatibleModels`.
- **The endpoint table, verified:** Ollama `http://localhost:11434/v1` with discovery at
  `/api/tags`; vLLM `:8000/v1`; SGLang `:30000/v1`; LM Studio `:1234/v1`; llama.cpp
  `:8080/v1` with discovery at `/v1/models`.
- **How it works:** one row per local runtime, each carrying an OpenAI-compatible base URL, an
  optional discovery path, and an optional parser. Two parsers cover all five rows, because
  four of the five expose OpenAI-compatible `/v1/models` and only Ollama needs its own shape.
- **Why it is useful to S-CLAW:** S-CLAW ships `llama-server`, but a user who already runs
  Ollama or LM Studio has a model loaded and warm. This table is the complete, correct answer
  to "let the user point S-CLAW at a local server they already have," and the discovery paths
  and ports are the fiddly part. It is ~1 screen of data.
- **Licensing:** Apache-2.0 with a per-file `Copyright 2025-2026 @ Eigent.ai` header. Copying
  the file requires preserving that header and shipping the Apache-2.0 licence text and a
  NOTICE-style attribution. See `CODE_REUSE_AND_LICENSES.md`.
- **Reuse:** **1 — directly reusable** (with attribution) or **2** if re-expressed as Python
  data. The *facts* (ports, paths) are not copyrightable; the file's expression is.

### A10. Eigent: `Provider` persistence model
- **Repo:** eigent (Apache-2.0)
- **Path:** `eigent/server/app/model/provider/provider.py`
- **Verification:** `READ` (first 50 lines)
- **What it defines:** `class VaildStatus(IntEnum)` with `not_valid = 1`, `is_valid = 2`
  (spelling as in source); `class Provider(AbstractModel, DefaultTimes, table=True)` with
  `user_id` (indexed), `provider_name`, `model_type`, `api_key`, `endpoint_url`,
  `encrypted_config: dict | None` (JSON column), `prefer: bool`, `is_valid`, and
  `execution_revision: str` (`String(32)`, commented "Assigned by database triggers. It is
  random, never a hash of a key/token").
- **Why it is useful to S-CLAW:** three transferable ideas. (1) A provider's **validity is
  persisted state**, not an assumption — it starts `not_valid` and becomes `is_valid` only
  after a check. That is exactly the discipline the user's own rule demands: "Do not claim
  that an API works unless an actual request has been made and its result verified." Encoding
  that in the data model makes the honest answer the default. (2) `prefer` gives one provider
  precedence without reordering rows. (3) The `execution_revision` comment is a good security
  habit: a revision token that is deliberately random so it cannot leak anything about the key.
- **Caution:** `api_key` is a plain column. S-CLAW must not copy that; keys belong in Windows
  Credential Manager / DPAPI, consistent with the standing rule "Never include secrets in
  installers or source control" and "Mask secrets by default."
- **Reuse:** **3 — architectural reference only** (SQLModel + user-scoped multi-tenant schema;
  S-CLAW is single-user SQLite).

---

## B. Making a small model's output usable

### B1. `@openclaw/tool-call-repair` — repairing malformed tool calls
- **Repo:** openclaw (MIT at repo root)
- **Path:** `openclaw/packages/tool-call-repair/`
- **Size:** 4,296 lines of non-test TypeScript (`src/*.ts` excluding `*.test.ts`), across
  `attempt.ts`, `contracts.ts`, `diagnostics.ts`, `grammar.ts`, `payload.ts`,
  `promote.ts` (207 lines), `index.ts`, each with a sibling `*.test.ts`
- **Verification:** `READ` for `contracts.ts` (first 70 lines, which is the whole of the
  declarations shown) and `attempt.ts` (first 45 lines); `NAME` for the rest
- **Package manifest, read in full:** `{"name": "@openclaw/tool-call-repair", "version":
  "0.0.0-private", "private": true, "type": "module", "exports": {".": "./src/index.ts"},
  "dependencies": {"@openclaw/normalization-core": "workspace:*"}}`
- **What it does:** takes model output that *looks* like a tool call but is not a valid one,
  and recovers a real call from it. `attempt.ts` classifies four shapes, per its own type:
  `kind: "json_tool_call" | "xml_tool_call" | "bracketed_tool_call" | "react_action"`.
- **How it works, specifics observed:**
  - A **prefilter regex** runs before any parsing:
    `/(?:tool[_\s-]?calls?|function[_\s-]?call|["'](?:name|tool_name|function|arguments|args|input|parameters|tool_calls)["']|<\s*tool_call\b|Action\s*:|\[END_TOOL_REQUEST\])/i`
    — so the expensive path is skipped for ordinary prose. Note it catches ReAct's
    `Action:` and a literal `[END_TOOL_REQUEST]` sentinel.
  - Hard limits: `MAX_SCAN_CHARS = 20_000`, `MAX_JSON_CANDIDATES = 20`,
    `MAX_JSON_CANDIDATE_CHARS = 8_000` — a repair pass cannot become a denial of service on a
    rambling model.
  - `readToolName()` accepts **four** spellings of the name field: `name`, `tool_name`,
    `tool`, `function_name`.
  - `hasToolArgs()` accepts `arguments`, `args`, `input`, or `parameters` — and then
    **excludes a tool *definition* masquerading as a call**, by rejecting records that look
    like a JSON Schema (`typeof record.description === "string"`,
    `record.type === "function"`, `parameters.type === "object"`, or
    `parameters.properties` present). Its comment: "Keep tool-definition schemas literal."
    That is a real failure mode — a model that echoes its own tool list back.
  - `contracts.ts` adds an **allowlist** (`allowedToolNames`) and a payload cap
    (`maxPayloadBytes`), a name matcher interface (`hasExactName` / `hasNamePrefix`), and
    **protected ranges**: `PlainTextToolCallProtectedRange { start, end }`, a resolver type
    `PlainTextToolCallProtectedRangeResolver = (text: string) => readonly …[]`, and
    `isOffsetInProtectedRanges(offset, ranges)`. The documented purpose of a protected range
    is a "Source range that must remain literal user-visible text" — i.e. a fenced code block
    the user asked to see must **not** be silently eaten and executed as a tool call.
  - It uses `extractBalancedJsonPrefix`, `safeParseJson`, `asOptionalRecord` and
    `normalizeOptionalString` from `@openclaw/normalization-core` — so it does not hand-roll
    JSON recovery.
- **Why this is the most important model-layer finding in the audit:** S-CLAW's measured bottleneck
  is the brain's capability choice and plan quality on a 2B model. Of everything surveyed,
  this package is the most direct attack on that bottleneck, because it converts a class of
  *total* failures ("error") into successful calls without changing the model, the prompt or
  the tool count. The allowlist and protected-range design also make it safe: a repaired call
  must name a tool that exists, and text the user is meant to read is off-limits.
- **CORRECTION — S-CLAW already covers the JSON case.** `backend/claw/agent/jsonfix.py` (113
  lines) is itself ported from OpenClaw (`packages/ai/src/utils/json-parse.ts`, `repairJson`),
  with attribution in `backend/claw/agent/OPENCLAW_LICENSE.txt`. It repairs control characters
  and backslashes — with a Windows-path rule that matters a great deal here — and extracts the
  first `{...}` from surrounding chatter or ``` fences. So the remaining gap is narrower than
  stated above: the **non-JSON shapes** (XML `<tool_call>`, bracketed, ReAct `Action:`), the
  prefilter, the **tool-name allowlist**, the **protected ranges**, and the
  tool-definition-echo exclusion. The last three are the security-relevant ones and are the
  reason to do this at all.
- **Dependencies and portability — important caveat:** `"private": true` means this package is
  **not published to npm**. It cannot be installed; reuse means porting, and its dependency on
  `@openclaw/normalization-core` must be ported or replaced too. S-CLAW's backend is Python,
  so this is a reimplementation in any case. 4,296 lines is also far more than S-CLAW needs —
  the valuable core is the prefilter, the four shape classifiers, the field-name tolerance,
  the schema-echo exclusion and the protected ranges.
- **Licensing:** MIT (`openclaw/LICENSE`: "MIT License / Copyright (c) 2026 OpenClaw
  Foundation"). MIT permits reuse with notice retention. Note the user is explicitly
  competing with OpenClaw; porting its MIT code is legally fine but see
  `CODE_REUSE_AND_LICENSES.md` for the judgement call.
- **Reuse:** **3 — architectural reference only** in practice (private package, TypeScript,
  oversized), but it is the highest-value *design* to copy.

### B2. `model-inference-capabilities.ts` — declared, not inferred, capabilities
- **Repo:** openclaw (MIT)
- **Path:** `openclaw/packages/model-catalog-core/src/model-inference-capabilities.ts`
- **Verification:** `READ` in full (13 lines of source)
- **What it is, quoted:**
  ```ts
  /** Provider-declared facts for one physical route; never execution or grounding authority. */
  export const ModelInferenceCapabilitiesSchema = z.object({
    /** Explicit declarations never infer chat support from text encoding or structured output. */
    chat: z.boolean(),
    decision: DecisionRouteCapabilitiesSchema.optional(),
  });
  ```
- **Why it is useful to S-CLAW:** the two comments carry the whole lesson. First, capabilities
  are **declared by the provider, not inferred** — "never infer chat support from text encoding
  or structured output." Second, a declaration is a *fact*, "never execution or grounding
  authority" — knowing a model *can* do something is not permission for it to do it. S-CLAW
  has nine capabilities (BROWSER, DESKTOP, FILES, DOCUMENTS, DATA, DESIGN, ORGANISER, CODE,
  REASONING) and a separate risk model (READ_ONLY / LOCAL_WRITE / EXTERNAL / DESTRUCTIVE).
  This file is independent confirmation that keeping *capability* and *authority* as two
  separate axes is the right design, which is what S-CLAW already does.
- **Supporting files in the same package** (`NAME` only): `canonical-model-key.ts`,
  `configured-model-refs.ts`, `decision-answer-capabilities.ts`,
  `decision-route-capabilities.ts`, `model-catalog-normalize.ts`,
  `model-catalog-pricing.ts`, `model-catalog-reasoning.ts`, `model-catalog-refs.ts`,
  `model-catalog-types.ts`, `provider-id.ts`, `provider-model-id-normalization.ts`,
  `provider-model-id-normalize.ts`, `remote-catalog-bundle.ts` — each with `*.test.ts`.
  `remote-catalog-bundle.ts` suggests the catalogue can be refreshed from a remote bundle
  rather than only shipped in the binary; relevant to S-CLAW's own brain catalogue, but unread.
- **Reuse:** **3 — architectural reference only** (confirms an existing S-CLAW decision).

---

## C. Context management

### C1. `goose-context-management` — compaction as a library
- **Repo:** goose (Apache-2.0)
- **Path:** `goose/crates/goose-context-management/src/lib.rs` (70 lines)
- **Verification:** `READ` in full
- **What it defines:** `pub const DEFAULT_COMPACTION_THRESHOLD: f64 = 0.8`; traits
  `CompactionInput { fn messages(&self) -> Vec<Message>; fn templates(&self) -> Templates }`
  and `CompactionOutput { fn set_summary(&mut self, summary: Message); fn set_usage(&mut self, usage: ProviderUsage) }`;
  and `pub async fn compact<I, O>(model: &dyn CompactionModel, estimator: Option<&dyn TokenEstimator>, input: &I, output: &mut O) -> Result<()>`.
  Modules: `format`, `model`, `provider`, `structured`, `summarize`, `templates`. Re-exports
  include `format_message_for_compacting`, `CompactionModel`, `ProviderModel`,
  `TokenEstimator`, `CompactingProvider`, `FileActivity`, `StructuredSummary`, `summarize`,
  `Summary`, `Templates`.
- **Its own doc comment:** "Conversation compaction: summarizing a message history down to a
  single message so a conversation can continue past a model's context window." It then names
  "Three layers, smallest first" — `summarize` (model + messages → one summary message),
  `compact` (the trait-based API), and notes cross-language access is exposed via `goose-sdk`
  uniffi bindings for Python and Kotlin.
- **Design points worth copying:** compaction knows **nothing** about the caller's
  conversation type — the caller implements two traits, so S-CLAW's own message store needs no
  adapter layer. The token estimator is `Option<&dyn TokenEstimator>`, i.e. compaction works
  without one. `impl CompactionInput for Vec<Message>` gives a zero-effort default. And
  `StructuredSummary`/`FileActivity` show the summary is **not** just prose — file activity is
  tracked as structured data, so compaction does not lose "which files were touched", which is
  precisely the information an agent needs after a summary.
- **Why it is useful to S-CLAW:** S-CLAW's window is 8192 tokens — small — so compaction
  matters more, not less. The 0.8 threshold and the structured-summary idea are both directly
  applicable, and `FileActivity` answers a real problem: after a summary, S-CLAW's brain
  should still know which files the task has touched.
- **Reuse:** **3 — architectural reference only** (Rust), but with **2** potential via the
  documented `goose-sdk` uniffi Python bindings — unverified; I did not inspect `goose-sdk`
  or confirm a published Python package exists. Flagged as an open question.

### C2. Agent Zero token accounting
- **Repo:** agent-zero (MIT)
- **Path:** `agent-zero/helpers/tokens.py`
- **Verification:** `READ` (first 40 lines)
- **What it defines:** `APPROX_BUFFER = 1.1`, `TRIM_BUFFER = 0.8`,
  `EMBEDDED_IMAGE_DATA_PLACEHOLDER = "[embedded image data omitted from token estimate]"`,
  a compiled `_EMBEDDED_IMAGE_DATA_URL_PATTERN`, then
  `count_tokens(text, encoding_name="cl100k_base")` (via `tiktoken`, with
  `disallowed_special=()`), `approximate_tokens(text)` returning
  `int(count_tokens(text) * APPROX_BUFFER)`, and `sanitize_embedded_image_data_urls(text)`.
- **Why it is useful to S-CLAW:** three concrete things. (1) **Deliberate over- and
  under-estimation**: count × 1.1 when asking "will this fit", and trim to 0.8 when deciding
  how much to cut — asymmetric buffers, so a mis-estimate fails safe in both directions.
  S-CLAW currently uses a single `CHARS_PER_TOKEN = 3.5` divisor, which is both less accurate
  and has no safety margin. (2) `disallowed_special=()` — without this, `tiktoken` *raises* on
  text containing `<|endoftext|>`, which a model can easily emit; this is a crash S-CLAW would
  otherwise hit. (3) The base64-image sanitiser, which matters because S-CLAW's brain is
  Qwen3-**VL** and screenshots are routine: an unsanitised estimate on an inlined screenshot
  is wrong by orders of magnitude and would blow every budget silently.
- **Dependency:** `tiktoken` — a **new dependency** for S-CLAW. The standing rule is "Do not
  introduce new dependencies into the application," so this is a decision for the user, not
  for me. Note also that `cl100k_base` is OpenAI's tokeniser, **not Qwen3's**, so even with
  `tiktoken` the count is an approximation for S-CLAW's actual brain — which is arguably an
  argument for keeping a divisor but fixing the buffers.
- **Reuse:** **2 — reusable with modifications** for the buffer/sanitiser ideas; the `tiktoken`
  dependency is **not recommended** without the user's decision.

### C3. Other context/cache modules identified (bodies not read)
- `agent-zero/helpers/context.py`, `context_utils.py`, `cache.py` — `NAME`
- `agent-zero/extensions/python/job_loop/_50_trim_cache.py` — `NAME`; the numeric prefix shows
  an ordered extension pipeline
- `agent-zero/plugins/_context_window/api/context_window.py`,
  `agent-zero/plugins/_context_doctor/helpers/context_doctor.py` — `NAME`. A "context doctor"
  as a first-class diagnostic is an idea S-CLAW could use: a user-visible explanation of why
  the window filled.
- `hermes-agent/gateway/agent_cache_pressure.py` — `NAME`
- `goose/crates/goose-provider-types/src/cache_semantics.rs` — `NAME`
- `openclaw/extensions/amazon-bedrock/prompt-cache.runtime.ts` — `NAME`
- `OpenHands/src/hooks/use-await-context-compaction.ts` — `NAME`; the name indicates the UI
  *awaits* compaction, i.e. compaction is a visible, awaited event in the interface rather
  than a hidden background step.

---

## D. Memory

### D1. Agent Zero FAISS memory
- **Repo:** agent-zero (MIT)
- **Path:** `agent-zero/plugins/_memory/helpers/memory.py`
- **Verification:** `DECL` (class and method declarations with line numbers)
- **Structure, verified:** `class MyFaiss(FAISS)` `:41` adding `get_by_ids` `:43`,
  `aget_by_ids` `:47`, `get_all_docs` `:50`. Then `class Memory` `:54` with
  `_get_embedding_config` `:64`, `get(agent)` `:69`, `get_by_subdir` `:97`, `reload` `:126`,
  `initialize` `:133`, `__init__` `:251`, `preload_knowledge` `:259`,
  `_preload_knowledge_folders` `:307`, `get_document_by_id` `:337`, `embed_query` `:340`,
  `search_similarity_threshold` `:343`, `search_similarity_threshold_with_scores` `:373`,
  `delete_documents_by_query` `:385`, `delete_documents_by_ids` `:445`, `insert_text` `:470`,
  `insert_documents` `:475`, `update_documents` `:490`, `_save_db` `:497`,
  `_generate_doc_id` `:500`, `_find_exact_query_docs` `:506`, `_find_related_docs_by_ids` `:528`,
  `_save_db_file` `:548`, `_write_index_hash` `:554`, `_verify_index_hash` `:568`,
  `_get_comparator` `:586`, `_score_normalizer` `:607`, `_cosine_normalizer` `:612`,
  `format_docs_plain` `:620`, `get_timestamp` `:631`. Module functions:
  `get_custom_knowledge_subdir_abs` `:635`, `reload` `:644`, `_normalize_memory_match_text` `:649`,
  `_metadata_references_any` `:653`, `abs_db_dir` `:666`, `abs_knowledge_dir` `:676`.
- **Design points that justify calling this the strongest memory subsystem surveyed:**
  - **Index integrity.** `_write_index_hash` / `_verify_index_hash` — the on-disk FAISS index
    is hash-verified before use. Without this, a half-written or externally-edited index loads
    as plausible-looking garbage. No other project surveyed does this.
  - **Deletion is first-class and offered two ways** —
    `delete_documents_by_query` *and* `delete_documents_by_ids`, with a user-facing
    `memory_forget.py` tool and `memory_delete.py`. GDPR-shaped and simply correct: a user must
    be able to make the agent forget.
  - **Two normalizers** (`_score_normalizer`, `_cosine_normalizer`) — raw FAISS distances are
    not comparable across metrics, so a single similarity *threshold* only works if scores are
    normalised first. A threshold API without this is subtly broken.
  - `_find_exact_query_docs` alongside similarity search — exact match is handled separately
    rather than hoping the embedding ranks it first.
  - `get_by_subdir` / `abs_knowledge_dir` — memory is partitioned on disk, so a per-project or
    per-plugin memory is a path, not a schema change.
- **Siblings** (`NAME`): `memory_quality.py`, `memory_consolidation.py`,
  `plugins/_memory/tools/{memory_save,memory_forget,memory_delete}.py`,
  `plugins/_memory/api/memory_dashboard.py`. Consolidation and a dashboard mean memory is
  curated and inspectable, not write-only.
- **Dependencies:** FAISS + LangChain (`FAISS`, `Document`) + an embedding model. All **new,
  heavy dependencies** for S-CLAW, and an embedding model is an additional local model to ship
  or download. Against the standing rule on new dependencies, this is a user decision.
- **Why it is useful to S-CLAW:** S-CLAW stores state in SQLite with no semantic recall.
  SQLite's own FTS5 would give exact and keyword recall with **zero** new dependencies, and
  the parts of this design that matter most — index integrity, two deletion paths, exact-match
  alongside ranked match, on-disk partitioning, a dashboard — are all implementable on FTS5.
- **Reuse:** **3 — architectural reference only.** The dependency cost of a direct port is out
  of proportion to S-CLAW's current need.

---

## E. Browser and desktop automation

### E1. Eigent hybrid browser toolkit
- **Repo:** eigent (Apache-2.0)
- **Path:** `eigent/backend/app/agent/toolkit/hybrid_browser_toolkit.py` — **1,038 lines**
  (a real in-repo implementation, unlike `pyautogui_toolkit.py`)
- **Verification:** `DECL`
- **Structure, verified:** module helpers `_timeout_value_to_seconds` `:58`,
  `_env_timeout_seconds` `:74`, `_env_positive_int` `:80`, `_endpoint_lock_key` `:95`;
  `class SheetCell(TypedDict)` `:123`;
  `class WebSocketBrowserWrapper(BaseWebSocketBrowserWrapper)` `:129` with `__init__` `:130`,
  `_fail_all_pending` `:141`, `_command_timeout_seconds` `:147`, `_navigation_lock_key` `:168`,
  `_navigation_lock_wait_seconds` `:172`, `_max_session_tabs` `:179`,
  `_max_managed_tabs_per_endpoint` `:185`, `_tab_registry_key` `:191`,
  `_touch_session_tab` `:194`, `_forget_session_tab` `:201`, `_track_and_limit_tabs` `:208`,
  `_close_current_websocket` `:309`, `_ensure_local_no_proxy` `:319`, `_receive_loop` `:340`,
  `start` `:427`, `_send_command` `:453`, `visit_page` `:513`, `get_tab_info` `:550`,
  `close_tab` `:575`, `cleanup_tab_tracking` `:594`;
  then `class WebSocketConnectionPool` `:620` with `get_connection` `:627`,
  `close_connection` `:698`.
- **What it does:** drives a browser over a WebSocket/CDP connection rather than in-process,
  with a connection pool keyed by session and an endpoint-level lock.
- **The transferable engineering, and it is substantial:**
  - **Per-command timeouts, from the environment.** `_command_timeout_seconds(command)` is
    per-*command*, not global — `visit_page` and a click do not deserve the same timeout.
    Backed by `_env_timeout_seconds(name, fallback_seconds)` so an operator can retune without
    a code change, and `_timeout_value_to_seconds(value, *, fallback_seconds)` normalises
    whatever units arrive.
  - **`_fail_all_pending(exc)`.** When the socket dies, every in-flight command is failed
    explicitly. Without this, pending futures hang forever and the agent appears frozen. This
    is a known S-CLAW-shaped bug: the user's report "it's taking a year to reply" is exactly
    what an un-failed pending request looks like.
  - **Tab limits.** `_max_session_tabs`, `_max_managed_tabs_per_endpoint`,
    `_track_and_limit_tabs`, `_touch_session_tab` / `_forget_session_tab` and a
    `_tab_registry_key` — an LRU-ish registry that caps how many tabs an agent may hold open.
    An agent that opens a tab per step will otherwise exhaust memory; the user has already
    seen slowness that this class of bug produces.
  - **A navigation lock** (`_navigation_lock_key`, `_navigation_lock_wait_seconds`) — two
    concurrent navigations on one page are serialised instead of racing.
  - **`_ensure_local_no_proxy()`** — a *verified* real-world detail: a system HTTP proxy will
    otherwise intercept a connection to `localhost`, breaking local CDP. S-CLAW talks to
    `127.0.0.1` for its own backend and `llama-server`; this is a bug S-CLAW can hit on a
    corporate Windows machine with a proxy configured, and it is one line to prevent.
  - **A connection pool** with explicit `close_connection(session_id)` — browsers are not
    launched per task.
- **Dependencies:** inherits `BaseWebSocketBrowserWrapper` from `camel-ai` (not inspected),
  plus Playwright/CDP. S-CLAW already ships Playwright + Chromium, so the *techniques* land on
  existing infrastructure.
- **Reuse:** **2 — reusable with modifications** for the specific techniques (per-command
  timeouts, fail-all-pending, tab caps, navigation lock, no-proxy-for-localhost); **4 — not
  recommended** as a wholesale port, since it is built on a `camel-ai` base class.

### E2. OpenClaw computer use
- **Repo:** openclaw (MIT)
- **Paths** (`NAME` except where noted): `extensions/cua-computer/` (contains `api.ts`,
  `index.ts`, `src/`, `test/`, `index.test.ts`, `openclaw.plugin.json` [**READ**],
  `package.json`, `README.md`, `assets/`); `src/node-host/computer-command.ts` (49 lines);
  `src/node-host/desktop-stream-command.ts`; `src/node-host/runtime.computer.test.ts`;
  `src/node-host/desktop-stream-command.test.ts`; `src/gateway/desktop/`;
  `src/gateway/node-computer-use-descriptor.ts`;
  `src/agents/computer-use-node-capabilities.ts` (+ `.test.ts`);
  `src/agents/session-placement-computer.ts` (+ `.test.ts`);
  `src/shared/node-desktop-stream.ts`; `src/shared/worker-desktop-descriptor.ts`;
  `extensions/anthropic/session-catalog-desktop.ts` (+ `.test.ts`)
- **What the structure says** (inference from names + the manifest, not from reading bodies):
  computer use is a **plugin** (`categories: ["computer-use"]`) that declares a **node-host
  capability**, and a session is **placed** onto a host that has it
  (`session-placement-computer.ts`). The desktop is **streamed** (`node-desktop-stream.ts`,
  `desktop-stream-command.ts`). There is a `driverPath` config property and the description
  says "Experimental CUA Driver computer control for macOS, Windows, and Linux node hosts" —
  so the actual input injection is an **external driver binary**, not in-repo TypeScript.
- **Why it is useful to S-CLAW:** it corroborates a decision S-CLAW has already made —
  keeping the desktop-control executor local and separate from the brain. OpenClaw goes
  further by making the controlled machine a *placeable resource*, which S-CLAW does not need
  (one user, one laptop). The `openclaw.plugin.json` manifest is the genuinely valuable
  artefact here and is covered in `PROJECT_ANALYSIS.md` §3.
- **Reuse:** **3 — architectural reference only.** The manifest design is **1** as a model for
  S-CLAW's own `PLUGIN.md` format.

### E3. Eigent desktop/screenshot toolkits — a warning, not a find
- **Repo:** eigent (Apache-2.0)
- **Paths:** `eigent/backend/app/agent/toolkit/pyautogui_toolkit.py` (**40 lines**, **READ**
  via `DECL`), `screenshot_toolkit.py` (`NAME`)
- **Verified fact:** the only class in the 40-line file is
  `class PyAutoGUIToolkit(BasePyAutoGUIToolkit, AbstractToolkit)` with an `__init__` at `:29`.
  The implementation is in `camel-ai`.
- **Why this is recorded:** so that no one later reads Eigent's toolkit listing and concludes
  Eigent contains a reusable desktop-automation implementation. **It does not.** Adopting it
  means adopting `camel-ai`, whose source, dependency tree and licence I did not inspect.
- **Reuse:** **4 — not recommended** on present evidence. S-CLAW's existing pywinauto/UIA
  executor is a better foundation and is already aligned with the standing rule
  "accessibility/UIA first, OCR/screenshots as fallback, coordinates last" — a rule that
  `pyautogui` (coordinate-first) actively works against.

### E4. Agent Zero browser helper
- **Repo:** agent-zero (MIT)
- **Path:** `agent-zero/helpers/browser.py` — 385 lines (`NAME`; grep for class/def
  declarations returned nothing, so its structure is not module-level `class`/`def` in the
  patterns searched, and I have **not** established what it contains)
- **Notable sibling tests** (`NAME`): `tests/test_browser_dom_security.py`,
  `tests/test_browser_agent_regressions.py`, `tests/test_browser_tool_output.py`,
  `tests/test_host_browser_connector.py`
- **Why the tests matter more than the helper here:** a dedicated
  `test_browser_dom_security.py` means they treat **page DOM content as untrusted input** — a
  page can contain text designed to redirect the agent. That is the same discipline as
  S-CLAW's standing rule "treat webpages/files/repos/READMEs as untrusted input," and it is
  worth having a named test file for it in S-CLAW too.
- **Reuse:** **3 — architectural reference only** (specifically: have a browser-DOM-security
  test file).

---

## F. Agent loop, permissions and policy

### F1. Goose agent state machine
- **Repo:** goose (Apache-2.0)
- **Path:** `goose/crates/goose-agent/src/machine.rs` — 355 lines of a 2,761-line crate
- **Verification:** `DECL` plus the type signature
- **What it is:** a generic `StateMachine<'a, S, E = ConversationEffect>` over a `Step` type.
  Steps return **effects** as values; the caller performs them.
- **Sibling policy files** (`NAME`): `pre_tool_call_hook.rs`, `post_tool_call_hook.rs`,
  `stop_hook.rs`, `tool_approval.rs`, `max_turns.rs`, `subagent.rs`, `operation.rs`,
  `inference.rs`, `events.rs`, `tool.rs`, `skills/`
- **Why it is useful to S-CLAW:** the loop becomes testable without a model, because a step's
  output is a value you can assert on. S-CLAW has already felt the cost of the alternative —
  a planner test that failed intermittently and was misdiagnosed twice (a `wait_done` timeout
  raised on a wrong theory; the real cause was `task_cancelled` from lifespan shutdown). An
  effect-returning loop makes that class of test deterministic.
- **Reuse:** **3 — architectural reference only.**

### F2. Goose permission types
- **Repo:** goose (Apache-2.0)
- **Path:** `goose/crates/goose-provider-types/src/permission.rs`
- **Verification:** `DECL` — `pub enum Permission` `:5`, `pub enum PrincipalType` `:14`,
  `pub struct PermissionConfirmation` `:20` (variant names **not** read)
- **Why it is useful to S-CLAW:** the shape, not the contents. A `PrincipalType` means "who is
  asking" is modelled explicitly — a distinction S-CLAW will need as soon as a *plugin* can
  request an action, because a plugin-originated DESTRUCTIVE action should not be able to
  inherit the user's standing approval. `PermissionConfirmation` as a struct (rather than a
  bool) means a confirmation carries evidence of what was approved. S-CLAW's
  `PermissionPolicy.__init__` already forces DESTRUCTIVE=ALLOW → ASK, which is the right
  instinct; adding a principal is the natural next step for the plugin ecosystem.
- **Reuse:** **3 — architectural reference only.**

### F3. Hermes approval actor
- **Repo:** hermes-agent (MIT)
- **Path:** `hermes-agent/gateway/approval_actor.py` — `NAME` only, **not read**
- **Why recorded:** an approval **actor** implies approvals are a serialised mailbox rather
  than an inline callback, which would prevent two concurrent tool calls from racing to prompt
  the user. Relevant to S-CLAW's `PermissionPolicy`. **This is inference from a filename and
  must be verified before acting on it.**
- **Reuse:** unassessed — insufficient evidence.

### F4. OpenHands automation permissions (UI side)
- **Repo:** OpenHands (MIT)
- **Path:** `OpenHands/src/hooks/use-automation-permissions.ts` — `NAME` only, **not read**
- **Why recorded:** a React hook for automation permissions suggests permission state is
  surfaced in the UI as a first-class hook rather than per-dialog ad-hoc state. Relevant to
  S-CLAW's Electron renderer. **Not verified.**
- **Reuse:** unassessed — insufficient evidence.

---

## G. Plugin ecosystem

### G1. OpenClaw plugin manifest + catalogue contract
- **Repo:** openclaw (MIT)
- **Paths:** `openclaw/extensions/cua-computer/openclaw.plugin.json` (**READ in full**);
  `openclaw/packages/plugin-package-contract/src/` — `catalog-order.ts` (24 lines),
  `catalog-route.ts`, `categories.ts`, `recommended-prompts.ts` (34 lines), `index.ts`,
  `index.test.ts`; 338 lines total (`DECL`/`NAME`); `openclaw/packages/plugin-sdk/` (`NAME`)
- **Why it is the most relevant finding to the user's stated plan:** the user wants plugins in
  **his own format**, downloadable from his website, authored by third parties. The manifest
  is a 28-line worked example of what such a format needs, and S-CLAW's existing `PLUGIN.md`
  (`backend/claw/plugins/pack.py`, `docs/PLUGINS.md`) can adopt five of its fields without
  adopting any of its code: `categories`, `activation`, `configSchema` (JSON Schema,
  `additionalProperties: false`), `configGroups` (so the host renders settings from the
  manifest), and `recommendedPrompts`.
  `recommendedPrompts` deserves emphasis: it is how a plugin tells a small brain what it is
  for, which is exactly the lever S-CLAW measured as effective (the Blender plugin changed a
  real brain's plan from 5 steps to 3). A separate *catalogue* contract
  (`catalog-order.ts`, `categories.ts`) is also a direct lesson for the website side — the
  plugin store's ordering and categories are part of the contract, not a website detail.
- **Reuse:** **1 — directly reusable** as a format to imitate (a JSON schema shape is not
  meaningfully copyrightable and nothing need be copied verbatim); **3** for the TypeScript.

### G2. Agent Zero plugin layout
- **Repo:** agent-zero (MIT)
- **Path:** `agent-zero/plugins/` — 48 directories (`NAME`); inner shape verified for
  `_memory`, which contains `helpers/`, `tools/` and `api/`
- **What it shows:** a plugin contributes in three distinct ways at once — `tools/`
  (model-callable), `api/` (HTTP endpoints the UI can call, e.g. `memory_dashboard.py`), and
  `helpers/` (internal). Built-ins are prefixed `_`. Also
  `agent-zero/extensions/python/job_loop/_50_trim_cache.py`, whose `_50_` prefix shows an
  **ordered hook pipeline** — plugins insert themselves at a numbered position in a loop.
- **Why it is useful to S-CLAW:** S-CLAW's plugin format currently centres on skills/tools.
  The `api/` channel is the missing piece for the user's goal of a premium UI — the Photoshop
  plugin he describes would need its own settings or status panel, and that requires a plugin
  to serve UI endpoints, not just tools. The numeric-prefix ordering is a simple answer to
  "two plugins both want to modify the context."
- **Reuse:** **3 — architectural reference only.**

### G3. OpenClaw provider-as-extension
- **Repo:** openclaw (MIT)
- **Path:** `openclaw/extensions/` — 189 directories (`NAME`); provider names verified by
  listing (`alibaba`, `amazon-bedrock`, `anthropic`, `anthropic-vertex`, `apple-fm`, `arcee`,
  `baseten`, `beam`, `bifrost`, `byteplus`, `celeris`, `cerebras`, `chutes`, `clawrouter`,
  `cloudflare`, `cloudflare-ai-gateway`, `codex`, `cohere`, …)
- **Why it is useful to S-CLAW:** the user wants an *online* brain as well as a local one, and
  does not want to maintain a provider list by hand forever. Making a provider a plugin means
  a new provider ships without a release of the application — and it means the same plugin
  installer the user already wants for Photoshop/Blender also covers models.
- **Reuse:** **3 — architectural reference only**, but a strong recommendation; see
  `SCLAW_RECOMMENDED_ARCHITECTURE.md`.

---

## H. Testing and release practice

### H1. OpenHands Windows-install E2E — the most transferable practice found
- **Repo:** OpenHands (MIT)
- **Paths:** `OpenHands/playwright.windows-install.config.ts` (**READ**, first 22 lines);
  referenced from it: `.github/workflows/windows-install-e2e.yml` and
  `playwright.mock-llm.config.ts` (both `NAME`, not read)
- **Verified content:** the header comment quoted in full in `PROJECT_ANALYSIS.md` §6, plus
  the code defaults `MOCK_LLM_PORT ?? "9999"`, `CANVAS_URL ?? "http://127.0.0.1:8000"`,
  `MOCK_LLM_PYTHON ?? "python"`, and the note that "The shared helpers read these at import
  time."
- **What it does:** a CI job on **Windows** installs the **packed tarball globally** and runs
  the user-facing command "the way a Windows user does (README Option 1)", then points
  Playwright specs at that already-running stack. The config deliberately does **not** start
  the app — only a mock LLM server.
- **Why this is the most important practice in the audit for this project specifically:**
  S-CLAW is developed on Linux and shipped to Windows, and that gap has repeatedly forced
  honest-but-unsatisfying BLOCKED statuses, plus two real incidents the user felt: a mangled
  filename (`backend/hat(?:.?s| is) in)|`) that Windows literally cannot check out, which
  broke every Windows build at step 2; and two folder-peek tests that could only pass on Linux
  (one hardcoded `/etc`, one searched `json.dumps(...)` output for a path, which JSON-escapes
  backslashes so a Windows path can never match). Both were caught late. OpenHands' pattern
  catches exactly this class, because it tests the **installed artefact on the target OS**.
  The mock LLM is what makes it affordable: deterministic, free, no model download — while
  still exercising the real installer, the real launcher, the real persisted session key and
  the real local port. S-CLAW already has every ingredient (a per-launch token, a
  `127.0.0.1` backend, Playwright, and a Windows runner in `build-windows.yml`); what it does
  not have is a mock-brain server and a test that drives the *installed* app.
- **Honest caveat:** I read 22 lines of one config file. I have **not** read the workflow, the
  mock LLM server implementation, or the specs. The *pattern* is established; the details are
  not.
- **Reuse:** **2 — reusable with modifications** (the pattern; S-CLAW's installer is Inno
  Setup, not an npm tarball, so the install step differs entirely).

### H2. Test-adjacency as a signal
Across all six, `*.test.ts` / `test_*.py` files sit **beside** the code they test
(`openclaw/packages/*/src/*.test.ts`, `model-catalog-core` has a test for nearly every
module). Agent Zero names tests after the *risk* rather than the module
(`test_browser_dom_security.py`, `test_browser_agent_regressions.py`). S-CLAW has already
benefited from exactly this habit — `tests/test_filenames_work_on_windows.py` exists because
of the mangled-filename incident, and a test asserting a named settings section exists as an
`<h3>` exists because a promised `extra_programs` field once did not. **Reuse: 3** —
keep naming tests after the failure, not the function.

---

## Summary: what to take, in priority order

**This table was revised after checking S-CLAW's own source.** Several items I had ranked
highest turned out to be already implemented. The revised order reflects what is actually
missing. See the CORRECTION sections in `MODEL_INTEGRATION.md` §2 and
`CODE_REUSE_AND_LICENSES.md` §3.

| # | Component | Repo | Class | Why, and S-CLAW's actual position |
|---|---|---|---|---|
| 1 | **Turn taint** (`AGENT_ARCHITECTURE.md` §2a) | openclaw | 2 | ~65 lines. The real defence against injection from a browsed page. S-CLAW has the permission model but no way to know a turn read the web. **Nothing equivalent exists.** |
| 2 | **Catalogue budget from the probed window** | hermes (discipline) | — | A *defect fix in S-CLAW's own code*: `CATALOGUE_BUDGET = 1800` is an absolute constant while `fit_context` uses the probed window. On a 2048 server they overcommit. |
| 3 | **Repetition guard** (`AGENT_ARCHITECTURE.md` §2b) | hermes | 2 | ~110 lines of Python, MIT. A looping small model is unbounded cost. Includes the lists/tables false-positive guard S-CLAW needs for its table tools. |
| 4 | **Tiny-model prompt techniques** (A5) | goose | 1 | 21 lines. S-CLAW ships a Tiny brain with no Tiny-specific prompt. Cheapest measurable experiment; harness already exists. |
| 5 | **CPU pre-flight gate** (A2) | goose | 2 | `models/hardware.py` reads RAM, cores and GPU but **no CPU instruction flags**. Turns "incompatible brain" from a crash into a named reason. |
| 6 | **Non-JSON tool-call shapes + allowlist + protected ranges** (B1) | openclaw | 3 | `jsonfix.py` already handles the JSON case. Missing: XML, bracketed, ReAct, the tool-name allowlist, protected ranges, and the schema-echo exclusion. |
| 7 | **Plugin manifest fields** (G1) + plugin `api/` channel (G2) | openclaw, agent-zero | 1, 3 | Directly serves the user's own plugin-ecosystem plan: `categories`, `activation`, `configSchema`, `configGroups`, `recommendedPrompts`, and an HTTP channel for plugin UI. |
| 8 | **Windows-install E2E with a mock LLM** (H1) | OpenHands | 2 | Removes the Linux/Windows evidence gap at its root. S-CLAW has the Windows runner already; it lacks a mock brain and a test of the *installed* app. |
| 9 | **Unhandled tool calls as an explicit case** | goose | 3 | ~75 lines. Common on a 2B model, currently invisible. |
| 10 | **Ollama `num_ctx` probe** (A8) | hermes | 2 | `ollama.py` has no `num_ctx`; Ollama's default is 2048. An Ollama brain silently gets the conservative default. |
| 11 | Token buffers + image sanitiser (C2) | agent-zero | 2 | Qwen3-VL inlines screenshots; `CHARS_PER_TOKEN = 3.5` has no safety margin. No `tiktoken` needed for the buffers or the sanitiser. |
| 12 | Structured compaction w/ `FileActivity` (C1) | goose | 3 | 8192 is small; compaction must not lose which files the task touched. |

**Dropped from the list after checking S-CLAW's code:**

- *Served-window probe* — **already done**, and well: `openai_compat.py:68` queries `/props`,
  `runner.py:228-245` logs asked-vs-actual and never lets the probe fail the task.
- *Localhost proxy exclusion* — **already done**, and better than Eigent's version: every
  httpx client passes `trust_env=False`.
- *JSON repair* — **already done**: `jsonfix.py`, ported from OpenClaw with attribution.
- *Create a third-party notices practice* — **already exists**:
  `backend/claw/agent/OPENCLAW_LICENSE.txt`. Needs promoting to the repo root and pinned SHAs,
  not inventing.

Nothing in this table requires running six frameworks together. Items 1, 2, 3, 5 and 9 are
small, independent changes to code S-CLAW already owns, and item 2 is a fix rather than a
feature.
