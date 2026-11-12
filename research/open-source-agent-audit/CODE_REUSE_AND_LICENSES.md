# CODE_REUSE_AND_LICENSES.md

**I am not a lawyer and this is not legal advice.** What follows is a record of what the
licence files in the clones actually say, what obligations they state on their face, and where
the risks are. Before shipping **copied** code in a commercially distributed installer, have
the final attribution set reviewed by someone qualified.

The good news up front: **all six projects are under permissive licences (MIT or Apache-2.0).
None is copyleft. None would force S-CLAW to open its source.** The real risks are not
licence incompatibility — they are (a) failing to attribute, (b) third-party *dependencies*
rather than the projects themselves, and (c) one specific competitive-sensitivity judgement.

---

## 1. Verified licence position

Read from each clone's `LICENSE` file:

| Repo | Licence | Copyright line as written | Per-file headers | `NOTICE` file |
|---|---|---|---|---|
| OpenHands | MIT ("The MIT License (MIT)") | `Copyright © 2025 OpenHands contributors` | not checked | not checked |
| agent-zero | MIT | `Copyright (c) 2025 Agent Zero, s.r.o` | not checked | not checked |
| eigent | Apache-2.0 (201-line file) | per-file: `Copyright 2025-2026 @ Eigent.ai All Rights Reserved.` | **1,493 files** | **none** |
| goose | Apache-2.0 (201-line file) | (repo LICENSE only) | **0 files** | **none** |
| hermes-agent | MIT | `Copyright (c) 2025 Nous Research` | not checked | not checked |
| openclaw | MIT | `Copyright (c) 2026 OpenClaw Foundation` | not checked | not checked |

OpenHands additionally declares `"license": "MIT"` in `package.json` (`"name":
"@openhands/agent-canvas"`, `"version": "1.40.0"`).

### Two facts that materially simplify the Apache-2.0 cases

**Neither Eigent nor Goose ships a `NOTICE` file.** Apache-2.0 §4(d) only requires propagating
attribution notices *"If the Work includes a `NOTICE` text file"*. Since neither does, that
clause imposes nothing. What remains for Apache-2.0 is §4(a)–(c): include the licence, state
changes, and retain existing copyright/patent/attribution notices in the source you copy.

**Eigent has 1,493 files carrying `Copyright 2025-2026 @ Eigent.ai All Rights Reserved.`;
Goose has none in `crates/`.** So:

- Copying any Eigent source file means **keeping that header verbatim** in the copied file.
- Copying Goose source carries no per-file header obligation — only the repo-level licence and
  attribution.

---

## 2. What each licence requires in practice for a Windows installer

### MIT (OpenHands, agent-zero, hermes-agent, openclaw)
If you copy or substantially adapt the code: include the copyright notice and the MIT licence
text somewhere in the distribution. That is the whole obligation. No source disclosure, no
change log, no restriction on commercial sale, no patent grant.

### Apache-2.0 (eigent, goose)
If you copy or substantially adapt the code:
1. Include a copy of the Apache-2.0 licence.
2. **State that you changed the files** (§4(b)) — a line per adapted file is enough.
3. Retain existing copyright, patent, trademark and attribution notices in the copied source
   (§4(c)) — for Eigent, that is the per-file header.
4. §4(d) `NOTICE` propagation: **not applicable**, as established above.

Apache-2.0 also grants patent rights, which is a mild advantage over MIT, and terminates that
grant if you sue the licensor over patents — irrelevant here.

### Where the obligations do **not** apply
Reading source and then writing your own implementation of the same *idea* creates no
obligation under either licence. Facts are not copyrightable: Eigent's port numbers
(`11434`, `8000`, `30000`, `1234`, `8080`) and discovery paths (`/api/tags`, `/v1/models`) are
facts. Goose's list of required CPU features (`fma`, `avx2`, `f16c`, `bmi2`, `sse4.2`) is a
fact. A JSON manifest's **field names** are close to a fact.

**This distinction is where almost all of this audit's value sits.** Nearly every
recommendation in the other documents is *"copy the decision, write our own code"*, which
carries no obligation at all. Only a handful of items involve actual copying.

---

## 3. A worked example of correct practice, found in the wild

`openclaw/packages/agent-core/src/repetition-guard.ts` line 1:

```ts
// Adapted from Hermes Agent; see THIRD_PARTY_NOTICES.md for the pinned source and MIT license.
```

And `openclaw/THIRD_PARTY_NOTICES.md` (111 lines total), lines 80–99, read:

```
## Hermes Agent

OpenClaw's live repetition guard adapts the bounded streaming checks, repeated
text detection, and sampled exact-period expansion from Hermes Agent.

- Upstream: https://github.com/NousResearch/hermes-agent
- Source: https://github.com/NousResearch/hermes-agent/blob/acc3cada0da86c81efc8aa6c5a291989549ca900/agent/repetition_guard.py
- OpenClaw source: `packages/agent-core/src/repetition-guard.ts`
- License: MIT
- Copyright: Copyright (c) 2025 Nous Research

MIT License

Copyright (c) 2025 Nous Research
[...full licence text...]
```

**This is the template S-CLAW should adopt verbatim as a practice.** Note each element and why
it matters:

- A **comment at the top of the adapted file** pointing at the notices file — so a future
  reader of that file knows immediately.
- **A pinned commit SHA** in the source URL (`acc3cada0da…`), not a branch. A branch URL rots
  and makes the provenance unverifiable; a SHA is permanent evidence of exactly what was
  adapted.
- A sentence saying **what specifically** was adapted ("the bounded streaming checks, repeated
  text detection, and sampled exact-period expansion") — which also discharges Apache-2.0
  §4(b)-style change statements when the upstream is Apache.
- Both the upstream path **and** the local path.
- The **full licence text**, not just its name.

The user's standing rules already say *"Preserve copyright and licence notices for reused
code"* and *"Never copy code if its licence is incompatible or unclear."* This file is what
compliance looks like when done properly, and it costs about fifteen lines per borrowed
component.

### CORRECTION: S-CLAW already does this, and already borrows from OpenClaw

**I checked S-CLAW's own tree after writing the above.** The practice I was about to recommend
creating **already exists**:

`backend/claw/agent/OPENCLAW_LICENSE.txt`, line 1:

```
# Applies to the parts of S-CLAW ported from OpenClaw: claw/browser/ddg_html.py,
# claw/agent/jsonfix.py, claw/agent/skills.py
```

followed by the full MIT licence text and `Copyright (c) 2026 OpenClaw Foundation`. And
`backend/claw/agent/jsonfix.py` (113 lines) carries a provenance docstring naming the exact
upstream file:

> `repair()` is ported from OpenClaw (MIT, (c) 2026 OpenClaw Foundation),
> `packages/ai/src/utils/json-parse.ts` (`repairJson`), rewritten in Python for S-CLAW.

So **three** S-CLAW files are already ported from OpenClaw, with a licence file, a per-file
provenance docstring, and the specific upstream path named. That is most of OpenClaw's own
template already in place. Two things it does not yet have, and both are small:

1. **A pinned commit SHA.** The docstring names `packages/ai/src/utils/json-parse.ts` but not
   *which revision*. Without a SHA the provenance cannot be re-verified later, which is the one
   element of OpenClaw's own notices entry that is missing here. Add the SHA for each of the
   three existing ports.
2. **One notices file, at the repo root, shipped by the installer.** `OPENCLAW_LICENSE.txt`
   sits inside `backend/claw/agent/`, which is right next to the code but is not where a
   distribution notice belongs, and there will be more upstreams than OpenClaw (Hermes is next).

**Revised recommendation:** promote the existing practice to a root `THIRD_PARTY_NOTICES.md`
with one section per upstream (keeping `OPENCLAW_LICENSE.txt` or folding it in), add pinned
SHAs for the three existing OpenClaw ports, and make the electron-builder / Inno Setup payload
include it. **This is an extension of something S-CLAW already does correctly, not a new
discipline.**

It also settles §6 below empirically: S-CLAW has *already* borrowed from OpenClaw, with
attribution, and nothing went wrong.

---

## 4. Per-component licence assessment

Components are the ones named in `SOURCE_CODE_MAP.md`.

| # | Component | Repo / Licence | Copying involved? | Obligation | Verdict |
|---|---|---|---|---|---|
| 1 | Served-window probe + compactor clamp | hermes / MIT | Likely adaptation of ~60 Python lines | MIT notice + `THIRD_PARTY_NOTICES.md` entry with pinned SHA | **Safe. Proceed.** |
| 2 | Repetition guard | hermes / MIT | Likely adaptation of ~110 Python lines | Same | **Safe. Proceed.** |
| 3 | Tool-call repair design | openclaw / MIT | Reimplementation in Python from a read of the TS | None strictly; attribute anyway | **Safe — and precedent already set: `jsonfix.py` is such a port** |
| 4 | Turn taint | openclaw / MIT | Reimplementation (~65 lines) | None strictly; attribute anyway | **Safe — but see §6** |
| 5 | Tiny-model prompt *techniques* | goose / Apache-2.0 | **No** — techniques only, text rewritten | None | **Safe. Do not paste the text.** |
| 6 | CPU feature pre-flight gate | goose / Apache-2.0 | No — reimplemented in Python; the feature list is a fact | None | **Safe.** |
| 7 | Local provider endpoint table | eigent / Apache-2.0 | If the file is copied: **yes** | Apache licence + keep the `Copyright 2025-2026 @ Eigent.ai` header + state changes | **Safe if attributed. Prefer re-expressing the facts in Python — then no obligation.** |
| 8 | Browser robustness techniques | eigent / Apache-2.0 | No — techniques applied to S-CLAW's own Playwright code | None | **Safe.** |
| 9 | Token buffers + image sanitiser | agent-zero / MIT | Two constants and a regex idea; likely rewritten | MIT notice if the regex is copied | **Safe.** |
| 10 | Context X-ray category taxonomy | goose / Apache-2.0 | Seven category names | Arguably none; attribute as courtesy | **Safe.** |
| 11 | Structured compaction + `FileActivity` | goose / Apache-2.0 | No — design only | None | **Safe.** |
| 12 | Plugin manifest field set | openclaw / MIT | Field names only | None | **Safe — see §6** |
| 13 | Windows-install E2E pattern | OpenHands / MIT | No — the pattern; S-CLAW uses Inno Setup, not npm | None | **Safe.** |
| 14 | Permission `PrincipalType` idea | goose / Apache-2.0 | No — design only | None | **Safe.** |
| 15 | Plugin `api/` channel + ordered hooks | agent-zero / MIT | No — design only | None | **Safe.** |

**Nothing in this table is blocked on licensing.** The two items that involve real copying
(1 and 2, both Hermes/MIT) are the cheapest possible case: MIT, Python already, small files.

---

## 5. The real risk is dependencies, not the projects

This is where a wholesale "reuse project X" plan would go wrong, and it is the reason the
recommendation throughout this audit is to take *techniques*.

### 5a. Eigent → `camel-ai`, and this one is disqualifying as it stands

`eigent/backend/pyproject.toml` line 9, read:

```
"camel-ai[eigent]==0.2.91a7",
```

Three problems, all verified from that one line plus `pyproject.toml` line 68
(`known-third-party = ["camel"]`):

1. **`0.2.91a7` is an alpha release.** Pre-1.0 and explicitly pre-release.
2. **`[eigent]` is a custom extra** — an extras group apparently defined for this consumer,
   pulling an unknown dependency set.
3. **I never inspected `camel-ai`** — not its source, not its licence, not its transitive
   dependency tree, not its install scripts.

And as established in `SOURCE_CODE_MAP.md` §E3, **Eigent's apparent tool breadth is mostly
camel-ai's, not Eigent's**: `pyautogui_toolkit.py` is 40 lines wrapping
`BasePyAutoGUIToolkit`. So "adopt Eigent's 42 toolkits" means "adopt an alpha release of an
uninspected library with a custom extras group."

That runs straight into the user's own standing rules — *"Do not download or execute arbitrary
repositories before inspecting their source, license, dependencies, install scripts, security
implications, and compatibility"* and *"never copy a repo wholesale without reviewing
licence/deps/security."*

**Verdict: class 4 — not recommended.** Not because camel-ai is bad (I have no evidence either
way) but because adopting it is a large, uninspected decision taken for breadth S-CLAW does
not need. S-CLAW's own pywinauto/UIA executor is also a **better** fit: the standing rule is
*"accessibility/UIA first, OCR/screenshots as fallback, coordinates last"*, and `pyautogui` is
coordinate-first by design — it works against that rule rather than with it.

**If the user still wants camel-ai evaluated, that is a separate audit** with its own
clone-and-read pass. I am not recommending it on present evidence.

### 5b. Agent Zero's dependency surface

`agent-zero/requirements.txt`, first 30 lines read. Pinned entries include: `a2wsgi`, `ansio`,
`docker==7.1.0`, `duckduckgo-search==6.1.12`, `pyreqwest-impersonate==0.5.3`,
`faiss-cpu==1.11.0`, `fastmcp==3.2.4`, `fasta2a`, `flask[async]==3.0.3`, `flask-basicauth`,
`flaredantic`, `GitPython==3.1.43`, `giturlparse`, `httpx[socks]==0.28.1`, `inputimeout`,
`json_repair==0.63.4`, `kokoro>=0.9.2`, `simpleeval==1.0.3`, `langchain-core==0.3.49`,
`langchain-community==0.3.19`, `langchain-unstructured`, `liteparse`, `litellm==1.104.0`,
`openai==2.54.0`, `openai-whisper==20250625`, `lxml_html_clean>=0.4.0`, `markdown==3.7`,
`mcp==1.27.0`, `newspaper3k==0.2.8`, `paramiko==3.5.0`.

Observations, stated as observations:

- **They pin tightly and annotate why.** `pyreqwest-impersonate==0.5.3  # freeze nearest
  wheel-backed release; 0.5.5 is source-only` — a source-only dependency would need a compiler
  on the user's machine. That is exactly the class of problem a Windows installer must avoid,
  and the comment is good practice worth imitating in S-CLAW's own pins.
- **They track CVEs in the requirements file.** `lxml_html_clean>=0.4.0  # CVE-2024-52595 fix:
  XSS CWE-79 CVSS 8.4`. Also worth imitating.
- **The memory subsystem's real cost is visible here:** `faiss-cpu`, `langchain-core`,
  `langchain-community`, `langchain-unstructured`. Porting Agent Zero's FAISS memory means all
  of these plus an embedding model — a second local model to ship or download, on top of the
  brain.
- **Several entries carry their own risk profile** regardless of licence: `docker`,
  `paramiko` (SSH), `simpleeval` (expression evaluation), `newspaper3k` (long unmaintained),
  `openai-whisper` and `kokoro` (large model-bearing packages).
- **I did not check any of these licences.** None was read. Pinned versions ≠ verified
  licences.

**Verdict: class 3 — architectural reference only.** Against the standing rule *"Do not
introduce new dependencies into the application"*, and given SQLite FTS5 can deliver exact and
keyword recall with **zero** new dependencies (while the valuable parts of Agent Zero's design
— index integrity hashing, two deletion paths, exact-match alongside ranked match, on-disk
partitioning, a memory dashboard — are all implementable on FTS5), a FAISS/LangChain port is
out of proportion to S-CLAW's current need.

### 5c. OpenClaw's `tool-call-repair` cannot be installed even if you wanted to

`openclaw/packages/tool-call-repair/package.json`, read in full:

```json
{ "name": "@openclaw/tool-call-repair", "version": "0.0.0-private", "private": true,
  "type": "module", "exports": { ".": "./src/index.ts" },
  "dependencies": { "@openclaw/normalization-core": "workspace:*" } }
```

`"private": true` and `"version": "0.0.0-private"` mean it is **not published to npm**. The
dependency is `workspace:*` — another unpublished workspace package. So reuse means porting
both, and S-CLAW's backend is Python anyway. **This is a port, not a dependency** — which is
also why its licence obligation is light.

### 5d. Goose is Rust

`goose-local-inference` (8,140 lines), `goose-context-management` (70-line public API),
`goose-agent` (2,761 lines) are all Rust. `goose-context-management`'s doc comment states
cross-language access is exposed by `goose-sdk` via **uniffi bindings** for Python and Kotlin,
and `goose/AGENTS.md` says some workspace crates are published to crates.io as the "GDK".

**I did not verify that a Python package exists, is published, or is installable.** If it is,
Goose's compaction could in principle be a *dependency* rather than a port — but that would
mean shipping a Rust-built native extension inside a PyInstaller bundle, which is a
significant packaging decision for a Windows installer and not obviously worth it for a
70-line API. **Flagged as an open question, not a recommendation.**

---

## 6. The OpenClaw judgement call — stated plainly because it matters

The user has said: *"I'm actually competing with OpenClaw."*

Two of this audit's highest-value findings come from OpenClaw: `tool-call-repair` (§B1) and
`turn-taint.ts` (§2a of `AGENT_ARCHITECTURE.md`). The plugin manifest format (§G1) is a third.

**The legal position is clear.** OpenClaw is MIT ("Copyright (c) 2026 OpenClaw Foundation").
MIT explicitly permits use, copying, modification and sale, by anyone, including a competitor,
with no restriction beyond notice retention. There is no non-compete, no field-of-use limit, no
"non-commercial" clause. OpenClaw itself adapts MIT code from Hermes and attributes it
(§3) — the same thing S-CLAW would be doing.

**The practical position has three parts, and I would act on all three:**

1. **Reimplement in Python; do not transliterate.** S-CLAW's backend is Python, so this is the
   natural path regardless. 4,296 TypeScript lines is also far more than S-CLAW needs — the
   valuable core of `tool-call-repair` is the prefilter, the four shape classifiers, the
   field-name tolerance, the schema-echo exclusion and the protected ranges. Writing that from
   a design understanding yields better code *and* the lightest possible obligation.
2. **Attribute anyway, even where strictly unnecessary.** A `THIRD_PARTY_NOTICES.md` entry
   costs nothing, removes any argument, and is simply the right thing. It also protects the
   user: a competitor who finds an unattributed near-copy has a story to tell; one who finds a
   clean attribution has nothing.
3. **Do not copy anything that carries OpenClaw's identity** — names, branding, the
   `openclaw.plugin.json` filename, the `__openclaw` metadata key, user-facing strings. The
   user explicitly wants his **own** plugin format; adopting the *field set* while using
   S-CLAW's own names and file naming is both better product design and a cleaner separation.

**One genuine caution.** The taint mechanism and the repair parser are security-relevant. A
reimplementation that misses a detail — for instance, failing to require the *literal* `"network"`
and literal `true` when reading taint metadata, which is what stops injected content forging a
clean state — produces something that looks like a defence and is not. **Port carefully, with
tests derived from the original's edge cases**, or do not port it at all.

---

## 7. What S-CLAW must not do

Drawn from the standing rules and from what this audit found:

- **Do not bundle any model weights** from these repos. No weights were examined and none has
  verified redistribution terms. S-CLAW's existing discipline —
  `ALLOWED_LICENSES = {"apache-2.0", "mit"}` on its own brain catalogue — is the right model
  and should not be loosened.
- **Do not vendor a whole repository.** Every single-file or single-technique borrow in this
  audit is small. There is no case for a wholesale copy, and `camel-ai` shows what one costs.
- **Do not mix a copied file's licence into S-CLAW's own headers.** A copied Eigent file keeps
  its `Copyright 2025-2026 @ Eigent.ai` header. It does not become S-CLAW's code because it
  sits in S-CLAW's tree.
- **Do not paste Goose's `tiny_model_system.md`.** Beyond the Apache notice, it contains
  `"You are goose, an autonomous AI agent created by AAIF"` — pasting it would put another
  product's identity into S-CLAW's prompt. Adapt the techniques.
- **Do not add a dependency to get a technique.** Items 1, 2, 4, 6, 8, 9 in §4 need **zero**
  new dependencies. That is not a coincidence; it is why they were selected.
- **Do not claim a licence is fine without reading it.** This document reads six `LICENSE`
  files and **zero** dependency licences. `camel-ai`, `faiss-cpu`, `langchain-*`, `litellm`,
  `tiktoken` — all unverified here.

---

## 8. Concrete compliance actions, in order

1. **Promote the existing `backend/claw/agent/OPENCLAW_LICENSE.txt` into a root
   `THIRD_PARTY_NOTICES.md`**, structured as OpenClaw's own (§3): a section per borrowed
   component with upstream URL, **pinned commit SHA**, local path, licence name, copyright line,
   and full licence text. S-CLAW already has the licence text and the file list for OpenClaw —
   this is a move plus the SHAs, not a new document from scratch.
2. **Make the installer ship it.** Add it to the electron-builder / Inno Setup payload and to
   an About or Legal screen. A notices file that only exists in the repo does not discharge a
   distribution obligation.
3. **Add a one-line provenance comment at the top of every adapted file**, pointing at the
   notices file — OpenClaw's pattern.
4. **Backfill pinned SHAs for the three existing OpenClaw ports**
   (`claw/browser/ddg_html.py`, `claw/agent/jsonfix.py`, `claw/agent/skills.py`), and record the
   pinned SHA at the moment you copy anything new. These are `--depth 1` clones, so no
   history is available here; capture the SHA from the upstream file URL at copy time. Without
   it, the provenance is unverifiable later.
5. **For Apache-2.0 sources (eigent, goose): state the changes** in the notices entry. One
   sentence per adapted file.
6. **Add a repo test that fails if a file in the tree carries a third-party copyright header
   without a matching `THIRD_PARTY_NOTICES.md` entry.** This project's experience is that the
   rules that hold are the ones a test enforces — `tests/test_filenames_work_on_windows.py`
   exists for exactly that reason.
7. **Before commercial distribution of any installer containing copied code, get the final
   notices set reviewed by someone qualified.** I am not that.

---

## 9. Gaps and uncertainties in this document

- **No dependency licence was read.** Not `camel-ai`, `faiss-cpu`, `langchain-*`, `litellm`,
  `tiktoken`, `pulldown_cmark`, `llama-cpp-2`, `rmcp`, or anything else.
- **Per-file headers were only counted for eigent and goose** (1,493 and 0). OpenHands,
  agent-zero, hermes-agent and openclaw were **not** scanned for per-file headers, so a file
  borrowed from those four must be checked individually before copying.
- **`NOTICE` presence was only checked for eigent and goose** (neither has one). Not checked
  for the MIT four — though MIT has no `NOTICE` mechanism, so this is immaterial.
- **`openclaw/THIRD_PARTY_NOTICES.md` was read only around its Hermes section** (lines 80–99 of
  111). Its other entries may name further upstreams relevant to components recommended here —
  in particular, if `tool-call-repair` or `turn-taint.ts` were themselves adapted from a third
  party, that upstream would be the better source. **Reading the full 111 lines is a
  prerequisite before porting either**, and is listed in `IMPLEMENTATION_ROADMAP.md`.
- **OpenClaw also contains `crates/`, `security/`, `patches/`, `custodian-skills/` and a
  `SECURITY.md`,** none of which were examined. `patches/` in particular may indicate patched
  third-party packages with their own terms.
- **Trademark was not considered at all.** "Goose", "OpenClaw", "Eigent", "OpenHands",
  "Agent Zero" and "Hermes" are product names; neither MIT nor Apache-2.0 grants trademark
  rights (Apache-2.0 §6 expressly withholds them). Keep all of them out of S-CLAW's UI,
  installer and marketing except in a notices file.
