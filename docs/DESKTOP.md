# Desktop control

Claw operates other Windows apps through **Windows UI Automation** (the
accessibility system screen readers use), via pywinauto. It reads a window's
buttons, fields and menus as a numbered list, acts on them by number, and then
checks the screen again to confirm something actually changed.

## What Claw can do
| Action | How it works | Asks first by default? |
|---|---|---|
| List / switch windows | UI Automation | No |
| Open an app | Start-menu shortcut or built-in app (Notepad, Paint, Calculator, File Explorer) | Yes |
| Look at a window | Numbered list of controls | No |
| Click a control | Invoke / toggle / select pattern; mouse click only if the control has none | Yes. Buttons named Send, Delete, Buy, Pay, Submit, Post… always ask |
| Type into a field | Value pattern, read back to check | Yes |
| Press a shortcut | Allowed keys only (no Windows key, Ctrl+Alt+Delete, Alt+Tab) | Yes |
| Screenshot / look at the screen | mss; the brain describes the image (Online brain, or the offline seeing model) | No |
| Click at a position | Only after a screenshot, only on-screen coordinates | Yes |
| Read files in authorized folders | list, read text files, find files | No |

**Stop at any time:** press **Ctrl + Alt + X**, use the quick bar's stop button, or the tray menu.

## Not supported (yet)
- **Locked screen.** Windows blocks input when locked, so desktop steps fail with a clear message. Browser steps keep working. "Keep the computer awake" in Settings stops sleep, not the lock screen.
- **Apps running as administrator**, UAC prompts, the sign-in screen, and other secure desktops.
- **Games and full-screen DirectX/OpenGL apps** that expose no controls.
- **Some Electron/Chromium apps** expose only part of their interface to UI Automation; `describe_screen` + `click_at` is the fallback.
- **System tools** (Command Prompt, PowerShell, Registry Editor, Windows Security, Control Panel…) are deliberately refused.
- Opening Office documents or reading PDFs/Word files directly (Batch 4).
- Using the computer at the same time as Claw: moving the mouse or typing can interfere with its steps.

## Windows verification checklist (not yet run)
The UI Automation driver was written against pywinauto 0.6.9's source and
syntax-checked, but **has not run on Windows**. Before relying on it:

1. `scripts\setup.ps1`, then `scripts\check.ps1` — all backend tests should pass.
2. Start Claw, connect a brain, add a folder.
3. Task: *"Open Notepad, type 'hello from Claw', and save it as test.txt in my folder."*
   Expected timeline: Opened an app → Looked at a window → Typed in an app (checked) →
   Pressed keys (Save As appears) → Typed the file name → Clicked Save (Save As closes).
4. Confirm `test.txt` exists with that text.
5. Task: *"Look at the screen and tell me what's open."* (Online brain) — a description appears.
6. During any desktop step press **Ctrl+Alt+X** — the task stops.
7. Lock the screen during a desktop task — the step fails with the "Windows is locked" message.

Record the results in `TEST_RESULTS.md`.
