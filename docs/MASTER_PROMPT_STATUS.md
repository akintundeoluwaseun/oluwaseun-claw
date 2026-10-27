# Against the Master Evolution Prompt — what is built, what is not

Dated 27 October 2026. Every line here is a verdict I can point at evidence for.
`PASS` means it was run and checked here; `MOCK-ONLY` means the logic is tested
against a labelled test double and no real machine has confirmed it; `BLOCKED`
means this container cannot run the test; `NOT IMPLEMENTED` means it does not
exist and nothing pretends otherwise.

## The ten capability families

| # | Family | State | What is actually there |
|---|---|---|---|
| 1 | Auto-reply across WhatsApp, Telegram, Instagram, e-mail | MOCK-ONLY | No per-app integrations. S-CLAW operates whichever app is open; Enter counts as *sending* in messaging apps and on messaging sites in a browser, and that approval now names the chat and quotes the message. Nothing replies on its own — auto-reply, as in unattended, is **NOT IMPLEMENTED** and would need a rule engine nobody has specified. |
| 2 | Write code, deploy sites and apps | NOT IMPLEMENTED | File tools can read and write text, which is not the same thing. No workspace, no diffs, no build, no deploy. |
| 3 | Control the PC | MOCK-ONLY | Launch, focus, inspect, click, type, press keys, screenshots, OCR. 26+ tests against `tests/fake_desktop.py`. Installing software: **NOT IMPLEMENTED** by choice. |
| 4 | Calendars, meetings, invitations | PASS, except invitations | Create, list, cancel, find free time, and now reminders written as real `VALARM`s. Invitations (ATTENDEE, sending an `.ics`) are **NOT IMPLEMENTED**: creating an event and delivering an invitation are different things and are not conflated. |
| 5 | Read and summarise e-mail, PDFs, YouTube | Part PASS, part NOT IMPLEMENTED | PDFs and documents: real extraction, OCR, page references, tested. E-mail reading and YouTube: nothing. `compose_mail` opens a draft and never sends. |
| 6 | Daily briefings | PASS (logic) / BLOCKED (on screen) | `daily_brief` tool and `GET /brief`: today's calendar in order, what is next, and work from the last three days that did not finish. Every briefing names what it cannot see — there is no mailbox and no message history. Delivered as one notification at a time you choose in Settings, **only while S-CLAW is running**: there is no service behind it, and the app does not pretend otherwise. |
| 7 | Shop, book, research flights | NOT IMPLEMENTED | Not started. |
| 8 | Persistent memory of people, projects, decisions | PASS | `remember`, `recall`, `forget_this`, a `memories` table (schema v3), and a Memory panel in Settings that lists everything with its date and a Remove link, plus Export and Forget everything. Five kinds only — preference, project, contact, decision, fact — because "other" becomes a bin. **A secret is refused before it is written**, not filtered when shown: passwords, codes, API keys, private keys and card numbers (Luhn-checked, so a phone number is not mistaken for one). Only what the person said is stored, never a conclusion drawn about them. |
| 9 | Scheduled jobs — **not** 24/7 | PASS (logic) / BLOCKED (a real unattended run on Windows) | Jobs with a name, a schedule (`every N minutes` or `daily at HH:MM`), next run, last result and their own history; pause, resume, run-now, remove. Two rules make it safe to leave running: **nobody is watching, so nothing may ask** — a job runs under `PermissionPolicy.unattended()`, where every "ask" becomes "no" and destructive work is refused whatever the settings say — and **a person at the keyboard comes first**: a job that would collide with a task you started is recorded as *skipped*, which does not consume its turn. Cron syntax is deliberately absent: a line nobody can read is a schedule nobody can check. **There is no 24/7**, and the panel says so in bold: a computer that is off does nothing. |
| 10 | Proactive notifications | PASS (logic) / BLOCKED (on screen) | Two now exist: *something needs you* (password, code, CAPTCHA) and *an event is about to start*. Both tested on both sides; neither has ever appeared on a real Windows screen from this container. |

## The sections with specific requirements

| Section | State | Note |
|---|---|---|
| B — two editions, shared codebase | PASS (client) / BLOCKED (service) | `resources/edition.json`, `claw/edition.py`, packaging profiles, 409 on a wrong-edition change. **The hosted service does not exist**, so Claw Online has never answered. |
| C — model research, provider interface | PASS (research + interface) / BLOCKED (inference) | Three providers; self-test generates real text and shows elapsed time. **No real model has ever answered here** — weights hosts and provider endpoints are both blocked. |
| D — agent loop and safety | PASS | Typed schemas, strict validation, approvals with a destructive floor settings cannot lower, untrusted-content flagging, emergency stop, audit trail. |
| G — open-source evaluation, ≥40 projects | PASS | `docs/OPEN_SOURCE_EVALUATION.md`, 39 projects checked against primary sources, licences corrected by hand where my first reading was wrong. |
| F — OpenClaw comparison | NOT IMPLEMENTED | `github.com/openclaw/openclaw` and `docs.openclaw.ai` are both unreachable from this container (all public web is blocked). A comparison written without reading them would be invention. |
| H — UI redesign | PASS | Whole shell redesigned: tokens, two-pane Settings, motion states, quick bar that drags, About panel. |
| I — performance and packaging | Part PASS / BLOCKED | Cold start, idle memory and tool latency measured on Linux (`docs/PERFORMANCE.md`). **Installer sizes are unmeasured** because no installer has been built, so nothing calls Online "lightweight". |
| J — test matrix | See `docs/CAPABILITY_MATRIX.md` | Every Windows, real-model, public-web and microphone row is BLOCKED with reproducible steps in `docs/WINDOWS_ACCEPTANCE.md`. |

## What I would build next, in order

Of the ten families, what is left is the large and the undefined:

1. **E-mail reading** (part of family 5) — the compose half is done. Reading
   needs OAuth, token storage and refresh, and live tests against a real
   mailbox; until all three exist, claiming Gmail support would be a lie.
2. **Code and deployment** (family 2) — a workspace, diffs, builds, previews,
   and a deploy step that is its own approved action.
3. **Shopping and travel** (family 7) — only through official provider APIs,
   with price timestamps and no payment details in memory.

Video is still a word rather than a scope: a YouTube transcript, a screen
recording and a video editor are three different products, and nothing is
built or claimed for any of them.
