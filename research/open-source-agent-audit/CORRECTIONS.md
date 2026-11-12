# CORRECTIONS.md

**Read this before acting on any other document in this folder.**

The audit surveyed six external projects thoroughly and S-CLAW's own source only
superficially. When I then went to implement the recommendations, seven of them turned out to
be things S-CLAW already does — in several cases better than the project I took them from.

This file lists every withdrawal, with the S-CLAW code that supersedes it. The other documents
have been annotated where the wrong claim appears, but **this list is authoritative**.

The root cause is worth stating: I read ~1% of six other codebases and treated the result as a
gap list without first reading the codebase it was a gap list *for*. That ordering was wrong.

---

## Withdrawn — already implemented in S-CLAW

### 1. Turn taint / untrusted-content tracking
**Claimed:** the highest-value addition in the whole audit (~65 lines, from OpenClaw's
`turn-taint.ts`) — *"S-CLAW has the permission model but no way to know a turn read the web."*

**Wrong.** S-CLAW has this, with **two** levels where OpenClaw has one, plus an injection
detector OpenClaw does not have at all:

- `backend/claw/tools/base.py:100` — `injection_seen: bool` on the task's memory, commented
  *"that content tried to give Claw instructions"*; alongside `read_untrusted`.
- `backend/claw/agent/executor.py` `note_content()` — sets `read_untrusted` for any tool
  returning `untrusted_text`, runs an `INJECTION` pattern over it, sets `injection_seen` on a
  match, emits an `injection_warning` event to the UI, and appends a sticky warning telling the
  model the text is not from the user and must not be followed.
- `backend/claw/agent/executor.py` `decide()` — escalates ALLOW to ASK: `injection_seen`
  escalates **every** non-READ_ONLY action; `read_untrusted` escalates EXTERNAL. Each returns a
  user-facing reason (*"Something Claw read in this task tried to give it instructions, so it
  checks every change with you."*).
- `STICKY_PREFIX = "WARNING:"` with `fit_context` pulling sticky messages out and keeping them
  *whatever the budget* — so the warning outlives the observation that caused it. OpenClaw's
  taint has no equivalent.
- The outcome carries a warning into the final report.

S-CLAW's version is also **stricter**: OpenClaw's taint clears at the next user message;
S-CLAW's lives on `ctx.memory` for the whole task and never clears.

**One residual, and it looks deliberate:** `read_untrusted` escalates EXTERNAL but not
LOCAL_WRITE. Since `PermissionPolicy.__init__` already forces DESTRUCTIVE=ALLOW → ASK,
DESTRUCTIVE is covered regardless. Escalating every local write after any web read would ask on
nearly every task, because "read a page, save a file" is the common case. I am **not**
recommending a change.

### 2. Unhandled tool calls as an explicit case
**Claimed:** ~75 lines from Goose's `unhandled_tool_calls.rs`; *"common on a 2B model,
currently invisible."*

**Wrong.** `backend/claw/agent/executor.py` around the dispatch site already: looks the tool up,
and on a miss calls `closest_tool()` to fuzzy-match a near-miss name, emits
`tool_name_corrected` with both the asked-for and used names, and otherwise records
`outcome: "rejected"` on the step. That is Goose's named case **plus** auto-correction Goose
does not have.

### 3. The served-context-window probe
**Claimed:** *"the highest-value single file in this audit"* (Hermes' `agent_init_ollama.py`).

**Wrong for llama-server.** `backend/claw/models/openai_compat.py:68` queries `/props` for
`n_ctx` with a `default_generation_settings.n_ctx` fallback; `backend/claw/agent/runner.py:228`
compares it against what was asked, logs when they differ, and never lets a probe failure fail
the task; `planner.py:112` does the same. The docstring describes the clamping failure mode
independently of Hermes.

**What survived:** the budget half — see "Acted on" below. And the Ollama path genuinely has no
`num_ctx` handling (`models/ollama.py`), which matters because Ollama's default is 2048.

### 4. Excluding localhost from a system proxy
**Claimed:** *"one line, prevents a class of total failure"* (Eigent's `_ensure_local_no_proxy`).

**Wrong, and S-CLAW's version is better.** Every S-CLAW HTTP client passes `trust_env=False` —
`runtime/engine.py:225`, `models/openai_compat.py:139`, `models/ollama.py:87` and `:116`. That
disables proxy-environment inheritance outright rather than patching `NO_PROXY` around it.

### 5. JSON repair for model output
**Claimed** as part of porting OpenClaw's `tool-call-repair`.

**Wrong.** `backend/claw/agent/jsonfix.py` (113 lines) is already a port of OpenClaw's
`repairJson`, with a Windows-path rule and `loads()` extracting the first `{...}` from chatter
or fences. The residual gap is only the non-JSON shapes (XML, bracketed, ReAct), the
tool-name allowlist, protected ranges and the schema-echo exclusion — and see item 8 on why
even that is lower value than I said.

### 6. Creating a third-party notices practice
**Claimed:** *"create `THIRD_PARTY_NOTICES.md` at the S-CLAW repo root before the first borrowed
line lands"*, and separately that the existing `backend/claw/agent/OPENCLAW_LICENSE.txt` lacked
pinned revisions.

**Wrong on both counts.** S-CLAW has a thorough root `THIRD_PARTY_NOTICES.md` with a component
table, licences read from package metadata on a stated date, and an **OpenClaw entry pinned to
commit `b8b054c1`** naming five ported files (`browser/ddg_html.py`, `agent/jsonfix.py`,
`agent/skills.py`, `browser/snapshot.py`, `agent/persona.py`) and their upstream paths — plus a
Windows-MCP entry, a licence correction dated 2 Nov 2026, and an explicit note that the MIT
notice must ship with the app.

It also shows S-CLAW has ported more from OpenClaw than my audit found. The audit's claim that
only three files were ported was incomplete.

### 7. CPU feature gate before loading a brain
**Claimed:** ~30 lines from Goose's `check_cpu_supports_local_inference`, as *"the direct answer
to 'the brain was not compatible with Standard.'"*

**Withdrawn, for two separate reasons.**

First, S-CLAW already gates brains on hardware: `backend/claw/runtime/catalog.py` gives each
entry `min_ram_gb` and `min_vram_gb`, `fits(entry, hw)` checks both, and `recommended(hw)`
picks the largest that fits — with a deliberate rule that Pro (8B) is not recommended without
enough VRAM *even when memory fits*, because *"on a laptop processor each reply takes minutes,
which feels broken."* The user-facing problem I attributed to missing CPU detection was
almost certainly this RAM/VRAM fit working as designed.

Second, and decisive: **I cannot honestly implement the instruction-set check.**
`scripts/setup.ps1` downloads whichever `-bin-win-cpu-x64.zip` is newest in llama.cpp's
releases at build time. The minimum CPU requirement is a property of that binary, it varies
between releases, and I cannot inspect it from this Linux sandbox. Copying Goose's list
(`fma`, `avx2`, `f16c`, `bmi2`, `sse4.2`) would be a guess about someone else's build, and a
wrong guess refuses a brain that would have run fine. That is exactly the fabrication the
project's rules forbid.

**If you want this**, it needs establishing on Windows first: run the bundled
`llama-server.exe` on a machine without AVX2 and record what it actually says. I can write the
detection once the requirement is a fact rather than a guess.

---

## Reduced in value (not withdrawn)

### Repetition guard
Still absent, but lower priority than I ranked it. S-CLAW already has a **step**-repetition
guard (`MAX_REPEATS = 3` on an identical tool signature in `executor.py`), which covers the
agent-repeats-an-action loop. What is missing is **output-text** repetition — the degenerate
"echo one fragment for 60k characters" case. But the planner asks for schema-constrained JSON
(`response_format: {"type": "json_object", "schema": …}`), and a grammar-constrained decode
cannot produce that. Real exposure is limited to the free-text paths: chat replies, `see()`,
and final summaries. Worth doing; not urgent.

### Tool-call repair beyond JSON
Same reasoning. With schema-constrained JSON plus `jsonfix.py` plus `closest_tool()`
fuzzy-matching, the XML/bracketed/ReAct shapes are unlikely to appear on the planner path. The
parts still worth having are the **allowlist** and **protected ranges**, which are safety
properties rather than parsing ones.

---

## Acted on — the one real defect found

**The tool catalogue's budget did not derive from the served window.** Fixed in commit
`df2ee58`.

`CATALOGUE_BUDGET = 1800` and `FULL_CATALOGUE_BUDGET = 4800` (`agent/executor.py`) were
absolute numbers set against `DEFAULT_CONTEXT_TOKENS = 8192`. `fit_context(messages,
window_tokens)` correctly used the *probed* window for the conversation — but the catalogue did
not, and `fit_context` keeps the system message (which holds the catalogue) whatever the
budget. So on a brain that really serves 2048, the catalogue alone claimed 1800 of it, every
run came back `forced` and over the line, and nothing could shrink.

`tool_catalogue()` now takes `window_tokens` and `catalogue_budget()` returns a share of it,
calibrated so `DEFAULT_CONTEXT_TOKENS` yields exactly 1800 / 4800. `test_catalogue_window.py`
asserts the rendered catalogue is **byte-identical** at 8192 for both the per-capability and
whole-registry cases, so the change is a proven no-op for anyone whose brain serves the window
it asked for. Floors (`MIN_DETAILED`, `MIN_NAMED`, fitting tools) hold at every window from 512
to 16384.

Full backend suite after the change: **1551 passed, 15 skipped**.

This is the one finding that survived contact with S-CLAW's source, and it came from Hermes'
`_clamp_compressor_to_ollama_num_ctx`, which exists for precisely the same reason.

---

## What the audit is still good for

The external findings are sound — each was verified in source and is marked READ / DECL / NAME.
What changed is the **gap list**, because S-CLAW is further along than the audit assumed.

Genuinely still missing, in honest order:

1. **Plugin manifest fields** — `categories`, `activation`, `configSchema`, `configGroups`,
   `recommendedPrompts`. Serves the stated product direction and nothing in S-CLAW covers it.
   (`AGENT_ARCHITECTURE.md` §5, `SOURCE_CODE_MAP.md` §G1)
2. **A permission principal** (user / brain / plugin / system) — needed *before* third-party
   plugins ship, so a plugin cannot inherit the user's standing approval. The taint machinery
   it would compose with already exists. (`SOURCE_CODE_MAP.md` §F2)
3. **Plugin `api/` channel** — the missing piece for a plugin that owns a settings or status
   panel. (`AGENT_ARCHITECTURE.md` §5)
4. **Windows-install E2E with a mock brain** — unchanged in value, and the mock brain is also
   the fixture every other test wants. (`SOURCE_CODE_MAP.md` §H1)
5. **Ollama `num_ctx`** — a real gap for Ollama users specifically.
6. **Output-repetition guard** — reduced, as above.
7. **Token-estimate buffers and the base64-image sanitiser** — `CHARS_PER_TOKEN = 3.5` has no
   safety margin, and Qwen3-VL inlines screenshots. No new dependency needed.

A tiny-brain prompt variant also remains untried, and is still the cheapest measurable
experiment — but it needs a real model, so it is BLOCKED in this sandbox rather than done.
