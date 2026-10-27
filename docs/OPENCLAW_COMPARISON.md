# OpenClaw compared with S-CLAW — capability gap analysis

Dated 27 October 2026.

## How this was researched, and what that limits

`docs.openclaw.ai` is **not reachable** from this build container (curl returns
`000` — the egress proxy refuses it), and `github.com` HTML returns `403`. What
*is* reachable is `raw.githubusercontent.com`, which serves the repository's own
files, and `registry.npmjs.org`.

So every OpenClaw statement below is cited to a file fetched from
`raw.githubusercontent.com/openclaw/openclaw/main/…` on 27 Oct 2026, at package
version **2026.10.7** (`package.json`), licence **MIT**, Node `>=24.22.1 <25 ||
>=26.12.1`. The files retrieved were:

```
README.md                         docs/concepts/architecture.md
SECURITY.md                       docs/concepts/model-providers.md
package.json                      docs/concepts/memory.md
docs/tools/index.md               docs/concepts/user-model.md
docs/tools/skills.md              docs/gateway/configuration.md
docs/tools/ask-user.md            docs/gateway/config-tools.md
docs/tools/secrets.md             docs/gateway/sandboxing.md
docs/tools/browser.md             docs/automation/index.md
docs/tools/exec.md                docs/channels/index.md
docs/tools/screen.md              docs/platforms/index.md
docs/start/why-openclaw.md        docs/platforms/windows.md
```

**Two limits on reading this report.** Many OpenClaw doc pages are index pages
that route to sub-pages I could not fetch, so depth is uneven. And where a row
says "no evidence found", that means *not in the pages above* — it is not proof
that OpenClaw lacks the feature. Nothing here is written from memory of the
project; anything I could not fetch is marked rather than filled in.

S-CLAW's side is cited to code and tests in this repository. Labels:

- **Verified implemented** — code exists and automated tests cover it here.
- **Partially implemented** — some of it works; the rest is named.
- **Blocked** — written, but unprovable in this container (no Windows, no model
  weights, no public internet, no hosted service).
- **Not implemented** — does not exist. Documentation and mocks do not count.

---

## The comparison

| # | Capability | OpenClaw — evidence | S-CLAW — evidence | Gap | Priority | Effort | Dependencies |
|---|---|---|---|---|---|---|---|
| 1 | **Overall shape** | A single long-lived **Gateway** daemon owns every surface; CLI, Control UI, TUI and nodes connect over WebSocket on `127.0.0.1:18789` (`docs/concepts/architecture.md`). "One Gateway per host." | FastAPI backend on `127.0.0.1` with a per-launch token, driven by one Electron app (`backend/claw/api/app.py`). *Verified implemented.* | Different bet, not a deficiency: OpenClaw is a chat-first daemon, S-CLAW is a desktop app. | — | — | — |
| 2 | **Messaging channels** | 20+ channels as plugins — WhatsApp (Baileys), Telegram (grammY), Slack, Discord, Signal (signal-cli), iMessage, Teams, Matrix, SMS/Twilio and more (`docs/channels/index.md`, `README.md`). | None. S-CLAW **operates the apps already on the computer** instead of bridging them (`docs/HOW_IT_WORKS.md`, `backend/claw/tools/desktop_tools.py`). *Not implemented — deliberately.* | S-CLAW cannot be messaged from a phone. | Low | L | A bridge per service, plus the ToS risk the current design avoids |
| 3 | **Driving the user's own Windows apps** | The Windows node exposes `screen.snapshot`, `screen.record`, `camera.*`, `system.notify`, `system.run`, `location.get`, `talk.*` (`docs/platforms/windows.md`). The `screen` tool is Control-UI layout, "not screenshot capture or browser automation" (`docs/tools/screen.md`). **No evidence found** in the retrieved pages of UI-Automation-style control — reading an accessibility tree, clicking a named control, typing into another app's window. | `launch_app`, `focus_window`, `look_at_window`, `click_control`, `type_into`, `press_keys`, `choose_menu`, `read_control`, `wait_for_window` + screenshot/OCR fallback (`backend/claw/tools/desktop_tools.py`, 26+ tests in `backend/tests/test_desktop.py` against a labelled double). *Blocked — no Windows desktop here.* | None against the evidence retrieved; this is S-CLAW's distinctive capability. **Do not trade it away.** | — | — | A real Windows machine to lift it from Blocked to Verified |
| 4 | **Tool catalogue pressure** | `tool_search`, `tool_describe`, `dispatch_action` and Code Mode exist specifically to "search, call, and combine many eligible tools **without sending every schema to the model**" (`docs/tools/index.md`). Plus profiles, groups, `allow`/`deny`, `byProvider`, `toolsBySender`, `elevated` layers (`docs/gateway/config-tools.md`). | Filtering already exists and I had to measure it rather than assume: the **planner** is never sent tool schemas at all, only four capability names (`backend/claw/agent/planner.py`), and the **executor** sends full schemas only for the plan's capabilities, naming the rest (`tool_catalogue`, `backend/claw/agent/executor.py:143`). Measured today: unfiltered **35,689 chars ≈ 8.9k tokens**; `browser` 1.5k; `desktop` 1.9k; **`files` 5.8k**. *Partially implemented.* | Narrower than it first looks, but real in three specific places: (a) `files` holds **37 of 76** tools, because calendar, memory, briefing, mail, document and spreadsheet tools all declare `Capability.FILES` — a bucket I made worse this session; (b) the filter uses the **union** of the whole plan's capabilities, not the current step (`backend/claw/agent/runner.py`), so a three-capability plan sends nearly everything; (c) a plan with no capability but `reasoning` falls through to **unfiltered** — all 76. | **P1** | S–M (1–2 d) | None — pure local work |
| 5 | **Event-triggered automation** | Four mechanisms: **automations** (cron, one-shot `--at`, job history), **hooks** (`HOOK.md` on lifecycle events; plugin `api.on(...)` can intercept every tool call), **webhooks** (authenticated HTTP ingress), **standing orders** injected into every session (`docs/automation/index.md`). | Time-based jobs only — `every N minutes` / `daily at HH:MM`, with history, pause, run-now (`backend/claw/jobs/`, 29 tests). *Partially implemented.* | No reaction to events: a file appearing, a webhook, a session lifecycle point. | **P1** | M (2–4 d) | A local HTTP ingress decision; webhooks mean opening a port, which conflicts with loopback-only |
| 6 | **Unattended safety** | Sandboxing is **off by default**, with Docker/Podman/SSH/OpenShell/Crabbox backends; "the Gateway process always stays on the host; only tool execution moves into the sandbox" (`docs/gateway/sandboxing.md`). Candid note: "This is not a perfect security boundary." | No sandbox. Instead: risk levels with a destructive floor settings cannot lower, a folder allowlist, and `PermissionPolicy.unattended()` — every "ask" becomes "no" and destructive work is refused outright for scheduled jobs (`backend/claw/permissions/policy.py`, `backend/tests/test_jobs.py`). *Verified implemented.* | Different answer to the same risk. S-CLAW restricts *what may run*; OpenClaw restricts *where it runs*. Ours needs no Docker on a user's laptop. | Low | — | Sandboxing would mean shipping a container runtime to end users |
| 7 | **Credentials the agent must never see** | `secrets` tool: the agent names an entry, the human types the value into a trusted prompt, the Gateway writes it to a secret store; "the value never appears in the chat, the session transcript, the tool result, or the model's context" — the agent gets a `SecretRef` (`docs/tools/secrets.md`). | `pause_for_me` stops and asks the person to type it **themselves, into the real app** — S-CLAW never receives it at all (`backend/claw/tools/human_tools.py`). Memory refuses to store secrets before the write (`backend/claw/memory/secrets.py`, 28 tests). *Verified implemented.* | S-CLAW has no **store**, so a tool that legitimately needs an API key (a weather service, a provider) cannot be given one without the user pasting it into Settings. | P2 | M (2–3 d) | OS keychain (DPAPI on Windows) to avoid a plaintext store |
| 8 | **Structured human questions** | `ask_user` — one to three structured questions, main session only, surface must declare question input; otherwise the agent asks in plain text (`docs/tools/ask-user.md`). | Approval cards carry a question, and `pause_for_me` is the "over to you" path, but there is no general "ask the user N structured questions mid-task" tool (`backend/claw/agent/executor.py`). *Partially implemented.* | Clarifying questions mid-task are not available to the planner. | P2 | S (1 d) | None |
| 9 | **Memory** | Plain Markdown in the workspace: `USER.md`, `MEMORY.md`, `memory/YYYY-MM-DD.md`, `DREAMS.md`; "the model only remembers what gets saved to disk; there is no hidden state"; a changed preference is **superseded in place** (`docs/concepts/memory.md`). | SQLite with five closed kinds, provenance on every row, replace-in-place on restatement, a Settings panel with per-row Remove, Export and Forget everything, and secrets refused before the write (`backend/claw/memory/`, `backend/claw/tools/memory_tools.py`, 28 tests). *Verified implemented.* | OpenClaw's is human-editable in a text editor; ours is structured and exportable. Roughly equal; ours is stricter about secrets, theirs is easier to hand-edit. | P3 | S | Export already exists |
| 10 | **Skills / extensibility** | `SKILL.md` instruction packs from workspace, shared dirs, or plugin packages (`docs/tools/skills.md`, 48 KB of it); plugins add tools, channels, providers, hooks; installable from ClawHub, npm, git, directories, archives (`docs/tools/index.md`). | A fixed registry compiled into the app. No plugin loader, no skill packs. *Not implemented.* | Every new capability needs a release. | P2 | L | A signing/trust story first — loading third-party code into a desktop agent with desktop control is the dangerous version of this feature |
| 11 | **Multi-agent** | `subagents`, `swarm`, `sessions_*`, `agents_wait`, goals (`create_goal`/`update_goal`), ACP agents (`docs/tools/index.md`). | One task at a time, by design; `TaskRunner` refuses a second (`backend/claw/agent/runner.py`). *Not implemented.* | No parallel or delegated work. | P3 | L | Would multiply the permission surface; low value for one person at one keyboard |
| 12 | **Model providers** | Many hosted providers plus local via custom providers — llama.cpp, Ollama, LM Studio, vLLM, LiteLLM (`docs/concepts/model-providers.md`). | Three modes: built-in llama.cpp brain, Claw-hosted service, user-configured OpenAI-compatible endpoint (`backend/claw/models/`, `backend/claw/edition.py`, 16 tests). *Blocked* — no real model has answered in this container. | OpenClaw supports more endpoints; S-CLAW's local path is bundled rather than BYO-runtime. | P3 | S | Weights and a GPU-less laptop to measure on |
| 13 | **Code execution** | `exec`, `process`, `terminal`, `code_execution` (`docs/tools/index.md`, `docs/tools/exec.md`). | None. Shell execution is deliberately absent; `is_program_running` uses fixed-argument process listing, never a shell. *Not implemented — deliberately.* | S-CLAW cannot run arbitrary commands. | Low | — | Adding it would undo the main safety property of the product |
| 14 | **Media generation** | `image_generate`, `music_generate`, `video_generate`, `tts`, `view_image` (`docs/tools/index.md`). | `edit_image`, `inspect_image`, `make_flyer` (Pillow). No generation, no TTS (`backend/claw/tools/image_tools.py`). *Partially implemented.* | No generation. **This is the honest answer to "video"**: OpenClaw calls a provider; nothing here does. | P3 | M | A provider and its key — i.e. gap #7 first |
| 15 | **Calendar and reminders** | Automations are the recommended way to "monitor calendar for upcoming events" (`docs/automation/index.md`). **No evidence found** of a built-in calendar tool in the retrieved pages. | `.ics` on disk, create/list/cancel/find-free-time, reminders as real `VALARM`s, shown once, stale ones retired, RRULE refused rather than guessed (`backend/claw/calendar/`, 34 + 12 tests). *Verified implemented* (logic); the Windows notification itself is *Blocked*. | Ahead, on the retrieved evidence. | — | — | A Windows machine to confirm the notification |
| 16 | **Daily briefing** | Named as an automation use case ("send daily report at 9 AM"), assembled by the agent (`docs/automation/index.md`). | A first-class `daily_brief` tool and `GET /brief` that always states what it cannot see (`backend/claw/brief.py`, 12 tests). *Verified implemented* (logic); delivery *Blocked*. | Comparable. | — | — | — |
| 17 | **E-mail** | An **IMAP plugin** exists for "sender-gated isolated reader sessions" (`docs/automation/index.md`). | `compose_mail` opens a draft in Gmail, Outlook or the default client and **never sends** (`backend/claw/tools/mail_tools.py`). No reading, no search. *Partially implemented.* | No inbox access. | P2 | L | OAuth app registration, token storage, refresh — none testable here |
| 18 | **Remote / multi-user** | Tailscale Serve, trusted-proxy auth, shared-secret auth, team deployments, per-requester `USER.md`, pairing of unknown senders (`docs/concepts/architecture.md`, `docs/concepts/user-model.md`, `README.md`). | Loopback only, single user, per-launch token. *Not implemented — deliberately.* | No remote access. | Low | — | Would require the whole exposure story OpenClaw documents |
| 19 | **Telemetry** | A daily version check by default; anonymous feature stats opt-in; `update.checkOnStart: false` disables both (`README.md`). | None. S-CLAW contacts nothing it was not asked to. *Verified implemented* (by absence — there is no telemetry code). | S-CLAW has no update check at all, which is also a gap: users will not learn about fixes. | P3 | S | A release feed, and a privacy sentence that stays true |
| 20 | **Voice** | `talk.ptt.*` and `talk.speak` on nodes; `tts` tool (`docs/platforms/windows.md`, `docs/tools/index.md`). | Push-to-talk with an editable transcript before anything runs (`backend/claw/speech/`, sherpa-onnx). *Blocked* — never tested with a real microphone. | Comparable in shape; ours is unverified and has no TTS. | P3 | M | A person, a microphone, and consented Nigerian-English recordings |

---

## One correction worth naming

My first draft of row 4 said S-CLAW "offers all 76 tools on every planning
call". That was an assumption, and measuring it proved it wrong: the planner is
sent no schemas at all, and the executor already filters by capability. The row
now carries the measured numbers instead, and the remaining gap is three
specific defects rather than the headline failure I expected to find. The same
measurement is reproducible:

```
backend/.venv/bin/python -c "from claw.agent.executor import tool_catalogue; \
  from claw.tools.registry import build_registry as b; \
  print(len(tool_catalogue(b(), None)), len(tool_catalogue(b(), {'files'})))"
```

## What I would do with this

**Do not** rebuild S-CLAW as a chat-channel gateway. Rows 2, 11, 13 and 18 are
places where the two products deliberately disagree, and OpenClaw's own
`SECURITY.md` and sandboxing pages exist precisely because a daemon that takes
instructions from twenty chat networks has a threat model S-CLAW does not have.

Three gaps are worth closing because they make S-CLAW **more reliable at what it
already does**, not more like OpenClaw:

1. **Tool-catalogue pressure (row 4, P1, ~1–2 days).** Not the gap I expected —
   measuring beat assuming here. The planner is already cheap and the executor
   already filters. What is left is three concrete defects worth ~4–6k tokens
   on a 4B brain: split `Capability.FILES` (37 of 76 tools) so an organiser
   task does not drag in spreadsheets and OCR; filter per **step** rather than
   per plan; and stop falling through to the unfiltered list when a plan is
   reasoning-only. No `tool_search` equivalent is needed until the catalogue is
   much larger. Measurable, with the numbers already in row 4 as the baseline.
2. **Event triggers (row 5, P1, ~2–4 days).** Jobs can only fire on a clock. A
   file landing in a folder, or a task finishing, cannot start work. Local file
   and lifecycle events need no open port; webhooks would, and should be
   decided separately.
3. **A credential store (row 7, P2, ~2–3 days).** Not to let the model see
   keys — to let *tools* hold them, backed by DPAPI, so the eventual mail or
   weather tool does not require pasting a key into a settings box.

Everything else is either a deliberate non-goal, blocked on infrastructure that
does not exist here, or cosmetic.

## What this report does not establish

- Nothing in OpenClaw was **run**. This is a documentation comparison against a
  pinned version, not a bake-off.
- The "no evidence found" rows (3, 15) are bounded by the pages I could fetch.
- Every S-CLAW row marked *Blocked* stays blocked: no Windows desktop, no model
  weights, no hosted service, no public web. `docs/WINDOWS_ACCEPTANCE.md` says
  how to settle each one on a real machine.
