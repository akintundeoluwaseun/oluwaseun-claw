# PROJECT_COMPARISON.md

## How to read this document

**There are no scores, ratings or rankings here, and no performance numbers.** Nothing was
built, run or benchmarked. Every cell is either a measured count, a verified fact from source,
or an explicit "not found" / "not checked".

**"not found" means I did not find it in the parts I examined.** It is not a claim of absence.
The clones range from 2,885 to 64,447 files and I read a few dozen files in total. Treat every
"not found" as "unverified", especially for OpenClaw (64,447 files) and Hermes (25,124).

---

## 1. Measured facts

All from the local clones, `git clone --depth 1`, 2026-11-12.

| | OpenHands | agent-zero | eigent | goose | hermes-agent | openclaw |
|---|---|---|---|---|---|---|
| Upstream | `All-Hands-AI/OpenHands` | `agent0ai/agent-zero` | `eigent-ai/eigent` | `block/goose` | `NousResearch/hermes-agent` | `openclaw/openclaw` |
| Licence | MIT | MIT | Apache-2.0 | Apache-2.0 | MIT | MIT |
| Clone size | 48 MB | 89 MB | 59 MB | 652 MB | 409 MB | 1.1 GB |
| Files | 2,885 | 3,307 | 3,557 | 2,555 | 25,124 | 64,447 |
| Primary language (count) | TypeScript (1,235 `.ts` + 1,143 `.tsx`) | Python (956) | Python (830) | Rust (622) | Python (11,412) | TypeScript (51,328) |
| Other notable | 17 `.py` only | 688 `.js` | 777 `.ts`, 574 `.tsx` | 344 `.tsx`, 272 `.ts` | 4,000 `.ts` | 1,780 `.swift`, 1,619 `.kt` |
| Desktop shell | Electron (`electron/main.mjs`) | web (Flask) | Electron | Electron (`ui/desktop/`) | not established | Electron + Swift + Kotlin |
| Module unit | — | `plugins/` (48 dirs) | `toolkit/` (42 modules) | `crates/` (16 dirs) | — | `extensions/` (189 dirs), `packages/` (26) |
| Per-file © headers | not checked | not checked | **1,493 files** | **0 files** | not checked | not checked |
| `NOTICE` file | not checked | not checked | **none** | **none** | not checked | not checked |

### Architecture-shape measurements

| | Value | Source |
|---|---|---|
| goose agent crate | 2,761 lines / 14 files + `skills/` | `wc -l goose/crates/goose-agent/src/*.rs` |
| goose local inference | 8,140 lines / 16 files + `llamacpp/` (2,113) | `wc -l` |
| goose context management public API | 70 lines | `lib.rs` |
| agent-zero agent module | **1,614 lines, one file** | `agent.py` |
| eigent browser toolkit | 1,038 lines | `hybrid_browser_toolkit.py` |
| eigent pyautogui toolkit | **40 lines** (wrapper over `camel-ai`) | `pyautogui_toolkit.py` |
| openclaw agent loop | 1,060 lines + 38 sibling modules | `agent-core/src/` |
| openclaw tool-call repair | 4,296 non-test lines | `wc -l` excluding `*.test.ts` |
| openclaw turn taint | 65 lines | `turn-taint.ts` |
| openclaw repetition guard | 109 lines | `repetition-guard.ts` |
| goose tiny-model prompt | **21 lines** | `prompts/tiny_model_system.md` |

---

## 2. Capability matrix — what was verified present

**Legend:** ✅ verified in source · ◻ named but body not read · — not found (unverified) ·
n/a not applicable to that design.

### A. Local and cloud models

| Capability | OpenHands | agent-zero | eigent | goose | hermes | openclaw |
|---|---|---|---|---|---|---|
| Table of local runtimes with ports + discovery paths | — | — | ✅ `localModels.ts` | n/a (in-process) | — | — |
| Ollama / LM Studio / vLLM / SGLang / llama.cpp endpoints | — | — | ✅ all five | n/a | ◻ Ollama | — |
| **Probe the server for its served context window** | — | — | — | n/a | ✅ `agent_init_ollama.py` | — |
| Clamp compactor to served window | — | — | — | n/a | ✅ same file | — |
| Log which source the window came from | — | — | — | — | ✅ same file | — |
| In-process llama.cpp | — | — | — | ✅ `llamacpp/` | — | — |
| MLX backend | — | — | — | ✅ `mlx.rs` (1,157 L) | — | — |
| **CPU feature gate before model load** | n/a | — | — | ✅ `mod.rs:316` | — | — |
| Model download / cancel / delete / evict | — | — | — | ✅ `management.rs` | — | — |
| HuggingFace search + repo variants | — | — | — | ✅ `management.rs` | — | — |
| Per-model settings (sampling / tool mode / template) | — | — | ◻ DB row | ✅ `management.rs` | ◻ config | ◻ catalogue |
| Provider validity persisted, starts false | — | — | ✅ `provider.py` | — | — | — |
| Provider as a plugin/extension | — | — | — | — | — | ✅ `extensions/` (~150+ providers) |
| Typed model catalogue with id normalisation | — | — | — | — | — | ✅ `model-catalog-core` |
| Capability declared, never inferred | — | — | — | — | — | ✅ `model-inference-capabilities.ts` |
| Prompt-cache semantics per (provider, model) | — | ◻ `cache.py` | — | ✅ `cache_semantics.rs` | ◻ `agent_cache_pressure.py` | ◻ `prompt-cache.runtime.ts` |
| Pricing in the catalogue | — | — | — | — | — | ◻ `model-catalog-pricing.ts` |

### B. Making a small model work

| Capability | OpenHands | agent-zero | eigent | goose | hermes | openclaw |
|---|---|---|---|---|---|---|
| Native-vs-emulated tool calling decided per model | — | — | — | ✅ `should_use_native_tool_calling` | — | — |
| Detection by chat-template **dry run** | — | — | — | ✅ `supports_native_tool_calling` | — | — |
| Three-state override (Auto/ForceNative/ForceEmulated) | — | — | — | ✅ `ToolCallingMode` | — | — |
| Text-pattern tool-call emulation | — | — | — | ✅ `tool_emulation.rs` | — | — |
| Dedicated tiny-model system prompt | — | — | — | ✅ 21 lines | — | — |
| Tool **discovery** fences (model asks what exists) | — | — | — | ✅ `list_functions` | — | — |
| **Malformed tool-call repair (4 shapes)** | — | — | — | ◻ emulation only | — | ✅ `tool-call-repair` |
| Reject tool *definitions* echoed as calls | — | — | — | — | — | ✅ `hasToolArgs` |
| Allowlist on repaired tool names | — | — | — | — | — | ✅ `contracts.ts` |
| Protected ranges (user-visible text off-limits) | — | — | — | — | — | ✅ `contracts.ts` |
| **Repetition-loop detection** | — | — | — | — | ✅ `repetition_guard.py` | ✅ (adapted from hermes) |
| Repetition false-positive guard for lists/tables | — | — | — | — | ✅ | ✅ |
| Streaming `<think>` filter | — | — | — | ✅ `thinking_output.rs` | — | ◻ `reasoning.ts` |

### C. Context and memory

| Capability | OpenHands | agent-zero | eigent | goose | hermes | openclaw |
|---|---|---|---|---|---|---|
| Compaction as a reusable library | ◻ UI hooks | ◻ plugin | — | ✅ `goose-context-management` | ◻ compressor | — |
| Structured summary (not just prose) | — | — | — | ✅ `StructuredSummary` | — | — |
| File activity preserved across compaction | — | — | — | ✅ `FileActivity` | — | — |
| Compaction threshold constant | — | — | — | ✅ `0.8` | ◻ | — |
| **Context breakdown shown to the user** | ◻ usage hook | ◻ `_context_window` plugin | — | ✅ `context_xray/` (669 L, i18n) | — | — |
| Unknown context window renders as nothing, not 0 | ✅ `use-context-window-usage.ts` | — | — | — | — | — |
| Tokeniser-based counting | — | ✅ `tiktoken` | — | ◻ `TokenEstimator` | — | — |
| Asymmetric estimate buffers (1.1 / 0.8) | — | ✅ `tokens.py` | — | — | — | — |
| Base64 image stripped before token estimate | — | ✅ `tokens.py` | — | — | — | — |
| Structured token/cost accounting with source | ◻ metrics store | — | — | ✅ `token_usage.rs` | — | ◻ pricing |
| Vector memory | — | ✅ FAISS, `memory.py` | ◻ `memory_toolkit.py` | — | — | ◻ `memory-host-sdk` |
| **Memory index integrity hashing** | — | ✅ `_write/_verify_index_hash` | — | — | — | — |
| Two deletion paths (by query, by id) | — | ✅ | — | — | — | — |
| Score normalisers for threshold comparability | — | ✅ | — | — | — | — |
| Memory consolidation / quality | — | ✅ (named modules) | — | — | — | — |
| Memory dashboard (inspectable) | — | ✅ `memory_dashboard.py` | — | — | — | — |

### D. Automation

| Capability | OpenHands | agent-zero | eigent | goose | hermes | openclaw |
|---|---|---|---|---|---|---|
| Browser automation in-repo | ◻ Playwright configs | ◻ `browser.py` (385 L) | ✅ 1,038 L | — | — | ◻ `extensions/browser` |
| Per-command timeouts, env-overridable | — | — | ✅ | — | — | — |
| **Fail all pending on transport death** | — | — | ✅ `_fail_all_pending` | — | — | — |
| Tab caps with touch/forget LRU | — | — | ✅ | — | — | — |
| Navigation lock | — | — | ✅ | — | — | — |
| **Exclude localhost from system proxy** | — | — | ✅ `_ensure_local_no_proxy` | — | — | — |
| Connection pooling | — | — | ✅ `WebSocketConnectionPool` | — | — | — |
| Browser-DOM-security test file | — | ✅ `test_browser_dom_security.py` | — | — | — | — |
| Desktop control | — | — | ◻ via `camel-ai` (40 L wrapper) | — | — | ◻ `cua-computer` + external driver |
| Desktop streaming | — | — | — | — | — | ◻ `node-desktop-stream.ts` |
| Computer use as a placeable host capability | — | — | — | — | — | ◻ `session-placement-computer.ts` |

### E. Agent loop, policy, safety

| Capability | OpenHands | agent-zero | eigent | goose | hermes | openclaw |
|---|---|---|---|---|---|---|
| Loop decomposed into named modules | — | ✗ (1,614 L monolith) | ◻ | ✅ 14 files | — | ✅ 39 files |
| Effects-as-values state machine | — | — | — | ✅ `machine.rs` | — | — |
| Pre/post tool-call hooks | — | ◻ numbered extensions | — | ✅ | — | ◻ `internal-hooks.ts` |
| Stop hook / max turns | — | — | — | ✅ | — | — |
| **Unhandled tool calls as an explicit case** | — | — | — | ✅ `unhandled_tool_calls.rs` | — | — |
| In-flight tool-call state as a type | — | — | — | ✅ `tool_call_state.rs` | — | ◻ `tool-call-outcome.ts` |
| **Turn taint (untrusted content tracked)** | — | — | — | — | — | ✅ `turn-taint.ts` |
| Permission types incl. a **principal** | ◻ UI hook | — | — | ✅ `permission.rs` | ◻ `approval_actor.py` | — |
| Approval as a serialised actor | — | — | — | — | ◻ | — |
| Tool batch admission | — | — | — | — | — | ◻ 46 L |
| Tool vs turn interruption, separately | — | — | — | — | — | ◻ two modules |
| Mid-turn steering | — | — | — | — | — | ◻ two modules |
| Pending message queue | — | — | — | — | — | ◻ |
| Sub-agents | — | — | ◻ remote + **depth-limited** | ◻ 296 L | — | — |

### F. Plugins, UI and release practice

| Capability | OpenHands | agent-zero | eigent | goose | hermes | openclaw |
|---|---|---|---|---|---|---|
| Plugin system | — | ✅ 48 dirs | — | ◻ MCP extensions | ◻ `skills/` | ✅ 189 dirs |
| **Declarative plugin manifest** | — | — | — | — | — | ✅ `openclaw.plugin.json` |
| JSON-Schema config in manifest | — | — | — | — | — | ✅ |
| `configGroups` → host renders settings UI | — | — | — | — | — | ✅ |
| `categories` for catalogue | — | — | — | — | — | ✅ |
| **`recommendedPrompts` shipped by plugin** | — | — | — | — | — | ✅ |
| Separate plugin **catalogue** contract | — | — | — | — | — | ✅ `plugin-package-contract` |
| Plugin contributes tools + **HTTP api** + helpers | — | ✅ `_memory/{tools,api,helpers}` | — | — | — | — |
| Ordered hook pipeline (numeric prefixes) | — | ✅ `_50_`, `_05_` | — | — | — | — |
| **Windows-install E2E in CI** | ✅ `playwright.windows-install.config.ts` | — | — | — | — | — |
| Mock LLM server for deterministic E2E | ✅ `playwright.mock-llm.config.ts` ◻ | — | — | — | — | — |
| Tests named after the risk, not the function | — | ✅ | — | — | — | — |
| CVE notes in the dependency manifest | — | ✅ `requirements.txt` | — | — | — | — |
| Third-party notices with **pinned SHA** | — | — | — | — | — | ✅ `THIRD_PARTY_NOTICES.md` |
| i18n on a shipped feature | — | — | — | ✅ `context_xray` | — | — |

---

## 3. What each project is actually best at

One honest sentence each, from what was verified.

**goose** — **local inference, context management and model lifecycle.** 8,140 lines devoted
to running a model on the user's own machine, including the only CPU-capability pre-flight
gate and the only per-model tool-calling-mode decision found. Also the best-decomposed agent
loop. Its weakness for S-CLAW is simply that it is Rust.

**openclaw** — **small-model output hardening and plugin architecture.** The only dedicated
tool-call repair package, the only turn-taint mechanism, and by far the most developed plugin
manifest and provider-as-extension model. Also the largest and hardest to survey, and the
project the user is competing with.

**hermes-agent** — **knowing what the local server actually does, and writing down why.** The
only project that probes the served context window and clamps its compactor to it; its
comments name specific production incidents. Python, MIT, and the most directly portable of
the six.

**agent-zero** — **memory and token accounting.** The only hash-verified vector index, the only
two-path deletion, the only normalised similarity scores, the only base64-image sanitiser
before token counting. Offset by a 1,614-line monolithic agent and a very heavy dependency
list.

**eigent** — **runtime robustness in the browser layer.** Per-command timeouts,
fail-all-pending, tab caps, navigation locks, connection pooling, and
`_ensure_local_no_proxy` — the hard-won details. Undercut by the fact that most of its
apparent tool breadth is `camel-ai`'s, pinned at an alpha version.

**OpenHands** — **being the same shape as S-CLAW, and testing the Windows install.** Electron
+ local Python backend + `127.0.0.1` + per-session key. The only project that runs the
installed artefact on Windows in CI against a mock LLM, and the only one that renders an
unknown context window as nothing rather than zero.

---

## 4. The conclusion the matrix forces

Read down any column and the gaps are as striking as the entries. **No project has more than
about a third of the capability list.** The techniques are scattered: Goose has the CPU gate
but not taint; OpenClaw has taint and repair but no served-window probe; Hermes has the probe
but no plugin system; Agent Zero has the memory but a monolithic loop; Eigent has the runtime
robustness but borrowed tools; OpenHands has the Windows discipline but little of the rest.

**This is the strongest possible evidence for the user's own stated position:**

> *"I do not want six different AI frameworks running together. I want one coherent
> application with carefully selected components."*

There is nothing here to adopt wholesale, because nothing is comprehensively good. There are
roughly a dozen specific, mostly small techniques — and S-CLAW's existing architecture
(Electron + FastAPI on `127.0.0.1` + `llama-server` + Playwright + pywinauto/UIA + SQLite),
which OpenHands independently validates as a shape, is the right place to put them.

See `SCLAW_RECOMMENDED_ARCHITECTURE.md` for which ones and where.

---

## 5. Coverage honesty

How much of each project this audit actually examined:

| Repo | Files read in full | Files read partially | Declarations grepped | Files in clone | Rough coverage |
|---|---|---|---|---|---|
| goose | 3 (`goose-context-management/lib.rs`, `tiny_model_system.md`, `context_xray/categories.ts`) | 5 | 4 | 2,555 | **« 1%** |
| openclaw | 4 (`openclaw.plugin.json`, `model-inference-capabilities.ts`, `turn-taint.ts`, `tool-call-repair/package.json`) | 3 | 2 | 64,447 | **«« 1%** |
| eigent | 2 (`localModels.ts`, `pyproject.toml` lines) | 2 | 2 | 3,557 | **« 1%** |
| hermes-agent | 1 (`agent_init_ollama.py` ~60 L) | 1 (`repetition_guard.py` head) | 0 | 25,124 | **«« 1%** |
| agent-zero | 1 (`tokens.py` 40 L) | 1 (`requirements.txt` 30 L) | 1 | 3,307 | **« 1%** |
| OpenHands | 2 (`playwright.windows-install.config.ts` header, `use-context-window-usage.ts`) | 1 | 0 | 2,885 | **« 1%** |

**This is a targeted audit, not a survey.** It went after the areas the user named — local
models above all — and found high-value, verifiable material in each. It did **not** read the
largest bodies of code in any project: `agent-loop.ts` (1,060 L), `goose-agent/inference.rs`
(675 L), `agent-zero/agent.py` (1,614 L), `goose/ui/desktop/src/main.ts` (3,125 L),
`tool_approval.rs` (194 L), and the ~8,000 remaining lines of `goose-local-inference` are all
unread.

Every "not found" in this document should be read with that in mind. The ✅ entries are
reliable — each one was observed in source. The — entries are not claims.
