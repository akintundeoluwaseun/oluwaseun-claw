# S-CLAW

An all-in-one AI agent for Windows 10 and 11. You type what you want done in
plain English; S-CLAW plans it, carries it out step by step on your own
computer, and checks each step actually worked. Consequential steps need your
permission, and the approval tells you what it would really do — not which key
it would press.

Made by Oluwaseun · MIT.

## Two editions, one codebase

| | **Claw Local** | **Claw Online** |
|---|---|---|
| Where it thinks | on your computer (llama.cpp + a Qwen3-VL brain) | on a Claw-hosted service |
| Needs the internet | no, after setup | yes |
| Needs your own API key | no | no |
| Installer | large (the brain is bundled or downloaded once) | small |

Both share the same tools, approvals, verification and interface. The edition is
decided at build time (`resources/edition.json`); the app never switches
silently, and refuses a setting the build cannot honour.

**The hosted service does not exist yet.** The client that talks to it is
written and tested; nothing has ever answered it. See `docs/EDITIONS.md`.

## What it can do

- **Operate the computer** — open apps, switch windows, read what is on screen
  through UI Automation, click, type. This is why there is no "WhatsApp
  integration" and no "Telegram integration": the apps are already on the
  computer, so S-CLAW uses them the way you would. Pressing Enter in a chat
  needs your approval, and the approval names the chat and quotes the message.
- **Work in a browser** — search, read pages, follow links, fill forms, download
  files, handle the failures (network, CAPTCHA, login walls) honestly.
- **Documents** — PDFs including scanned ones (OCR), Word, Excel, text; it says
  which text came from a scan and how sure it is.
- **Calendar** — create, list, cancel, find free time, stored as `.ics` that
  Outlook, Google and CalDAV can read. Reminders are real `VALARM`s, and S-CLAW
  raises them on this computer too.
- **A morning briefing** — today's agenda and anything that did not finish,
  once a day, always saying what it cannot see.
- **Memory** — what you tell it about your preferences, projects, contacts and
  decisions. Never a password, a code, a key or a card number: those are
  refused as you say them, not hidden afterwards.
- **Scheduled jobs** — while S-CLAW is open. Not 24/7, and it says so.
- **Voice** — push-to-talk, with the transcript shown before anything happens.

`docs/CAPABILITY_MATRIX.md` gives every capability a verdict — PASS,
MOCK-ONLY, BLOCKED or NOT IMPLEMENTED — with the evidence for it.
`docs/MASTER_PROMPT_STATUS.md` does the same against the original brief.

## Honest status (v0.5.0)

Everything above is tested, but this repository is built and tested on Linux.
**It has never run on Windows**, no real model has ever answered here (the
weight hosts are unreachable from the build container), and there is no public
internet. Those four gaps are listed, with reproducible steps, in
`docs/WINDOWS_ACCEPTANCE.md` and `docs/KNOWN_ISSUES.md`. Nothing in this
repository claims a mock pass as a real one.

## Quick start (Windows 10/11, developers)

1. Install Python 3.12+ and Node.js 22.
2. `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`
   (also fetches the llama.cpp engine and installs Tesseract OCR)
3. `powershell -ExecutionPolicy Bypass -File scripts\start.ps1`
4. In the app, download a brain once (Settings → Claw's brain) — Local only.
5. Installers:
   `scripts\build-release.ps1 -Edition Local -Brain Standard`
   `scripts\build-release.ps1 -Edition Online -ServiceUrl https://…`

User guide: `docs/USER_GUIDE.md` · Install: `docs/INSTALL.md` ·
Developers: `docs/DEVELOPER_GUIDE.md` · How it works: `docs/HOW_IT_WORKS.md` ·
Editions: `docs/EDITIONS.md` · Security: `docs/SECURITY.md` ·
Status: `PROJECT_STATUS.md`

## Layout

```
backend/   Python agent runtime (FastAPI, Pydantic, SQLite): tools, planner,
           executor, calendar, memory, jobs, OCR pipeline, llama.cpp manager
desktop/   Electron app: main process, quick bar, renderer
docs/      Guides, capability matrix, acceptance tests, evaluations
packaging/ Inno Setup installer script
scripts/   setup / start / check / build-release / screenshots / benchmark
```

## License

MIT — © 2026 Akintunde Oluwaseun Joshua. Third-party components:
`THIRD_PARTY_NOTICES.md`.
