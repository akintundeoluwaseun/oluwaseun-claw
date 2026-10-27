# Capability matrix

Dated 27 October 2026. One line per capability, with the verdict and what it
rests on.

**PASS** — verified by a test appropriate to the claim.
**MOCK-ONLY** — verified against a labelled test double; real-world behaviour unproven.
**BLOCKED** — needs a model, credential, network, Windows desktop, device or service that is not available here.
**FAIL** — attempted and did not meet its expected result.
**NOT IMPLEMENTED** — does not exist.

## Files and documents

| Capability | Verdict | Evidence |
|---|---|---|
| Create / read / write / rename / move / copy files | PASS | run against a real disk and re-checked afterwards; `test_text_tools.py`, 42-task record |
| Create folders, refuse paths that escape | PASS | `test_text_tools.py`, plus the safety suite in the task record |
| Find files by name, type and age | PASS | `find_files(not_modified_in_days=…)` run against files with set mtimes |
| Count, search, combine, sort, compare text | PASS | exact answers checked against Python's own counts |
| Extract e-mail addresses | PASS | case duplicates folded, bare domains not matched |
| CSV: create, arithmetic over a column, list → table | PASS | all ten rows checked against price × quantity |
| Read PDF / DOCX / XLSX | PASS | `test_documents.py`, real files |
| OCR a scanned PDF | PASS | `test_ocr.py` with real Tesseract |
| Summarise a document | BLOCKED | routes to the model; no model reachable here |

## Desktop (Windows)

| Capability | Verdict | Evidence |
|---|---|---|
| launch_app / focus_window / press_keys / type / click logic | MOCK-ONLY | 26 tests against `tests/fake_desktop.py`, including 7 failure paths added today |
| Refusing system tools, blocked key combinations, locked screen | MOCK-ONLY | same suite |
| Any of it on real Windows | BLOCKED | no Windows desktop in this container; see `docs/WINDOWS_ACCEPTANCE.md` |

## Browser and web

| Capability | Verdict | Evidence |
|---|---|---|
| Open a page, read it, tabs, downloads | PASS | real Chromium against a real local site |
| Search provider interface (DuckDuckGo / Bing / SearXNG / custom) | PASS | URL building, validation and selection tested; a real search run against a local search page |
| Evidence on every result (provider, URL, page title, time) | PASS | `test_search_records_where_the_answer_came_from` |
| Plain-language network errors | PASS | real connection refusal, no `net::` code reaches the user |
| Clean message after a failed navigation | PASS | reproduced a real failure first |
| Public web search (python.org) | BLOCKED | egress policy refuses duckduckgo, bing, google (`ERR_TUNNEL_CONNECTION_FAILED`) |
| SearXNG against a real server | BLOCKED | needs a reachable host |

## AI inference

| Capability | Verdict | Evidence |
|---|---|---|
| Provider selection (builtin / service / cloud / custom) | PASS | `test_editions.py`, `test_api.py` |
| Self-test that really generates | PASS | against the labelled fake server; distinguishes unreachable, refused key, not-configured, empty |
| Engine start / stop / crash recovery / memory refusal | BLOCKED | 7 tests skip: no `llama-server` binary here |
| Real local inference with trained weights | BLOCKED | no weights reachable; HF and GitHub release assets both refused |
| Real hosted inference | BLOCKED | no Claw service exists; no credentials configured |
| Judgment task (draft an email) | BLOCKED | needs a model |
| Tool-use loop with a real model | BLOCKED | needs a model |

## Editions

| Capability | Verdict | Evidence |
|---|---|---|
| Edition profile read, damaged profile falls back to Local | PASS | `test_editions.py` |
| Online refuses local brain and brain downloads | PASS | 409 `wrong_edition`, saved setting unchanged |
| Local refuses a service it was not built with | PASS | same |
| Service token never exposed | PASS | checked in `/edition`, `repr`, and the settings body |
| Local runs with every non-loopback socket refused | PASS | `test_local_edition_runs_with_no_network_at_all` |
| Online reports lost connectivity honestly | PASS | real connection attempt to a dead address |
| Two installers built and measured | BLOCKED | needs the Windows runner |

## Voice

| Capability | Verdict | Evidence |
|---|---|---|
| Speech packaging, catalogue, streaming resampler | PASS | `test_speech.py`; resampler proven bit-identical to whole-file resampling |
| Push-to-talk, microphone permissions, live partials | BLOCKED | no microphone, no Windows |
| Nigerian English accuracy | NOT IMPLEMENTED | no consented recording set exists, so no number can be produced |

## Integrations

| Capability | Verdict | Evidence |
|---|---|---|
| WhatsApp read / draft / approve / send | MOCK-ONLY | `test_whatsapp.py` against a stand-in whose layout is a **guess** at the real app |
| Messaging any app by operating it (Telegram, Instagram, Slack, Teams…) | MOCK-ONLY | `test_laptop_control.py`; the rule that makes Enter count as *sending* is tested for desktop apps and for sites inside a browser |
| An approval for a send names the chat and quotes the message | PASS | `test_laptop_control.py`; the sentence is produced by the backend, not the card |
| Calendar — read, create, cancel, find free time | PASS | `test_calendar.py`; a hand-written RFC 5545 subset, `.ics` on disk, read back after every write |
| Calendar reminders (VALARM in the file, notification on this computer) | PASS (logic) / BLOCKED (the notification itself) | `test_calendar_reminders.py` (34) and `desktop/tests/reminders.test.js`; no Windows here, so no notification has ever appeared on a screen |
| Recurring events (RRULE) | NOT IMPLEMENTED | kept in the file untouched, flagged `unsupported`, and skipped by reminders rather than guessed at |
| Mail — compose a draft in Gmail, Outlook or the default mail program | PASS (opens a draft) / NOT IMPLEMENTED (sending, reading, searching) | `test_laptop_control.py`; there is no IMAP client and no stored mailbox password, and `sent` is always `false` |
| Daily briefing — today's agenda, unfinished work, and what it cannot see | PASS (logic) / BLOCKED (the notification) | `test_brief.py` (12) and `desktop/tests/reminders.test.js`; fires once a day, only while the app runs |
| Scheduled jobs (while the app runs; never 24/7) | PASS (logic) / BLOCKED (unattended run on Windows) | `test_jobs.py` (29); the first three tests are the restraint: an unattended job cannot ask, cannot do destructive work, and cannot widen the authorised folders |
| Persistent memory — remember, recall, forget, export | PASS | `test_memory.py` (28); 16 of them are the refusal: a password, OTP, API key, private key or card number is rejected *before* the write, while phone numbers, e-mails and birthdays are kept |
| Shopping, travel, bookings | NOT IMPLEMENTED | not started |
| Video | NOT IMPLEMENTED | still undefined — see the note at the end |

## Packaging

| Capability | Verdict | Evidence |
|---|---|---|
| Frozen backend starts, voice runtime loads | PASS | smoke test on a real Windows runner (earlier builds) |
| Installer script compiles, plain and split | PASS | Inno Setup compile check in `test-windows.yml` |
| Edition correctness enforced at build time | BLOCKED | the check is written; no build has run since |
| PowerShell scripts parse | BLOCKED | no `pwsh` here; a parse check was added to the Windows workflow |

## Video

Named in the brief and never defined. It could mean reading a YouTube
transcript, recording the screen, or editing a file, and those are three
different products. Nothing is built, and nothing is claimed.

## The four things no repository can fix

1. A Windows desktop, for everything marked MOCK-ONLY above.
2. Trained model weights, for Claw Local.
3. A funded, deployed service, for Claw Online — removing the user's API key
   means someone else pays for the compute.
4. Ordinary internet, for public search and for downloading weights.
