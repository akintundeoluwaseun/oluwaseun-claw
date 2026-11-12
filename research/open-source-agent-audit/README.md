# Open-source agent audit — index

A deep source-code audit of six open-source AI agent projects, done to decide what S-CLAW
should borrow. **Nothing has been implemented. No S-CLAW production file was modified.**

**Projects audited:** Goose (`block/goose`), Eigent (`eigent-ai/eigent`),
OpenClaw (`openclaw/openclaw`), Hermes Agent (`NousResearch/hermes-agent`),
Agent Zero (`agent0ai/agent-zero`), OpenHands (`All-Hands-AI/OpenHands`).

**Method.** All six cloned with `git clone --depth 1` into `/home/user/research-clones/` —
outside the S-CLAW tree. Findings come from reading files, listing directories and grepping
declarations. Every claim in `SOURCE_CODE_MAP.md` is marked **READ** (file opened),
**DECL** (declarations verified by grep) or **NAME** (existence/size only). No code was built,
run or benchmarked, so there are no performance numbers anywhere in these documents.

## Read in this order

| Document | What it answers |
|---|---|
| **`SCLAW_RECOMMENDED_ARCHITECTURE.md`** | **Start here.** What to add to S-CLAW, what not to do, and why. |
| **`IMPLEMENTATION_ROADMAP.md`** | Twelve milestones, each with its tests; plus six open questions needing your decision. |
| `PROJECT_COMPARISON.md` | The capability matrix across all six, and an honest coverage table. |
| `MODEL_INTEGRATION.md` | Local and cloud models — the area you said matters most. |
| `SOURCE_CODE_MAP.md` | Every component, with exact paths, functions and reuse class 1–4. |
| `AGENT_ARCHITECTURE.md` | Agent loop, permissions, plugins, and the turn-taint safety finding. |
| `PERFORMANCE_ANALYSIS.md` | Structural speed measures only — no invented benchmarks. |
| `CODE_REUSE_AND_LICENSES.md` | Licence position per component and the attribution plan. |
| `PROJECT_ANALYSIS.md` | Per-project architecture, with each project's gaps named. |

## Headline conclusions

1. **Keep S-CLAW's architecture.** OpenHands — the only one of the six built the same way
   (Electron + local Python backend + `127.0.0.1` + per-session key) — validates the shape.
   No project surveyed holds more than about a third of the useful techniques, so there is
   nothing to adopt wholesale. The proposal is additive.
2. **S-CLAW is already ahead in several places.** Four recommendations were **withdrawn** after
   checking S-CLAW's own source: it already probes `/props` for the served context window and
   logs asked-vs-actual; it already passes `trust_env=False` on every HTTP client (stronger
   than Eigent's fix); it already repairs model JSON (`jsonfix.py`); and it already has a
   third-party attribution file (`OPENCLAW_LICENSE.txt`). These are marked **CORRECTION** in
   the relevant documents.
3. **One real defect found in S-CLAW's own code.** `CATALOGUE_BUDGET = 1800` and
   `FULL_CATALOGUE_BUDGET = 4800` (`backend/claw/agent/executor.py:1048`/`:1053`) are absolute
   constants, while `fit_context` correctly budgets from the *probed* window. On a server that
   serves 2048 tokens they overcommit. `MODEL_INTEGRATION.md` §2.
4. **The highest-value addition is a safety one.** Turn taint (~65 lines, from OpenClaw's
   `turn-taint.ts`): once a turn has read untrusted content, an EXTERNAL or DESTRUCTIVE action
   needs fresh confirmation regardless of standing approval. S-CLAW's rules already say to
   treat web pages as untrusted; there is currently no mechanism that *knows* a turn read one.
5. **All six are MIT or Apache-2.0.** None is copyleft; none would force S-CLAW open. The real
   risks are dependencies, not licences — in particular `camel-ai[eigent]==0.2.91a7`, an alpha
   pin that Eigent's apparent tool breadth actually lives in.
6. **Zero new runtime dependencies** are needed for eleven of the twelve proposed additions.

## Honest limits

Each project was read at well under 1% of its files (clones range from 2,885 to 64,447 files).
The largest bodies of code in the best-structured projects went unread. Coverage is itemised
in `PROJECT_COMPARISON.md` §5; every "not found" in these documents means "I did not find it",
not "it is absent". `IMPLEMENTATION_ROADMAP.md` Milestone 0 lists the verification reads that
must happen before any code is written.
