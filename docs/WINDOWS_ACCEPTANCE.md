# Windows acceptance tests (run on a real Windows 10/11 PC)

These tests can't run in the Linux build workspace, so they are marked **BLOCKED** in
`TEST_RESULTS.md` until someone runs them here. Record each one with the template at the bottom.

**Before you start:** run `scripts\setup.ps1` and `scripts\start.ps1`, download the Standard brain
(Settings → Claw's brain), and add `Documents` under Settings → Folders Claw may use. Leave
"Saving or editing files" on **Ask me**, so you see each approval.

## Test A — Notepad
1. Type: *Open Notepad, type 'Oluwaseun Claw desktop-control test', save it as claw-test.txt in
   Documents, reopen it, and verify the exact contents.*
2. Approve each step as it's asked.
3. **Pass only if:**
   - the last step is "Checked a file … contents match exactly";
   - `Documents\claw-test.txt` exists;
   - opening it in Notepad shows exactly that text.
4. Also try saving into `C:\Windows\claw.txt`. Claw must report that an error-like dialog appeared
   and must not count the step as done.

## Test B — Chrome
1. In Settings → Browser, choose **Google Chrome** and tick "Show the browser window".
2. Type: *Open Chrome, search for 'free open-source video editing software', open a relevant
   result, and save the title and URL.*
3. **Pass only if:**
   - the browser visibly opened a result page;
   - the saved `.md` file in Documents has that page's real title and address.

## Test C — WhatsApp (official app)
**Preconditions:** WhatsApp Desktop from the Microsoft Store, linked to your phone, with a few unread chats.
1. Settings → Messages: leave "Checking WhatsApp in tasks" on **Ask me**.
2. Type: *Open WhatsApp and tell me which conversations have new messages.* Approve the "Private data" card.
3. **Pass only if** the chats and counts Claw lists match what WhatsApp shows, and none are invented.
4. Read one chat on your phone, have someone send you a message, then press **Settings → Check WhatsApp now**.
   Only the new chat should be marked **New**, and a Windows notification should name it.
5. Close WhatsApp, and in its place lock the screen, or unlink WhatsApp. Each case must be explained, never reported as "no unread".
6. **Sending:** *Send "Claw test" to <a test chat> on WhatsApp.* The approval card must show the exact chat and
   text; deny it once (nothing is sent), then allow it (the message appears and Claw says it confirmed it).
7. **If the counts are wrong or Claw says it "couldn't read the chat list"**, WhatsApp's accessible names differ
   from Claw's guesses. Run `look_at_window` with the title "WhatsApp" (type: *Look at the WhatsApp window and list its
   controls*) and send the output, so the patterns in `backend/claw/integrations/whatsapp.py` can be corrected.

## Phase A extras
- **Form:** *Open https://httpbin.org/forms/post and fill in the customer name "Test User" and
  pizza size Medium, but don't submit.* Pass if the fields are filled and nothing was submitted.
- **Download:** *Download the PDF linked on https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/
  into Documents.* Pass if the file is there and opens. Asking for an `.exe` must be refused.
- **Copy:** put two screenshots (Win+Shift+S → save) and one other picture in a folder, then:
  *Find all screenshots in this folder and organise copies into a new folder called Screenshots
  copies.* Pass if only the screenshots are copied and the originals are untouched.
- **Scroll and menus:** in Notepad with a long text: *Scroll down in Notepad, then use File >
  Save As.* Pass if the Save As dialog opens.
- **Emergency stop:** while a task is typing, press **Ctrl+Alt+X**. Typing must stop within
  about 1 second, and the task must show "Stopped by you".

## Record template
```
Test ID:        A / B / …
Date, PC:       Windows version, RAM, brain (Standard/Pro)
Preconditions:
Actions:        what you typed and approved
Expected:
Observed:
Result:         PASS / FAIL / BLOCKED
Evidence:       screenshot paths; %APPDATA%\OluwaseunClaw\logs\claw.log lines
Limitations:
```
