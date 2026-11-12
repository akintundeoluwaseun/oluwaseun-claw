# AGENT_ARCHITECTURE.md

> **⚠ See `CORRECTIONS.md` before acting on §2a or §7.** Turn taint (§2a) and unhandled
> tool calls (§7 item 3) are **already implemented in S-CLAW**, the taint more thoroughly
> than in the OpenClaw source this document praises. The external analysis stands; the
> recommendations in §7 do not.

How the six projects structure the agent loop, tools, skills, permissions and sub-agents —
and which of those structures S-CLAW should borrow.

---

## 1. Two opposite answers to "where does the agent loop live"

### The monolith: Agent Zero

`agent-zero/agent.py` is **1,614 lines**. One module holds the loop, tool dispatch, prompt
assembly and state.

### The decomposition: Goose

`goose/crates/goose-agent/src/` is **2,761 lines across 14 files plus a `skills/` directory`**.
Measured:

| File | Lines | Concern |
|---|---|---|
| `inference.rs` | 675 | calling the model |
| `tool.rs` | 417 | tool execution |
| `machine.rs` | 355 | the state machine itself |
| `operation.rs` | 304 | units of work |
| `subagent.rs` | 296 | sub-agents |
| `tool_approval.rs` | 194 | approval policy |
| `stop_hook.rs` | 122 | when to stop |
| `tool_call_state.rs` | 104 | in-flight call state |
| `pre_tool_call_hook.rs` | 93 | before-call policy |
| `max_turns.rs` | 77 | turn limit |
| `unhandled_tool_calls.rs` | 75 | calls that went nowhere |
| `events.rs` | 18 | event types |
| `post_tool_call_hook.rs` | 17 | after-call policy |
| `lib.rs` | 14 | wiring |
| `skills/` | — | `mod.rs`, `discovery.rs`, `arguments.rs` |

Nearly the same total line count as Agent Zero's single file, split by **concern**. Note how
small the policy files are: `post_tool_call_hook.rs` is 17 lines, `events.rs` 18,
`max_turns.rs` 77. These are not big abstractions — they are named seams.

Two files worth calling out because their *existence* is the lesson:

- **`unhandled_tool_calls.rs` (75 lines).** A tool call that matched nothing is an explicit,
  handled case with its own module. On a 2B model this is a *common* case, not an edge case.
  S-CLAW has felt this directly: four v1.8 scenarios were assessed as having "no matching
  tool" when `rename_many` actually covered one — a mistake that is easier to make when
  unmatched calls are not a named, inspectable concept.
- **`tool_call_state.rs` (104 lines).** In-flight call state is a type, which is what lets a
  call be cancelled, timed out, or failed en masse (cf. Eigent's `_fail_all_pending`).

### The core design: effects as values

`machine.rs` is a generic `StateMachine<'a, S, E = ConversationEffect>` over a `Step` type.
A step **returns an effect**; the caller performs it. The loop never does I/O itself.

**Why this matters to S-CLAW specifically, with evidence from this project's own history.**
S-CLAW has already paid the cost of the alternative twice over. A planner test failed
intermittently; the first diagnosis was a `wait_done` timeout (20 s → 60 s), which was wrong —
the real cause was `task_cancelled` from lifespan shutdown, fixed by holding the client open
with `with make_client() as c:`. Separately, a traceback was misread and a prompt edit was
believed applied when it had not been. Both are symptoms of a loop whose behaviour can only
be observed by running it end-to-end with real I/O. When a step returns a value, you assert on
the value.

**Recommendation: 3 — architectural reference.** Do not rewrite S-CLAW's agent into a Rust-style
state machine. Do extract the named seams that S-CLAW does not yet have as separate,
testable units: pre-call policy, post-call policy, stop condition, turn limit, and
**unhandled tool calls**.

---

## 2. OpenClaw's `agent-core`: a catalogue of problems a real agent loop must solve

`openclaw/packages/agent-core/src/` — file listing verified, 39 entries. The non-test files are
effectively a checklist, and several name problems S-CLAW has hit:

| File | Lines | What the name tells us |
|---|---|---|
| `agent-loop.ts` | 1,060 | the loop |
| `agent-loop-steering.ts`, `stream-steering.ts` | — | the user can redirect a running turn |
| `agent-loop-tool-execution.ts` | — | tool execution split out |
| `agent-loop-tool-recovery.ts` | 136 | **recovering** from a failed tool call |
| `repetition-guard.ts` | 109 | detecting a looping model |
| `assistant-repetition-guard.ts` | 54 | detecting a looping *assistant* specifically |
| `turn-taint.ts` | 65 | **tracking untrusted content through a turn** |
| `tool-batch-admission.ts` | 46 | deciding which of a batch of calls may run |
| `tool-batch-completion.ts` | — | waiting for a batch |
| `tool-interruption.ts`, `turn-interruption.ts` | — | stopping a call vs stopping a turn |
| `pending-message-queue.ts` | — | messages that arrive mid-turn |
| `tool-call-outcome.ts` | — | outcome as a type |
| `reasoning.ts` | — | reasoning handling |
| `operator-messages.ts` | — | system/operator-originated messages |
| `errors.ts`, `runtime-deps.ts`, `internal-hooks.ts`, `harness/` | — | wiring |

Nearly every non-test file has a sibling `*.test.ts`. The two findings below were read in full.

### 2a. `turn-taint.ts` — the best security finding in this audit

**65 lines. Read in full.** It tracks whether the current turn has been contaminated by
network content.

```ts
export function toolResultTaintsTurn(message: ToolResultMessage): boolean {
  return readTurnTaintMetadata(message)?.resultContentSource === "network";
}

export function isActiveTurnTainted(messages: readonly AgentMessage[]): boolean {
  const boundary = messages.findLast((message) => {
    if (message.role === "user") return true;
    const metadata = readTurnTaintMetadata(message);
    return metadata?.turnTainted === true || metadata?.resultContentSource === "network";
  });
  return boundary !== undefined && boundary.role !== "user";
}
```

How it works:

- Metadata rides on the message under a namespaced key (`__openclaw`), read defensively via
  `Reflect.get` + `asOptionalRecord` — so a message without it is simply untainted, never an
  error.
- `withToolResultContentSource(message, source)` marks a tool result with where its content
  came from; `"network"` is the taint trigger.
- `withAssistantTurnTaint(message, tainted)` **propagates** the taint onto the assistant
  message that follows.
- `isActiveTurnTainted` scans **backwards** for the nearest boundary. A `user` message is a
  clean boundary; a tainted message is a dirty one. So **the taint persists until the human
  speaks again**, and a user turn resets it.
- The readers are strict: only the literal `"network"` and literal `true` are honoured
  (`record.resultContentSource === "network"`, `record.turnTainted === true`), so a page cannot
  forge a *clean* state by injecting an arbitrary value.

**Why this is the most important architectural finding for S-CLAW's safety.** S-CLAW's standing
rules say to treat webpages, files, repos and READMEs as untrusted input, and S-CLAW already
forces DESTRUCTIVE=ALLOW → ASK in `PermissionPolicy.__init__`. What S-CLAW does *not* have is a
way to know that **this turn** has read a web page. Taint tracking gives exactly that, and it
enables the rule that matters:

> After the agent reads network content, an EXTERNAL or DESTRUCTIVE action in the same turn
> requires fresh user confirmation — regardless of any standing approval.

That is the concrete defence against the scenario this project will certainly face: S-CLAW
browses a page, the page contains text crafted to look like an instruction, and the brain
(a 2B model, which is *more* susceptible, not less) acts on it. Without taint, a standing
"yes, you may write files" covers an action the user never intended. With taint, it does not.

65 lines, no dependencies beyond a record coercion helper, and it composes with the permission
model S-CLAW already has. **This is the highest-value safety change available.**

**Reuse: 2 — reusable with modifications** (trivially portable to Python; the design is the
value). Note S-CLAW should extend `resultContentSource` beyond `"network"` to cover any
untrusted source — a downloaded file, an installed plugin's output, clipboard content.

### 2b. `repetition-guard.ts` — detecting a looping model, *and* a licensing object lesson

**109 lines. Read, first 50 lines.** Its very first line:

```ts
// Adapted from Hermes Agent; see THIRD_PARTY_NOTICES.md for the pinned source and MIT license.
```

**This is a live, correct example of exactly the licensing discipline the user asked about**,
and it is covered in `CODE_REUSE_AND_LICENSES.md`.

The algorithm, as read:

- Constants: `FIRST_CHECK_CHARS = 16_000`, `TAIL_CHARS = 64_000`, `WINDOW_CHARS = 60`,
  `MIN_REPEATS = 5` — bounded work, and it only starts checking after 16 KB, so short replies
  cost nothing.
- **Line-level detection.** Counts non-empty trimmed lines; if any line occurs ≥ 5 times and
  `line.length * count` covers at least half the text, it is repetition-dominated.
- **A false-positive guard, and it is the thoughtful part.** Its comment: *"Similar prefixes in
  distinct records are not a loop, even when their windows repeat."* Implemented as: if
  `lineCount >= MIN_REPEATS && counts.size > lineCount / 2`, return `false` immediately — i.e.
  if most lines are *distinct*, this is a list or a table, not a loop. Without this, a
  legitimate 200-row CSV or directory listing would be killed as a loop. For S-CLAW this guard
  is essential, not optional: S-CLAW's tools routinely emit tabular output (`table_extract`,
  `summarize_column`, folder listings).
- **Window-level detection.** Slides a 60-char window; `needed = max(MIN_REPEATS,
  ceil(dominantChars / WINDOW_CHARS))`; skips overlapping re-counts via the stored `end`.
- **Exact-period sampling.** Its comment: *"Sample exact periods as well: a long repeated unit
  can have few equal 60-char windows."* 32 samples (`step = max(1, ceil(lastStart / 31))`) to
  catch a long repeated unit that the fixed 60-char window misses.

**Why S-CLAW needs this.** A small model that loops is one of the two worst user-visible
failures, and it is unbounded: it burns the whole context window and all the wall-clock before
anything stops it. It is a plausible contributor to "it's taking a year to reply" and to
"almost all tasks are error." A guard with the distinct-lines false-positive check is a
contained, testable addition.

The companion `assistant-repetition-guard.ts` (54 lines, not read) suggests a second,
cheaper check specific to assistant messages — likely "did the assistant just say the same
thing twice", as distinct from "is this one output internally repetitive."

**Reuse: 2 — reusable with modifications.** Both the Hermes original
(`hermes-agent/agent/repetition_guard.py`, Python, MIT) and the OpenClaw adaptation
(TypeScript, MIT) are available. **For S-CLAW, go to the Hermes original**: it is already
Python, and it is the upstream rather than a derivative.

### 2c. The rest of the checklist, as a gap list for S-CLAW

Not read, but named, and each is a real concern S-CLAW must answer eventually:

- **Steering** (`agent-loop-steering.ts`, `stream-steering.ts`): can the user redirect a turn
  that is already running? The user has asked for an emergency stop (which S-CLAW has and must
  preserve); steering is the softer version — "no, not that folder" mid-task.
- **Interruption, split two ways** (`tool-interruption.ts` vs `turn-interruption.ts`): stopping
  one tool call is not the same as stopping the turn. S-CLAW's emergency stop is the second;
  the first is what you want when a single Playwright call hangs.
- **Tool batch admission** (`tool-batch-admission.ts`, 46 lines): when a model emits several
  calls at once, which are allowed to run, and in what order? This is where a permission check
  on a *batch* belongs.
- **Tool recovery** (`agent-loop-tool-recovery.ts`, 136 lines): what happens after a tool
  fails — retry, reprompt, or surface. Distinct from tool-call *repair*; this is recovery after
  a correctly-parsed call failed.
- **Pending message queue** (`pending-message-queue.ts`): the user typed while the agent was
  working. S-CLAW will hit this the moment someone types twice.
- **Operator messages** (`operator-messages.ts`): system-originated messages kept distinct
  from user ones — which is the message-level counterpart of Goose's `PrincipalType`.

---

## 3. Permissions and approval

### Goose: permission as a typed triple

`goose/crates/goose-provider-types/src/permission.rs` — `pub enum Permission` `:5`,
`pub enum PrincipalType` `:14`, `pub struct PermissionConfirmation` `:20` (variant names not
read). Enforcement sits in `goose-agent/src/tool_approval.rs` (194 lines, not read) with
`pre_tool_call_hook.rs` (93) and `post_tool_call_hook.rs` (17).

Two structural points:

- **`PrincipalType` means "who is asking" is modelled.** S-CLAW needs this as soon as a
  *plugin* can request an action. The user's plan is third-party plugins downloaded from his
  website — at that point a plugin-originated DESTRUCTIVE action must not inherit the user's
  standing approval. Without a principal, there is nowhere to express that.
- **`PermissionConfirmation` is a struct, not a bool.** A confirmation carries evidence of
  *what* was approved, so an approval cannot be silently reused for a different action.

### Hermes: approval as an actor

`hermes-agent/gateway/approval_actor.py` — **NAME only, not read.** An "actor" implies
approvals are a serialised mailbox rather than an inline callback, which would prevent two
concurrent tool calls racing to prompt the user. **This is inference from a filename and must
be verified before anything is built on it.** Flagged in `IMPLEMENTATION_ROADMAP.md` as a
follow-up read.

### OpenHands: permissions surfaced as a UI hook

`OpenHands/src/hooks/use-automation-permissions.ts` — **NAME only, not read.** A React hook
implies permission state is first-class in the renderer rather than ad-hoc per dialog.
Relevant to S-CLAW's Electron UI. **Not verified.**

### What S-CLAW already has right

S-CLAW's risk model (READ_ONLY / LOCAL_WRITE / EXTERNAL / DESTRUCTIVE) with
`PermissionPolicy.__init__` forcing DESTRUCTIVE=ALLOW → ASK is sound, and **nothing in this
audit suggests replacing it.** Three additions are suggested by the above, in order of value:

1. **Taint** (§2a) — a turn that read network content needs fresh confirmation for EXTERNAL /
   DESTRUCTIVE.
2. **A principal** — user vs plugin vs operator, so plugin-originated actions can be held to a
   stricter standard than the user's own.
3. **Batch admission** — a model emitting several calls at once gets one coherent decision
   rather than a race of prompts.

---

## 4. Capability declaration vs execution authority

`openclaw/packages/model-catalog-core/src/model-inference-capabilities.ts` (13 lines, read in
full) carries two comments that settle a design question:

> *Provider-declared facts for one physical route; never execution or grounding authority.*
>
> *Explicit declarations never infer chat support from text encoding or structured output.*

Capabilities are **declared, never inferred**, and a capability is a **fact, not a
permission**.

**S-CLAW already does this correctly** — nine capabilities (BROWSER, DESKTOP, FILES,
DOCUMENTS, DATA, DESIGN, ORGANISER, CODE, REASONING) on one axis, four risk levels on another.
This file is independent confirmation from a much larger system that the two axes must stay
separate. **Do not collapse them.** The practical temptation to collapse them will appear when
plugins arrive — "this plugin has DESKTOP capability so it may control the desktop" — and that
is exactly the conflation these comments forbid.

---

## 5. Skills

### Goose: skills as discovery + arguments

`goose/crates/goose-agent/src/skills/` — `mod.rs`, `discovery.rs`, `arguments.rs`.
**NAME only.** The split is informative: a skill must be **discovered** (found on disk,
catalogued) and its **arguments** must be resolved (validated, defaulted, bound). S-CLAW's
`skills.load` and its `PLUGIN.md`/`SKILL.md` handling occupy the same space — and S-CLAW has
already been bitten on the discovery half: `skills.load` globbed only `SKILL.md`, so a
`PLUGIN.md` installed, listed, and never reached the brain. A dedicated discovery module is
where that bug would have been visible.

### Agent Zero: a plugin contributes three ways at once

`agent-zero/plugins/_memory/` contains `helpers/`, `tools/` **and** `api/`:

- `tools/` — model-callable (`memory_save.py`, `memory_forget.py`, `memory_delete.py`)
- `api/` — HTTP endpoints the UI calls (`memory_dashboard.py`)
- `helpers/` — internals (`memory.py`, `memory_quality.py`, `memory_consolidation.py`)

Built-ins are prefixed `_`. And `agent-zero/extensions/python/job_loop/_50_trim_cache.py` plus
`extensions/python/message_loop_result/_05_truncated_response.py` show an **ordered hook
pipeline** — a numeric prefix places an extension at a position in a named loop. Note
`_05_truncated_response.py` in particular: handling a truncated model response is an
*extension point*, not core code.

**This is the most directly useful finding for the user's plugin plan.** S-CLAW's plugin format
currently centres on skills and tools. The `api/` channel is the missing piece for a premium
UI: the Photoshop plugin the user describes would want its own settings or status panel, and
that requires a plugin to serve UI endpoints — not just tools. The numeric-prefix ordering is
a simple, legible answer to "two plugins both want to modify the context."

### OpenClaw: a plugin is a manifest + a category + recommended prompts

Covered in `PROJECT_ANALYSIS.md` §3 and `SOURCE_CODE_MAP.md` §G1.
`extensions/cua-computer/openclaw.plugin.json` (read in full) gives `id`, `categories`,
`activation: { onStartup }`, `enabledByDefault`, `name`, `description`, `configGroups`,
`configSchema` (JSON Schema with `additionalProperties: false`), `recommendedPrompts`.

`recommendedPrompts` is the one to emphasise for S-CLAW. A plugin ships example phrasings —
which is how a plugin teaches a **small** model what it is for. This is a mechanism S-CLAW has
already demonstrated works: the Blender plugin changed a real brain's plan from 5 steps
starting "Open Blender" to 3 steps starting "Write a Blender Python script." That effect is
currently achieved through S-CLAW's `PLUGIN.md` prose; making it a **declared, structured
field** makes it reliable and makes it available to third-party authors as a documented
contract.

And a separate *catalogue* contract — `packages/plugin-package-contract/src/catalog-order.ts`
(24 lines), `categories.ts`, `recommended-prompts.ts` (34 lines) — is the lesson for the
website side: the plugin store's ordering and categories belong in the **contract**, not in
website markup.

---

## 6. Sub-agents

- `goose/crates/goose-agent/src/subagent.rs` — 296 lines, **not read**
- `eigent/backend/app/agent/toolkit/remote_sub_agent_toolkit.py`,
  `depth_limited_agent_toolkit.py` — **NAME only**

The one genuinely informative item is Eigent's **`depth_limited_agent_toolkit.py`**: a
sub-agent facility with an explicit **depth limit**, i.e. recursion is bounded. An agent that
can spawn agents that can spawn agents is an unbounded-cost bug waiting to happen.

**Recommendation for S-CLAW: do not build sub-agents now.** S-CLAW's bottleneck is a 2B
model's single-step capability choice; a 2B model orchestrating other 2B models will compound
the error rate, not reduce it. Record the depth-limit requirement for if and when it becomes
relevant.

---

## 7. What this means for S-CLAW's architecture

**S-CLAW's existing architecture is sound and should not be replaced.** Electron 45 + Python
3.13 FastAPI on `127.0.0.1` with a per-launch token + `llama-server` + Playwright/Chromium +
pywinauto/UIA + SQLite is a coherent design, and OpenHands — the only one of the six built the
same way — independently validates it.

What this audit says to **add**, as named seams inside the architecture S-CLAW already has:

| Priority | Addition | From | Size | Why |
|---|---|---|---|---|
| 1 | **Turn taint** → fresh confirmation for EXTERNAL/DESTRUCTIVE after network content | openclaw `turn-taint.ts` | ~65 lines | The real defence against prompt injection via a browsed page |
| 2 | **Repetition guard** with the distinct-lines false-positive check | hermes `repetition_guard.py` | ~110 lines | A looping small model is unbounded cost |
| 3 | **Unhandled tool calls** as an explicit, inspectable case | goose `unhandled_tool_calls.rs` | ~75 lines | Common on a 2B model; currently invisible |
| 4 | **Principal** on a permission request (user / plugin / operator) | goose `permission.rs` | small | Required before third-party plugins ship |
| 5 | **Plugin `api/` channel** + `recommendedPrompts` + `categories` in the manifest | agent-zero, openclaw | format change | Serves the user's plugin-ecosystem plan directly |
| 6 | **Named policy seams**: pre-call, post-call, stop, max-turns | goose `goose-agent` | refactor | Makes the loop testable without a model |
| 7 | **Tool batch admission** | openclaw `tool-batch-admission.ts` | ~46 lines | One coherent decision instead of racing prompts |
| 8 | **Skill discovery** as its own module | goose `skills/discovery.rs` | refactor | Where the `PLUGIN.md`-not-loaded bug would have shown |

Items 1–3 are small, independent, and each prevents a class of failure the user has either
already reported or will certainly hit. **None of the eight requires adopting another
framework**, which is the outcome the user asked for.

### What to explicitly *not* do

- **Do not** rewrite the agent loop as a state machine. The win is the seams, not the pattern.
- **Do not** build sub-agents.
- **Do not** adopt `camel-ai` to get Eigent's toolkit breadth (see
  `CODE_REUSE_AND_LICENSES.md`).
- **Do not** collapse capability and risk into one axis when plugins arrive.

---

## 8. Gaps in this section

- `agent-loop.ts` (1,060 lines), `tool_approval.rs` (194), `subagent.rs` (296),
  `inference.rs` (675), `tool.rs` (417) — all **unread**. The largest bodies of agent-loop code
  in the two best-structured projects were not examined.
- `permission.rs` **variant names** were never read, so what Goose's permission *values* are
  is unknown — only that the three types exist.
- `approval_actor.py` and `use-automation-permissions.ts` are filename inferences only.
- Agent Zero's `agent.py` (1,614 lines) was **not read**; the monolith/decomposition contrast
  rests on file size and Goose's file list, not on Agent Zero's contents.
- `assistant-repetition-guard.ts`, `agent-loop-tool-recovery.ts`,
  `tool-batch-admission.ts` — sizes known, bodies unread.
- Hermes' `repetition_guard.py` — **I have its path and licence only via OpenClaw's
  `THIRD_PARTY_NOTICES.md`; I did not open the Hermes file itself.** Since it is the
  recommended source for item 2, reading it is the first task in
  `IMPLEMENTATION_ROADMAP.md`.
