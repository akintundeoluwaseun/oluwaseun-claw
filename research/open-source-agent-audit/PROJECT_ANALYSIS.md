# PROJECT_ANALYSIS.md

Per-project architecture findings from reading source code in local clones.

**Research method.** All six repositories were cloned with `git clone --depth 1` into
`/home/user/research-clones/` — deliberately outside the S-CLAW working tree, so no
S-CLAW file was touched during this audit. Findings below come from reading files,
listing directories and grepping declarations. Where I did not open a file, I say so.

**Clone date:** 2026-11-12. Shallow clones, so commit history was not available and no
claim here is about project history or velocity.

---

## Clone inventory (measured)

| Repo | Upstream | Size | Files | Licence | Dominant languages (file counts) |
|---|---|---|---|---|---|
| OpenHands | `All-Hands-AI/OpenHands` | 48 MB | 2,885 | MIT | 1,235 `.ts`, 1,143 `.tsx`, 17 `.py` |
| agent-zero | `agent0ai/agent-zero` | 89 MB | 3,307 | MIT | 956 `.py`, 688 `.js` |
| eigent | `eigent-ai/eigent` | 59 MB | 3,557 | Apache-2.0 | 830 `.py`, 777 `.ts`, 574 `.tsx` |
| goose | `block/goose` | 652 MB | 2,555 | Apache-2.0 | 622 `.rs`, 344 `.tsx`, 272 `.ts` |
| hermes-agent | `NousResearch/hermes-agent` | 409 MB | 25,124 | MIT | 11,412 `.py`, 4,000 `.ts` |
| openclaw | `openclaw/openclaw` | 1.1 GB | 64,447 | MIT | 51,328 `.ts`, 1,780 `.swift`, 1,619 `.kt` |

Structural counts (directory counts, `find -maxdepth 1 -type d`, includes the parent dir):

- `openclaw/extensions/` — 189 directories
- `openclaw/packages/` — 26 directories
- `goose/crates/` — 16 directories
- `agent-zero/plugins/` — 48 directories

---

## 1. Goose (`block/goose`) — Apache-2.0

**Shape.** A Rust Cargo workspace (`members = ["crates/*"]` per `goose/AGENTS.md`) plus an
Electron desktop UI at `ui/desktop/`. Verified entry points:

- `goose/crates/goose-cli/src/main.rs` — 56 lines (CLI entry)
- `goose/ui/desktop/src/main.ts` — 3,125 lines (Electron main process)
- `goose/crates/goose/src/providers/base.rs` — 69 lines (the `Provider` trait)

**Crate map** (`goose/crates/`): `goose`, `goose-agent`, `goose-cli`,
`goose-context-management`, `goose-download-manager`, `goose-local-inference`, `goose-mcp`,
`goose-provider-types`, `goose-providers`, `goose-roaming`, `goose-sdk`, `goose-sdk-types`,
`goose-test`.

The crate split *is* the architecture, and it is the single most important architectural
lesson in this audit. Goose does not have one "agent" module that knows about models,
context, tools and downloads. It has:

- **`goose-provider-types`** — the vocabulary (messages, token usage, permissions, cache
  semantics). No I/O. Everything else depends on this and not on each other.
- **`goose-providers`** — concrete cloud/local providers.
- **`goose-local-inference`** — 8,140 lines of local-model machinery, isolated so the rest
  of the system does not know whether a model is local.
- **`goose-context-management`** — conversation compaction as a standalone library.
- **`goose-agent`** — 2,761 lines total. The *loop*, nothing else.
- **`goose-download-manager`** — a single `lib.rs`; model downloads.

**`goose-agent/src/` file list** (verified): `events.rs`, `inference.rs`, `lib.rs`,
`machine.rs`, `max_turns.rs`, `operation.rs`, `post_tool_call_hook.rs`,
`pre_tool_call_hook.rs`, `skills/`, `stop_hook.rs`, `subagent.rs`, `tool.rs`,
`tool_approval.rs`.

`machine.rs` (355 lines) is a generic `StateMachine<'a, S, E = ConversationEffect>` over a
`Step` type that returns effects rather than performing them. The agent loop is a pure state
machine; side effects are values the caller executes. That makes the loop unit-testable
without a model.

Note the named hook files: `pre_tool_call_hook.rs`, `post_tool_call_hook.rs`,
`stop_hook.rs`, `tool_approval.rs`, `max_turns.rs`. Policy (approve this? stop here? too
many turns?) is separated from execution at the type level.

**Documentation accuracy — a verified defect.** `goose/AGENTS.md` line 131 lists
`Agent: crates/goose/src/agents/agent.rs` as an entry point. **That file does not exist** in
the cloned tree. This is direct evidence for the user's own instruction not to trust docs:
a project's own agent-facing documentation named a path that is not there.

## 2. Eigent (`eigent-ai/eigent`) — Apache-2.0

**Shape.** Python backend (`eigent/backend/`) + a separate `eigent/server/` (SQLModel/
SQLAlchemy persistence layer) + a TypeScript/React Electron front end (`eigent/src/`).

**Agent layer** (`eigent/backend/app/agent/`): `agent_model.py`, `factory/`,
`listen_chat_agent.py`, `prompt.py`, `toolkit/`, `tools.py`, `utils.py`.

**Toolkit catalogue** — `eigent/backend/app/agent/toolkit/` holds 42 toolkit modules.
Verified file names include `hybrid_browser_toolkit.py`, `hybrid_browser_python_toolkit.py`,
`pyautogui_toolkit.py`, `screenshot_toolkit.py`, `terminal_toolkit.py`, `excel_toolkit.py`,
`pptx_toolkit.py`, `file_write_toolkit.py`, `whatsapp_toolkit.py`, `slack_toolkit.py`,
`notion_toolkit.py`, `google_calendar_toolkit.py`, `memory_toolkit.py`, `skill_toolkit.py`,
`rag_toolkit.py`, `human_toolkit.py`, `thinking_toolkit.py`, `observable_todo_toolkit.py`,
`code_execution_toolkit.py`, `markitdown_toolkit.py`, `video_analysis_toolkit.py`,
`audio_analysis_toolkit.py`, `openai_image_toolkit.py`, `web_deploy_toolkit.py`,
`remote_sub_agent_toolkit.py`, `depth_limited_agent_toolkit.py`, `workspace_git_toolkit.py`.

**Critical caveat on Eigent's tools.** `pyautogui_toolkit.py` is **40 lines** and its only
class is `class PyAutoGUIToolkit(BasePyAutoGUIToolkit, AbstractToolkit)` — a thin wrapper.
The real desktop-control implementation lives in the `camel-ai` dependency, not in this
repository. The same pattern applies to several other toolkits. **Eigent's tool breadth is
largely inherited from CAMEL, not written in Eigent.** Any "reuse Eigent's desktop control"
plan is in fact a plan to depend on `camel-ai`. I did not inspect `camel-ai`'s source or
licence; that is an explicit gap (see `CODE_REUSE_AND_LICENSES.md`).

`hybrid_browser_toolkit.py` is by contrast a real 1,038-line implementation in-repo — see
`SOURCE_CODE_MAP.md`.

**Provider persistence.** `eigent/server/app/model/provider/provider.py` defines a SQLModel
`Provider` table: `user_id`, `provider_name`, `model_type`, `api_key`, `endpoint_url`,
`encrypted_config: dict | None`, `prefer: bool`, `is_valid: VaildStatus` (an `IntEnum` of
`not_valid = 1` / `is_valid = 2`), and an `execution_revision` column whose comment reads
"Assigned by database triggers. It is random, never a hash of a key/token."

Two things worth copying as *ideas*: a provider is **validated** and carries a persisted
validity state rather than being assumed to work, and one provider can be marked `prefer`.
Note also that `api_key` is a plain column — Eigent stores keys in its database.

## 3. OpenClaw (`openclaw/openclaw`) — MIT

**Shape.** The largest clone by a wide margin (1.1 GB, 64,447 files, 51,328 TypeScript
files). A pnpm monorepo: `packages/` (26 dirs), `extensions/` (189 dirs), `apps/`, `src/`,
`ui/`, plus `crates/` (Rust), `swift`/`kotlin` sources for mobile, a `Dockerfile`,
`fly.toml`, `render.yaml`, Sparkle appcasts (`appcast.xml`, `appcast-arm64.xml`,
`appcast-x86_64.xml`), `taxonomy.yaml`, `security/`, `qa/`, `custodian-skills/`, `skills/`.

**`packages/` (verified listing):** `acp-core`, `agent-core`, `ai`, `gateway-client`,
`gateway-protocol`, `llm-core`, `markdown-core`, `media-core`, `media-generation-core`,
`media-understanding-common`, `memory-host-sdk`, `mermaid-renderer`, `model-catalog-core`,
`net-policy`, `normalization-core`, `openclaw-id-protocol`, `plugin-package-contract`,
`plugin-sdk`, `retry`, `sdk`, `session-url-contract`, `terminal-core`, `tool-call-repair`,
`workboard-contract`, `worker-runtime`.

**The single biggest architectural finding of this audit.** `extensions/` contains 189
directories, and the overwhelming majority are *model providers*: `alibaba`,
`amazon-bedrock`, `amazon-bedrock-mantle`, `anthropic`, `anthropic-vertex`, `apple-fm`,
`arcee`, `azure-speech`, `baseten`, `beam`, `bifrost`, `byteplus`, `celeris`, `cerebras`,
`chutes`, `clawrouter`, `codex`, `cohere`, `cloudflare`, `cloudflare-ai-gateway`, `comfy` …
alongside capability extensions (`browser`, `cua-computer`, `canvas`, `active-memory`,
`code-mode-quickjs`, `brave`, `bonjour`, `advisor`, `autoreview`, `a2a`, `acpx`).

**Providers are plugins.** OpenClaw did not build a provider registry with a switch
statement; it made each provider an extension with a manifest. That is exactly the shape the
user wants for S-CLAW's plugin ecosystem, applied to models rather than to apps.

**Plugin manifest format** — `openclaw/extensions/cua-computer/openclaw.plugin.json`, read in
full:

```json
{
  "id": "cua-computer",
  "categories": ["computer-use"],
  "activation": { "onStartup": true },
  "enabledByDefault": true,
  "name": "CUA Computer",
  "description": "Experimental CUA Driver computer control for macOS, Windows, and Linux node hosts.",
  "configGroups": [
    { "id": "legacy-settings", "title": "Legacy settings", "order": 10,
      "properties": ["driverPath"] }
  ],
  "configSchema": {
    "type": "object", "additionalProperties": false,
    "properties": { "driverPath": { "type": "string" } }
  },
  "recommendedPrompts": [
    "Check whether computer use is ready on the machine I choose.",
    "Inspect an app on my chosen desktop and suggest a next step without controlling it."
  ]
}
```

Five design decisions in 28 lines, all worth adopting into S-CLAW's own `PLUGIN.md` format:
`categories` for catalogue grouping; `activation` so not every plugin loads at startup; a
JSON-Schema `configSchema` with `additionalProperties: false`; `configGroups` so the host can
*render* a settings UI from the manifest without plugin-specific UI code; and
`recommendedPrompts` — the plugin ships example phrasings, which is how a plugin teaches a
small model what it is for. The second recommended prompt is notably read-only ("without
controlling it"), i.e. the manifest encourages a safe first interaction.

Supporting contract packages confirm this is a real system, not a one-off:
`packages/plugin-package-contract/src/` holds `catalog-order.ts` (24 lines), `catalog-route.ts`,
`categories.ts`, `recommended-prompts.ts` (34 lines), `index.ts`, `index.test.ts` — 338 lines
total. A plugin *catalogue* has its own typed contract, separate from the plugin SDK.

**Desktop automation.** `extensions/cua-computer/` (with `api.ts`, `index.ts`, `src/`, `test/`),
plus host-side plumbing: `src/node-host/computer-command.ts` (49 lines),
`src/node-host/desktop-stream-command.ts`, `src/gateway/desktop/`,
`src/gateway/node-computer-use-descriptor.ts`, `src/agents/computer-use-node-capabilities.ts`,
`src/agents/session-placement-computer.ts`, `src/shared/node-desktop-stream.ts`,
`src/shared/worker-desktop-descriptor.ts`. Computer use is modelled as a *capability of a
node host* that a session is *placed onto* — not as a tool the agent calls directly. I did not
read these files' bodies; this is from file names and the 49-line command file only.

## 4. Hermes Agent (`NousResearch/hermes-agent`) — MIT

**Shape.** Python-dominant (11,412 `.py`), 25,124 files, with a `gateway/` service layer and
an `agent/` core. The largest Python surface of the six.

**The standout quality: this project writes down *why*.** Its comments are the most useful
engineering artefact in the whole audit, because they describe failure modes rather than
mechanisms. `agent/agent_init_ollama.py` was read in full for its first 60 lines and it
documents three real local-model bugs — see `MODEL_INTEGRATION.md`, which covers this file
in detail. Summarised:

1. "Ollama defaults num_ctx to 2048, so detect the max window and send num_ctx per request."
2. GGUF metadata can advertise 256 K+ context, and Ollama would allocate that much VRAM —
   so an auto-detected window must be capped by explicit config.
3. If the compactor's threshold is computed from the *probed model* window but the server
   *serves* a smaller `num_ctx`, "the compaction trigger could sit several times ABOVE the
   real served window and never fire."

That third one is a silent, catastrophic bug class: compaction that never runs. Related
modules identified by name (bodies not read): `agent/model_metadata.py` (provides
`is_local_endpoint`, `query_ollama_num_ctx`), `agent/agent_runtime_helpers.py`,
`gateway/agent_cache_pressure.py`, `gateway/approval_actor.py`.

`gateway/approval_actor.py` names an approval **actor** — approvals modelled as a
concurrent actor rather than an inline callback. Not read; flagged as a reference for
S-CLAW's `PermissionPolicy`.

## 5. Agent Zero (`agent0ai/agent-zero`) — MIT

**Shape.** Python + a JS front end, 3,307 files. Has a real plugin system:
`agent-zero/plugins/` holds 48 directories, including `_memory`, `_context_window`,
`_context_doctor`, `_text_editor`. The leading underscore appears to mark built-ins.

**Counter-example worth recording.** `agent-zero/agent.py` is **1,614 lines** — a
monolithic agent module. Set against Goose's `goose-agent` (2,761 lines spread over 13
focused files plus a `skills/` dir), Agent Zero is the "one big file" end of the spectrum.
For S-CLAW, which already has a layered `claw/` package, Agent Zero is a reference for
*plugin shape* and *memory*, not for agent-loop structure.

**Memory is its strongest subsystem.** `agent-zero/plugins/_memory/helpers/memory.py` is a
real vector-memory implementation over FAISS — `class MyFaiss(FAISS)` with
`get_all_docs()`/`get_by_ids()` added, then `class Memory` with
`search_similarity_threshold`, `search_similarity_threshold_with_scores`,
`delete_documents_by_query`, `insert_text`, `insert_documents`, `update_documents`,
`preload_knowledge`, and two normalizers, `_score_normalizer` and `_cosine_normalizer`.

Two details show production hardening: `_write_index_hash` / `_verify_index_hash` — the
FAISS index on disk is hash-verified, which is how you detect a corrupted or
externally-modified index instead of loading garbage. And sibling modules
`memory_quality.py` and `memory_consolidation.py`, plus tools `memory_save.py`,
`memory_forget.py`, `memory_delete.py`, and an API `memory_dashboard.py` — memory is a
managed, inspectable, forgettable store, not an append-only log.

**Token accounting** — `agent-zero/helpers/tokens.py`, read in full for its first 40 lines:
uses `tiktoken` (`cl100k_base`), with `APPROX_BUFFER = 1.1`, `TRIM_BUFFER = 0.8`, and
`sanitize_embedded_image_data_urls()` which replaces `data:image/...;base64,...` payloads
with `[embedded image data omitted from token estimate]` before counting. That last detail
matters for S-CLAW directly: S-CLAW's brain is Qwen3-**VL**, so base64 images *will* reach
the token estimator, and an unsanitised estimate on a screenshot is wrong by orders of
magnitude.

## 6. OpenHands (`All-Hands-AI/OpenHands`) — MIT

**The headline finding, and it contradicts prior assumption.** OpenHands in this clone is
**not a Python project**. `package.json` declares `"name": "@openhands/agent-canvas"`,
`"version": "1.40.0"`, `"license": "MIT"`. The tree holds 1,235 `.ts` + 1,143 `.tsx` against
**17 `.py` files**. There is an `electron/` directory (`main.mjs`, `preload.cjs`,
`preload-main.cjs`, `lib/`, `loading.html`, `build-resources/`, `package.json`).

It is an Electron + TypeScript application named "Agent Canvas", whose Python side is an
external `openhands-sdk` installed separately. So of the six, **OpenHands is architecturally
the closest analogue to S-CLAW**: Electron shell, local Python backend process, talking over
a local HTTP port with a per-run key.

**And it is the only one of the six that tests a Windows install.** Verified by reading
`OpenHands/playwright.windows-install.config.ts`, whose header comment says:

> Playwright config for the Windows npm-install E2E job
> (`.github/workflows/windows-install-e2e.yml`).
> Unlike `playwright.mock-llm.config.ts`, this config does not start Agent Canvas. The
> workflow installs the packed npm tarball globally and runs the `agent-canvas` command the
> way a Windows user does (README Option 1), then points these specs at that stack. Only the
> mock LLM server starts here.

Required environment, per the same comment: `MOCK_LLM_BACKEND_URL` (the running ingress),
`MOCK_LLM_SESSION_API_KEY` ("the key the launcher persisted on first run"),
`MOCK_LLM_PYTHON` ("Python with openhands-sdk installed"). Defaults in code:
`MOCK_LLM_PORT ?? "9999"`, `CANVAS_URL ?? "http://127.0.0.1:8000"`.

This is the most directly transferable *practice* in the entire audit, and it answers a
problem this project has hit repeatedly: S-CLAW's development happens on Linux while the
product runs on Windows, so Windows claims have had to be marked BLOCKED. OpenHands'
answer is to test **the installed artefact**, on Windows, in CI, against a **mock LLM** —
not the dev tree, and not a real model. Note what the design separates: the mock LLM makes
the test deterministic and free, while still exercising the real installer, the real
launcher, the real persisted session key and the real local port.

Other items identified by name but **not read**: `src/hooks/use-await-context-compaction.ts`,
`src/hooks/use-automation-permissions.ts`, `playwright.mock-llm.config.ts`.

---

## Honest gaps in this analysis

- **Shallow clones.** No history, so nothing here is a claim about maintenance or activity.
- **Eigent's real tool code is in `camel-ai`,** which I did not clone or inspect. Eigent's
  apparent breadth is therefore not Eigent's code.
- **OpenClaw is 64,447 files.** I read `plugin-package-contract` file names, one plugin
  manifest in full, `tool-call-repair` partially, and `model-inference-capabilities.ts` in
  full. The other ~99% is unexamined. No statement here should be read as a complete account
  of OpenClaw.
- **Hermes is 25,124 files;** I read one file's first 60 lines in full and identified four
  others by name. `approval_actor.py` and `agent_cache_pressure.py` bodies are unread.
- **Goose's Electron UI (`ui/desktop/`, 3,125-line `main.ts`) was not read beyond its size,**
  even though it is the closest match to S-CLAW's own shell. This is the largest single gap
  in the UI section and is carried into `IMPLEMENTATION_ROADMAP.md`.
- **No code was executed.** Nothing was built, run or benchmarked. Every performance
  statement in `PERFORMANCE_ANALYSIS.md` is a statement about *code structure*, never about
  measured speed.
