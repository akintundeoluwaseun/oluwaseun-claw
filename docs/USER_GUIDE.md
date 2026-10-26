# Oluwaseun Claw — User guide

Claw is a free assistant that does jobs on your Windows computer for you. You type what you
want in plain English, and Claw works through it step by step in the browser, in your apps and
in your files. It always asks before anything important.

**Free, with nothing to add.** No payment, no account, no key. Claw's brain runs on your own
computer, so your tasks and documents stay with you.

---

## 1. Install
1. Download **Oluwaseun Claw Standard** (most laptops) or **Pro** (16 GB of memory or more).
   For Pro, keep `Setup.exe` and its `.bin` files together in one folder.
2. Double-click `Setup.exe` and follow the steps. No administrator rights are needed.
3. Claw opens when installation finishes. Its brain is already inside, so you can start
   straight away.

Windows may warn that the app is from an unknown publisher (Claw is not code-signed yet).
Click **More info → Run anyway** only if you downloaded Claw from its official page.

## 2. First steps
1. Open **Settings → Folders Claw may use** and add the folder where Claw should save its work,
   for example `Documents\Claw`. Claw can't save anything until you add one.
2. Close Settings and type a task in the big box, for example:
   *"Search for free motion graphics templates, compare them, and save the useful links."*
3. Press **Start task**, or **Enter**.

## 3. Watching a task
- Each step appears in a timeline: **Done**, **Done, not checked**, **Failed** or **Not allowed**.
- When Claw needs your OK, a card shows exactly what it wants to do. Choose **Allow this step**
  or **Don't allow**. Declining stops the task safely.
- **Stop** ends the task at any time. **Ctrl+Alt+X** stops it from anywhere, even while Claw is
  using your mouse and keyboard.
- At the end, the **Outcome** card shows what was done, what failed, the files Claw made
  (with **Open** and **Show in folder**) and any warnings. Claw's own summary is shown
  separately, so you can check it against the steps.
- **Plan only** shows the steps Claw would take, without doing anything.

## 4. Working in the background
- **Quick bar:** a small bar at the top of the screen. Click it, or press **Ctrl+Shift+Space**
  anywhere, type a task and press Enter. You can then leave the computer.
- **Tray icon:** closing the window keeps Claw running. Right-click the tray icon to open Claw,
  start or stop a task, or quit.
- **Notifications** tell you when a task finishes or needs your OK.
- Settings can keep the computer awake while a task runs, and can start Claw with Windows.

## 5. Documents (including scanned PDFs)
1. Click **Documents** in the left sidebar, then **Open a document**. You can open PDF, Word,
   Excel or text files.
2. Claw reads each page. Scanned pages are read with OCR (text recognition) on your computer;
   nothing is uploaded.
3. Every page shows where its text came from:
   - *From the file's text* — exact.
   - *Read from the scan · 95% sure* — recognised from the image. *Turned 90°* means the page
     was sideways.
   - Pages marked as an **unclear scan** or **could not be read** should be checked by eye.
4. Use **Search this document** to find words; click a result to jump to its page.
5. Use **Ask Claw** to summarise the document or ask a question about it. Answers mention page
   numbers.
6. **Save searchable copy** makes a new PDF of a scan whose text you can select and search.
   It never replaces an existing file.

Searching and reading work even when the brain is busy or missing. Only asking needs the brain.
Password-protected PDFs can't be read: save an unprotected copy first.

## 6. Claw's brain (Settings → Claw's brain)
- The brain that came with Claw is ready to use; you don't need to change anything.
- **Download** gets the other free brain (Standard or Pro). The size is shown first, you can
  cancel at any time, and a stopped download continues where it left off. Claw checks the
  file's licence and checksum before using it.
- **Use this** switches between brains. **Remove** deletes a downloaded brain (you're asked first).
- **Use a GGUF file I have** lets you use your own model file (choose its `mmproj` vision file
  too, if it has one). Claw never deletes your file.
- **Restart the brain** helps if it seems stuck.
- If Claw says there isn't enough memory, close some apps or use the Standard brain.

## 7. What Claw may do (Settings → What Claw may do without asking)
| Kind of action | Default | Choices |
|---|---|---|
| Looking and reading | Go ahead | Go ahead / Ask me / Never |
| Saving or editing files | Ask me | Go ahead / Ask me / Never |
| Changing things online | Ask me | Go ahead / Ask me / Never |
| Deleting, sending, buying | Ask me | Ask me / Never (it can never go ahead alone) |
| Reading your browser history | Ask me | Ask me / Never |

For tasks that should finish while you're away, set "Saving or editing files" to **Go ahead**.

If something Claw reads (a web page, a file or a document) tries to give it orders, Claw
ignores it, shows a warning, and asks before every change for the rest of that task.

## 8. Privacy
- The brain, OCR and your task history stay on this computer.
- Claw uses its own browser profile. It never sees your passwords or signed-in accounts.
- Data folder: `%APPDATA%\OluwaseunClaw` (settings, history, downloaded brains, logs).
  Uninstalling Claw keeps this folder; delete it yourself to remove everything.

## 9. If something goes wrong
| You see | What to do |
|---|---|
| "Not enough free memory for this brain" | Close some apps, or switch to the Standard brain. |
| "The brain did not finish loading" | This computer is too slow for that brain; use Standard. |
| "Claw's AI engine is missing" | Reinstall Claw. |
| "The OCR engine … is not installed" / "data files are incomplete" | Reinstall Claw. |
| A page says "unclear scan" | Check that page yourself; the text may be wrong. |
| "Windows is locked" | Steps in other apps need an unlocked screen. Browser steps still run. |
| "Microsoft Edge was not found" | Settings → Browser → choose Chrome. |
| "Step limit reached" | Raise "Most steps per task" in Settings, or split the task. |
| "Agent stopped" in the title bar | Click it to restart. Claw also restarts itself after a crash. |

## 10. Keyboard shortcuts
| Keys | Does |
|---|---|
| Ctrl+Shift+Space | Open the quick bar (anywhere in Windows) |
| Ctrl+Alt+X | Stop the current task (anywhere) |
| Ctrl+N | New task (in Claw's window) |
| Enter | Start the task |
