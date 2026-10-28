# Windows acceptance tests

Everything in this file needs a real Windows 10/11 desktop with a logged-in,
unlocked session. None of it can be run in the Linux build container, and none
of it is claimed to pass. The automated desktop tests that *do* pass run against
`tests/fake_desktop.py`, a labelled test double: they prove Claw's logic, not
Windows' behaviour.

## Before you start

```powershell
git clone <repo> ; cd s-claw
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -SkipOcr -Chromium
cd backend
.\.venv\Scripts\python.exe -m pytest -q          # the whole suite, on Windows
```

Record the machine: Windows build, RAM, CPU, GPU, screen resolution and scaling.
UI Automation behaves differently at 125% and 150% scaling, so the scaling
matters.

## A. Desktop control (Priority 2)

Install Claw, open it, and give it one instruction at a time, approving each
step. For every row, write down what happened, what Claw's own summary said, and
whether it claimed `verified`.

| # | Say to Claw | Passes when |
|---|---|---|
| A1 | `Open Notepad` | a Notepad window appears; summary names the window title |
| A2 | `Open Calculator and work out 245 x 36` | Calculator shows **8820**; Claw reports 8820 and did not invent it |
| A3 | `Open File Explorer at my Documents folder` | Explorer opens at Documents |
| A4 | `Open <a picture>.jpg in the default image viewer` | the picture opens in whatever Windows uses |
| A5 | `Switch to Notepad, then switch back` | focus moves both ways; Claw reports `verified` only when it really did |
| A6 | `Open Windows Settings at the Bluetooth page` | Settings opens on Bluetooth |
| A7 | `Create a file in Documents containing exactly "Hello from S-CLAW", then reopen it and tell me what it says` | the file exists with exactly that text, and Claw read it back |

### The failure paths, which matter more than the happy ones

| # | Do this | Passes when |
|---|---|---|
| A8 | Ask Claw to open an app that is not installed | it says no app matched, and does not pretend |
| A9 | While Claw is launching an app, click another window to steal focus | `focus_window` reports it could not verify, rather than claiming success |
| A10 | Ask Claw to press Ctrl+S in Notepad with an unsaved file | it reports the Save As dialog opened and stops for it |
| A11 | Ask it to open `Command Prompt` | refused before anything launches ("system tools") |
| A12 | Lock the screen, then ask for a desktop step | a clear "Windows is locked" message, not a crash |
| A13 | Ask it to press a key combination like Alt+Tab | refused by validation |

A1–A13 correspond to the logic covered by `tests/test_desktop.py` (26 tests,
passing against the double). If a row here fails on real Windows while the
matching test passes, the double is wrong and should be corrected.

### An independent check (optional)

`microsoft/WinAppDriver` (MIT) can drive Notepad and Calculator through a second
implementation. Agreement between Claw and WinAppDriver is worth more than Claw
agreeing with itself. Install it on the test machine only; it is never shipped.

## B. Real local inference (Priority 1)

```powershell
# the engine tests that are skipped in the container become real here
.\.venv\Scripts\python.exe -m pytest tests\test_runtime.py -q -rs
```

Seven tests change from skipped to run once `llama-server.exe` exists. They use
`tests/make_tiny_gguf.py` — **random weights**. They prove the engine starts,
loads a model, honours its API key, restarts after a crash and refuses a model
that will not fit. They prove nothing about answer quality.

Then the real thing, in Claw:

1. Settings → Claw's brain → download the recommended brain. Note the download
   size, the time, and the memory it uses once loaded.
2. **Judgment:** `Write a short professional email asking a supplier for a quote.`
   Record the actual text it produced.
3. **Tool use:** `How many words are in <file>.txt?` The model must request
   `count_text`; Claw validates and runs it; the answer must match
   `(Get-Content file.txt -Raw).Split().Count`.
4. **Self-test:** Settings → Test the connection. It must quote the model's own
   reply and a time. If it says "Ready" without quoting anything, that is a bug.
5. **Recovery:** kill `llama-server.exe` in Task Manager mid-task. Claw should
   report the engine died and restart it, not hang.
6. **Offline:** turn off Wi-Fi and repeat 2 and 3. Claw Local must work
   unchanged. If anything fails, it is not offline-capable.

## C. Public web search (Priority 3)

On a machine with ordinary internet:

1. `Search the web for the official Python website and open the first result.`
   The first result should be python.org. Record the provider, the result URL and
   the time from `web_search`'s own evidence fields.
2. Repeat with Settings → Search engine → Bing.
3. If you run a SearXNG server, point Claw at it and repeat. This is the check
   that the provider interface is real rather than theoretical.
4. Turn off the network mid-search. The message must name the connection, not
   print a `net::ERR_` code.

## D. Voice (Priority 5)

Needs a real microphone and real recordings. Nothing about Nigerian English can
be claimed before this exists.

1. Build a set of **at least 50 utterances** of things people actually say to
   Claw ("open my documents folder", "summarise this PDF"), spoken by Nigerian
   English speakers who have consented to the recording being used for testing.
2. Write the exact intended text for each.
3. Run them through Claw's transcription and compute word error rate. Record the
   figure, the model used, and the hardware.
4. Only then compare against `faster-whisper` or `whisper.cpp` on the same set.
   Comparing them without the set would prove nothing.
5. Check push-to-talk key hold and release, an unplugged microphone, silence,
   background noise, and cancelling mid-sentence.

## E. Packaging (two editions)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -Edition Local -Brain Standard -SliceMB 1900
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -Edition Online -ServiceUrl https://<your service>/v1
```

The script prints the measured size of each. Then, for each installed edition:

- Claw Online must contain no `llama-server.exe` and no `.gguf`, and Settings
  must not offer a brain download.
- Claw Local must contain both, and must work with the network switched off.
- Neither may contain a service token in any file a user can read.

The GitHub workflow checks the first two automatically and fails the build if
they are wrong.

## Reporting

For each row: PASS, FAIL, or BLOCKED, with what was observed. A row is not a PASS
because the code looks right. Send the results back with the Windows build
number and the hardware, and they go into a dated report beside
`docs/TEST_RUN_2026-10-27.md`.

## Calendar reminders (added 27 Oct)

Logic is tested on both sides; **no notification has ever appeared on a screen**,
because this container has no Windows desktop. To confirm it on a real machine:

1. Open S-CLAW and ask it: `remind me about the site visit in 12 minutes`.
   Expect the reply to say you will be reminded 10 minutes before.
2. Open `%APPDATA%\S-CLAW\calendars\My calendar.ics` in Notepad. Expect a
   `BEGIN:VALARM` block with `TRIGGER:-PT10M` inside the event.
3. Import that same `.ics` into Outlook or Google Calendar. Expect the reminder
   to come across with it — that is the point of writing a real VALARM.
4. Wait. Within a minute of the two-minute mark, expect one Windows notification
   titled `Site visit — in 2 minutes`. Click it: S-CLAW should come to the front.
5. Wait another two minutes. Expect **no second notification** for the same event.
6. Close S-CLAW, set the system clock forward a day, reopen it. Expect **no
   notification at all** for that event — it is retired, not queued.
7. Check `%APPDATA%\S-CLAW\calendars\reminders.json` holds the event's id.

A failure at step 4 means the poll or the notification is broken; at step 5 the
"shown once" record; at step 6 the grace window.

## Scheduled jobs (added 27 Oct)

The scheduling arithmetic and the permission restraint are tested; **no job has
ever run unattended on a real machine**. On Windows:

1. Settings → Automations → add a job: name `Site check`, task
   `check whether example.com is up`, every 5 minutes. Expect it listed with
   "every 5 minutes · next …".
2. Leave S-CLAW open and do nothing for six minutes. Expect the job to run on
   its own, and its line to read `Last: ran … ` with what it found.
3. Add a second job whose task is something destructive — `delete the files in
   my Downloads folder`. Expect it to stop on its own with
   **"It needed your approval, and nobody was there to give it."** and for the
   files to be untouched. This is the test that matters most.
4. Start a long task of your own, and while it runs, wait for a job to come due.
   Expect the job's line to read `Last: was skipped — S-CLAW was busy with
   something else.`, and expect it to run shortly after your task finishes
   (a skip must not consume its turn).
5. Pause the job. Expect "Paused" and no next run. Resume it.
6. Close S-CLAW for twenty minutes, then reopen it. Expect **one** run, not four.
7. Remove the job. Expect it and its history to be gone.

A failure at step 3 is a stop-ship: it means an unattended job can do something
nobody approved.

## Standing reply (added 27 Oct)

Draft-only; **S-CLAW cannot send a WhatsApp message**, so nothing here should
ever produce one. Use a **test account**, not your own, and a second phone you
control as the sender.

1. Open WhatsApp Desktop, linked. Settings → Messages → set "Checking WhatsApp
   in tasks" to Go ahead and a background interval.
2. Under **Standing reply**, type a reply, choose 30 minutes, press Start.
   Expect the amber box: "Replying for you — 30 minutes left", and the window
   title under it.
3. From the other phone, message the test account. Wait for a background check.
   Expect one prepared reply for that chat, with "1 unread message(s)" and a
   working Copy button. Expect **no message to be sent**.
4. Message again from the same phone. Expect **no second draft** for that chat.
5. Have someone message a **group** the test account is in. Expect **no draft**.
6. Press **Stop now**. Message again. Expect no draft at all.
7. Start a 30-minute window, close S-CLAW, wait for it to expire, reopen.
   Expect the panel to show no standing reply and produce no drafts.

Step 5 is the one that matters most: a group reply from an automatic rule is the
most embarrassing failure this feature can have.
