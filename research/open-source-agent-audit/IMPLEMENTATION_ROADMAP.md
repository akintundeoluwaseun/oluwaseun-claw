# IMPLEMENTATION_ROADMAP.md

> **⚠ Superseded in part by `CORRECTIONS.md`.** Milestone 0 is done. Milestone 2 is
> **complete** (commit `df2ee58`, 1551 tests passing). Milestones 1, 5 and 7 are **cancelled**
> — S-CLAW already implements them. Milestones 3 and 6 are reduced in value because the planner
> uses schema-constrained JSON. Milestones 8–12 stand.

**Nothing in this roadmap has been implemented.** No S-CLAW production file was modified
during this audit. This is a proposal awaiting the user's approval, as his brief requires:
*"At the end, present your findings and wait for my approval before implementing anything."*

Each milestone is small, independently shippable, and has a stated test. Sizes are estimates.

---

## Milestone 0 — Verification reads (before any code)

The audit has gaps, and three of them sit directly under recommendations in
`SCLAW_RECOMMENDED_ARCHITECTURE.md`. Closing them is cheap and must come first, because
building on a filename inference would violate the user's own rule: *"Do not make assumptions
when evidence is available in the source."*

| # | Read | Why it gates something |
|---|---|---|
| 0.1 | `hermes-agent/agent/repetition_guard.py` **in full** (8,849 bytes) | Only its first 30 lines were read. It is the recommended source for Tier-1 item 3. |
| 0.2 | `openclaw/THIRD_PARTY_NOTICES.md` **all 111 lines** | Only the Hermes section (lines 80–99) was read. If `turn-taint.ts` or `tool-call-repair` were themselves adapted from a third party, **that** upstream is the better source and the correct attribution target. Gates items 1 and 6. |
| 0.3 | `openclaw/packages/agent-core/src/turn-taint.ts` **plus its tests** | Read in full, but its test file was not. A security port needs the original's edge cases as test cases. Gates item 1. |
| 0.4 | `openclaw/packages/tool-call-repair/src/{payload,grammar,diagnostics}.ts` | Only `contracts.ts` and `attempt.ts` (first 45 lines) were read. Gates item 6. |
| 0.5 | S-CLAW's own `agent/executor.py` around `_next_action`, `fit_context`, and the catalogue renderer | The budget defect (item 2) was found by grep. **Read the code before changing a constant that four tests depend on.** |
| 0.6 | S-CLAW's `models/base.py` + `registry.py` + `runtime/brain.py` | To confirm items 7, 8, 15, 17, 18, 19 of the `MODEL_INTEGRATION.md` §7 checklist, which are still marked "not checked" against S-CLAW. |
| 0.7 | Confirm with a real Qwen3 brain whether `<think>` tags ever reach S-CLAW | The planner uses schema-constrained JSON, which likely suppresses them. **Do not build a `<think>` filter on a grep result.** |

Also worth one command: re-clone **without** `--depth 1`, or fetch the specific blobs, to
capture **pinned commit SHAs** for every file this audit cites. The current clones are shallow,
so provenance SHAs are unavailable — and `CODE_REUSE_AND_LICENSES.md` §8 needs them.

**Output:** a short note appended to this file recording what each read confirmed or
contradicted. If 0.2 shows a different upstream, the attribution plan changes before any code
is written.

---

## Milestone 1 — Turn taint (safety)

**What.** Tier-1 item 1. Mark tool results with their content source; taint the turn when the
source is untrusted; require fresh confirmation for EXTERNAL/DESTRUCTIVE actions in a tainted
turn.

**Touches.** `backend/claw/agent/executor.py`, `backend/claw/agent/conversation.py`,
`backend/claw/permissions/policy.py`. New: a small taint module.

**Size.** ~65 lines of taint logic plus the policy hook and tests.

**Tests.**
- A browser tool result marks the turn tainted; a file-read from the user's own path does not.
- Taint propagates to the following assistant message and **clears at the next user message**.
- A DESTRUCTIVE action in a tainted turn is re-asked **even with a standing ALLOW**.
- Injected content cannot forge a clean state: a tool result whose metadata says
  `resultContentSource: "trusted"` or `turnTainted: "false"` (a string) is still treated as
  tainted/unclear, because only literal values count.
- `PermissionPolicy.__init__` still forces DESTRUCTIVE=ALLOW → ASK (regression).

**Don't break.** The emergency stop shortcut. No existing approval path may become *more*
permissive.

**Status vocabulary.** This milestone is testable entirely on Linux. It will be **PASS** or
**FAIL**, not BLOCKED.

---

## Milestone 2 — Catalogue budget derives from the served window (defect fix)

**What.** Tier-1 item 2. `CATALOGUE_BUDGET` / `FULL_CATALOGUE_BUDGET` become fractions of
`window_tokens`, calibrated so 8192 reproduces today's 1800 / 4800.

**Touches.** `backend/claw/agent/executor.py` (`:1048`, `:1053`, `:1116`), and plumbing
`window_tokens` into the catalogue renderer if it is not already reachable there.

**Size.** Small, but it moves a constant four tests depend on — do Milestone 0.5 first.

**Tests.**
- At `window_tokens = 8192` the rendered catalogue is **byte-identical** to today's. This is
  the important one: the change must be a no-op at the current window.
- At `window_tokens = 2048`, catalogue + `fit_context` reserve together fit inside the window.
- `MIN_DETAILED = 10` and `MIN_NAMED = 25` floors hold at every window size — including the
  off-by-step case that previously produced 23 instead of 25.
- `test_tool_catalogue.py` still passes.

**Risk.** This is the one item that changes behaviour of a shipped path. Hence the
byte-identical test at 8192.

---

## Milestone 3 — Repetition guard

**What.** Tier-1 item 3, ported from Hermes (after Milestone 0.1).

**Touches.** New module under `backend/claw/agent/`; called from the executor's model-reply
path. Attribution entry required.

**Size.** ~110 lines plus tests.

**Tests.**
- A degenerate loop (one 60-char fragment repeated past the dominance ratio) trips it.
- **A 200-row table does not trip it** — the distinct-lines guard. Use real output from
  `table_extract` and `summarize_column` as fixtures, not synthetic text.
- A folder listing of many similarly-prefixed filenames does not trip it.
- Output under the minimum fragment length is never checked.
- When it trips, the conversation receives the **marker**, never the looped bytes.

**Attribution.** Hermes section in `THIRD_PARTY_NOTICES.md` with a pinned SHA, plus a
provenance docstring in the new file — matching the pattern `jsonfix.py` already uses.

---

## Milestone 4 — Tiny-brain prompt experiment

**What.** Tier-1 item 4. A Tiny-specific prompt variant using Goose's techniques, adapted.

**Touches.** `backend/claw/agent/planner.py` / `persona.py`, selected by brain edition from
`runtime/catalog.py`.

**Size.** ~25 lines of prose, plus selection logic.

**Method — this one is an experiment, not a change.** Run `scripts/brain_bench.py` on a real
brain before and after. Report held-out capability accuracy and mean step count. **Keep only
what measures better.** Baseline to beat: 69% accuracy, 3.1 steps.

**Honest constraint.** This needs a real model, and whether the sandbox can run one at useful
speed is unverified. If it cannot, this milestone is **BLOCKED** with exact steps for the user
to run it on Windows — not converted to PASS.

---

## Milestone 5 — CPU pre-flight gate

**What.** Tier-2 item 5. Detect `fma`, `avx2`, `f16c`, `bmi2`, `sse4.2`; fail before load with
a message naming every missing one; hide incompatible brains from the catalogue.

**Touches.** `backend/claw/models/hardware.py`, `backend/claw/runtime/catalog.py`,
`backend/claw/runtime/engine.py`.

**Size.** ~30 lines plus tests.

**Tests.**
- On a CPU with all features: no change in behaviour.
- With the detector stubbed to report a missing feature: load is refused and the message names
  it; a brain requiring it is not offered.
- `hardware.detect()` keeps returning its existing fields (regression on `Hardware`).

**Platform honesty.** The Linux path (`/proc/cpuinfo`) is testable here. **The Windows path is
not** — mark it BLOCKED with exact verification steps, consistent with the standing rule.
This is also precisely the kind of thing Milestone 8 would catch automatically.

---

## Milestone 6 — Tool-call repair beyond JSON

**What.** Tier-2 item 6. XML / bracketed / ReAct shapes, prefilter, bounded work, field-name
tolerance, schema-echo exclusion, tool-name allowlist, protected ranges.

**Touches.** `backend/claw/agent/jsonfix.py` or a sibling module; the executor's action parser.

**Size.** ~150 lines plus substantial tests.

**Tests.** The allowlist and protected ranges are the security-relevant parts, so test them
hardest:
- Each of the four shapes is recovered into a real S-CLAW tool call.
- A repaired call naming a tool **not** in the registry is rejected, not executed.
- A fenced code block the user asked to see is **not** consumed as a tool call.
- A model echoing its own tool catalogue back (a JSON Schema shape) is **not** executed.
- Ordinary prose containing the word "parameters" does not enter the repair path (prefilter).
- A 100 KB rambling reply does not blow the scan caps.
- Everything `jsonfix.py` handles today still works (regression).

**Attribution.** Extend the existing OpenClaw entry; add the pinned SHA.

---

## Milestone 7 — Unhandled tool calls as an explicit outcome

**What.** Tier-2 item 7. A named, logged outcome for a call that matched no tool, plus the
aggregate view that answers "which tools are actually missing?"

**Touches.** `backend/claw/agent/executor.py`, `report.py`, `storage/`.

**Size.** ~75 lines.

**Tests.** A call to a non-existent tool produces the unhandled outcome, is logged with the
attempted name, does not look like a generic failure, and is counted.

---

## Milestone 8 — Windows-install E2E with a mock brain

**What.** Tier-4 item 12. A CI job that installs the Inno Setup artefact on Windows and drives
the installed app with Playwright against a mock brain server.

**Touches.** `.github/workflows/` (new job), `tests/` (mock brain + specs).

**Size.** The largest item here, and the one with the highest leverage on everything else.

**Why it is worth it.** It converts the project's recurring BLOCKED statuses into real PASS/FAIL
evidence, and it would have caught both prior Windows incidents — the un-checkoutable filename
and the two Linux-only folder-peek tests — automatically.

**Build it in this order, as separate commits:**
1. A mock brain: an HTTP server speaking enough of the OpenAI-compatible surface S-CLAW uses
   (`/v1/chat/completions` with `response_format` schema, `/props` returning a chosen `n_ctx`,
   `/v1/models`). Deterministic, scripted replies. **This is also the fixture Milestones 1–7
   should use** — so build it first and reuse it.
2. One Windows CI job: install the artefact, launch it, assert the backend answers on
   `127.0.0.1` with its token and the UI loads.
3. Then one scenario at a time.

**Note:** the `/props` mock lets Milestone 2 be tested at an *arbitrary* served window — which
is otherwise hard to arrange — so Milestones 2 and 8 reinforce each other.

**Honest caveat.** Only 22 lines of OpenHands' config were read. The workflow, the mock server
and the specs were not. The pattern is established; the details are S-CLAW's to work out.

---

## Milestone 9 — Plugin format extension

**What.** Tier-3 items 9 + 11 together. `categories`, `activation`, `configSchema`,
`configGroups`, `recommendedPrompts` in S-CLAW's own `PLUGIN.md` format — **and** the
permission principal, because a plugin that can serve endpoints must not inherit the user's
authority.

**Touches.** `backend/claw/plugins/pack.py`, `backend/claw/skills/`, `docs/PLUGINS.md`,
`backend/claw/permissions/policy.py`, and the settings UI in `desktop/src/renderer/`.

**Size.** Moderate. The settings-UI renderer driven by `configGroups` is the bulk of it.

**Tests.**
- An existing plugin with **no** new fields still installs, lists and loads — backward
  compatibility is non-negotiable; `drive-blender` must keep working.
- A manifest with an invalid `configSchema` is rejected at install, with a clear reason.
- `additionalProperties: false` is enforced.
- `recommendedPrompts` reach the brain. **Measure the effect** with `brain_bench.py`, as the
  Blender plugin's 5-steps → 3-steps result was measured.
- `activation.onStartup: false` means the plugin is not loaded at startup and does not consume
  catalogue budget.
- A plugin-originated DESTRUCTIVE action is re-asked even with a standing user ALLOW.
- Regression on both known plugin bugs: `read_folder`/`install` path mismatch (so `remove()`
  deleted nothing and reported success), and `skills.load` globbing only `SKILL.md` (so a
  `PLUGIN.md` installed, listed, and never reached the brain).

**Do not ship** items 9 or 10 without 11. That ordering is the point.

---

## Milestone 10 — Plugin `api/` channel

**What.** Tier-3 item 10. A plugin may contribute HTTP endpoints, behind the per-launch token,
with ordered hooks.

**Depends on** Milestone 9 (principal must exist first).

**Touches.** `backend/claw/plugins/`, `backend/claw/api/`.

**Tests.** A plugin endpoint is reachable only with the per-launch token; cannot widen the
permission surface; cannot reach paths outside its own namespace; two plugins with ordered
hooks run in the declared order.

---

## Milestone 11 — Ollama `num_ctx`

**What.** Tier-2 item 8. Probe `/api/show`, send `num_ctx` per request, cap by explicit config,
label the source in the log.

**Touches.** `backend/claw/models/ollama.py`.

**Size.** ~25 lines.

**Tests.** With a stubbed `/api/show`, the probed window is used and logged with its source; a
probe failure falls back to the conservative default **without failing the task**; an explicit
config value overrides the probe; a probed value above the configured cap is capped.

---

## Milestone 12 — Context breakdown panel

**What.** The UI half of `PERFORMANCE_ANALYSIS.md` §2a: a capacity meter and per-category
breakdown — system prompt / tool definitions / conversation / compaction summary.

**Depends on** Milestone 2 (the numbers must be real first).

**Touches.** `backend/claw/agent/executor.py` (expose the breakdown),
`desktop/src/renderer/`.

**Tests.** Categories sum to the reported total. **When the served window is unknown the panel
shows nothing — never 0%** (OpenHands' discipline, and this project's own rule against
fabricated status).

**Deliverable for the user.** He has said repeatedly: *"Most times when you do something, I'm
actually using my phone and I'm not running it. So I would need a preview, a picture and
screenshot of what you've done."* So this milestone ends with a real screenshot — and
**with the backend running**, since a prior UI review was nearly done against a screenshot
where every button was greyed out because no backend was up.

---

## Suggested order, and why

```
0  Verification reads            ── gates 1, 2, 3, 6
│
├─ 1  Turn taint                 ── safety; nothing depends on it; ship alone
├─ 2  Catalogue budget fix       ── a real defect; byte-identical at 8192
├─ 3  Repetition guard           ── unbounded cost; after 0.1
├─ 5  CPU pre-flight gate        ── answers "incompatible brain" directly
├─ 7  Unhandled tool calls       ── small; produces data on missing tools
│
├─ 8  Mock brain + Windows E2E   ── build the mock FIRST; it is the fixture for
│                                   everything else, and it ends the BLOCKED problem
├─ 2b Re-test 2 at 2048          ── now possible via the mock's /props
├─ 6  Tool-call repair           ── after 0.2 and 0.4
├─ 4  Tiny-brain prompt          ── experiment; needs a real model
├─ 11 Ollama num_ctx             ── only matters to Ollama users
│
├─ 9  Plugin format + principal  ── the product direction; ship together
├─ 10 Plugin api/ channel        ── after 9
└─ 12 Context panel              ── after 2; the visible premium feature
```

**Rationale.** Safety first (1). Then the one genuine defect (2). Then the unbounded-cost
failures (3, 5, 7) — small, independent, each addressing a complaint already on record. Then
the mock brain (8), because it is the fixture every later milestone wants *and* it removes the
Linux/Windows evidence gap permanently. Then the model-quality work (6, 4, 11). Then the
product direction (9, 10, 12), which is the largest and benefits from everything above being
solid.

Milestones 1, 2, 3, 5, 7 and 11 are each a single sitting. The user has said: *"I expect you
to be working 2-3 hours building something."* That is six milestones' worth of work before
anything large begins.

---

## Working rules for the implementation phase

Carried from the user's standing instructions, restated because this is where they bind:

- **Do not modify existing S-CLAW functionality**, delete files, or silently remove features,
  integrations, settings, shortcuts or safety protections. **Preserve the emergency stop.**
- **Do not introduce new runtime dependencies.** Milestones 1–11 need none. If one looks
  necessary, stop and ask.
- **Backward compatibility for plugins is non-negotiable.** `drive-blender` must keep working.
- **Status vocabulary:** PASS / PARTIAL / FAIL / BLOCKED / NOT TESTED / NOT APPLICABLE.
  **Never convert BLOCKED or NOT TESTED into PASS.** Several milestones here have Windows paths
  that cannot be verified in this Linux sandbox; those are BLOCKED with exact run-steps, which
  is the problem Milestone 8 exists to end.
- **No fabricated screenshots, test output, connection status or success reports.** Screenshots
  are taken with the backend actually running.
- **Preserve copyright and licence notices.** Attribution lands in the same commit as the
  borrowed code, with a pinned SHA — the discipline `jsonfix.py` and `OPENCLAW_LICENSE.txt`
  already demonstrate.
- **Never print or expose secrets**, including the per-launch token, in logs, errors, URLs or
  telemetry.
- **Small milestones, each shippable.** Commit per milestone; do not batch.
- **Measure, do not assert.** Any claim about speed or brain quality comes from
  `scripts/brain_bench.py` on a real model, or it is not made.

---

## Open questions for the user

These need his decision, not mine:

1. **Milestone 2 changes a shipped path.** The byte-identical-at-8192 test makes it safe, but
   it is still the only behaviour change in Tier 1. Proceed, or hold it until after the mock
   brain (Milestone 8) can test it at an arbitrary window?
2. **Semantic memory** (SQLite FTS5, zero new dependencies) is deliberately absent from this
   roadmap. Is that wanted, and when?
3. **An online brain / provider-as-plugin** (`MODEL_INTEGRATION.md` §5) is the route to
   *"the brain is going to be online"*, but it is a larger piece of work than anything here and
   is not scheduled. Where does it sit against the plugin ecosystem?
4. **`camel-ai`** is recommended against on present evidence, but that rests on a pinned alpha
   version and an uninspected library — not on anything bad found in it. Worth a separate
   audit, or drop it?
5. **`tiktoken`** would improve token accuracy but is a new dependency against a standing rule.
   The buffers and image sanitiser can be had without it. Confirm: no new dependency?
6. **Milestone 8 is the biggest item and ships nothing visible to users.** Worth doing before
   the plugin work, given it ends the BLOCKED-status problem for everything after it?

---

## Research artefacts

- **Clones:** `/home/user/research-clones/{OpenHands,agent-zero,eigent,goose,hermes-agent,openclaw}`
  — `--depth 1`, 2026-11-12, **outside** the S-CLAW tree. No S-CLAW file was modified by this
  audit. These are in an ephemeral container and will not survive it; re-clone when
  implementation starts, non-shallow, to capture pinned SHAs.
- **Documents:** this directory —
  `PROJECT_ANALYSIS.md`, `SOURCE_CODE_MAP.md`, `MODEL_INTEGRATION.md`,
  `PERFORMANCE_ANALYSIS.md`, `AGENT_ARCHITECTURE.md`, `CODE_REUSE_AND_LICENSES.md`,
  `PROJECT_COMPARISON.md`, `SCLAW_RECOMMENDED_ARCHITECTURE.md`, `IMPLEMENTATION_ROADMAP.md`.
- **Coverage honesty:** `PROJECT_COMPARISON.md` §5. Each project was read at well under 1% of
  its files. Every claim is marked READ / DECL / NAME in `SOURCE_CODE_MAP.md`.
- **Corrections made after checking S-CLAW's own source:** `MODEL_INTEGRATION.md` §2,
  `CODE_REUSE_AND_LICENSES.md` §3, and the revised priority table in `SOURCE_CODE_MAP.md`.
  Four recommendations were withdrawn because S-CLAW already implements them.
