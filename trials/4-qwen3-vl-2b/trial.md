# Real trial

## Open Notepad, type 'S-CLAW desktop-control test', save it as claw-test.txt in Documents, reopen it, and verify the exact contents.
- status: **completed** (87.6 s)
- answer: (The model finished without a summary.)

## Search the web for free open-source video editing software, open a good result, and save its title and URL.
- status: **completed** (147.8 s)
- step `web_search` → verified: Found 10 result(s) for 'free open-source video editing software' on DuckDuckGo (2344 ms).
- step `open_search_result` → verified: Opened result 1: OpenShot Video Editor | Free, Open, and Award-Winning Video Editor for Linux, Mac, and Windows!
- answer: I have opened the first search result for OpenShot Video Editor, which is a free, open-source video editor for Linux, Mac, and Windows. I will now save the title and URL as requested.

## Read invoice.pdf in my Documents folder and tell me the total amount due.
- status: **failed** (122.7 s)
- error: The model server at http://127.0.0.1:51113 did not answer in time.
- event failed: {"message": "The model server at http://127.0.0.1:51113 did not answer in time.", "hint": "Try a smaller model or raise the timeout in Settings."}

## Find all PDF files in my Documents folder.
- status: **completed** (126.5 s)
- step `find_files` → failed: Access to 'Documents' is not allowed: it is outside the folders you authorized
- answer: Access to the 'Documents' folder is not allowed because it is not authorized. Please check your authorized folders and ensure the 'Documents' folder is included in the list of authorized folders. If it is, try again. If not, you may need to authorize it first.
- event failed: {"step": 1, "tool": "find_files", "detail": "Access to 'Documents' is not allowed: it is outside the folders you authorized"}

## What windows are open right now?
- status: **completed** (168.1 s)
- step `list_windows` → verified: 5 window(s) open.
- answer: There are 5 windows open on the system. They are:
1. Taskbar (explorer.exe)
2. OpenShot Video Editor
3. Python script running in Windows Terminal
4. Program Manager (explorer.exe)
5. Microsoft Edge (msedge.exe)

## Make a promotional flyer for my software TechDesk and save it in Documents.
- status: **failed** (169.5 s)
- error: The model server at http://127.0.0.1:51113 did not answer in time.
- event failed: {"message": "The model server at http://127.0.0.1:51113 did not answer in time.", "hint": "Try a smaller model or raise the timeout in Settings."}

## Copy sales.csv from Documents into a new folder called Backup.
- status: **completed** (190.1 s)
- step `create_folder` → failed: Access to 'Documents' is not allowed: it is outside the folders you authorized
- answer: I cannot create the 'Backup' folder in the Documents directory because it is outside the authorized folders. I need to check the authorized folders first and ensure I have the right permissions to create a folder in the Documents directory.
- event failed: {"step": 1, "tool": "create_folder", "detail": "Access to 'Documents' is not allowed: it is outside the folders you authorized"}

## Create a spreadsheet of five Nigerian states and their capitals and save it in Documents.
- status: **failed** (161.1 s)
- error: The model server at http://127.0.0.1:51113 did not answer in time.
- event failed: {"message": "The model server at http://127.0.0.1:51113 did not answer in time.", "hint": "Try a smaller model or raise the timeout in Settings."}

## Open WhatsApp and tell me which chats have unread messages.
- status: **completed** (73.4 s)
- step `check_whatsapp` → failed: WhatsApp didn't open within 20 seconds.
- answer: WhatsApp did not open within the expected time, so I was unable to check for unread messages.
- event failed: {"step": 1, "tool": "check_whatsapp", "detail": "WhatsApp didn't open within 20 seconds."}

## What is on my calendar today?
- status: **completed** (124.9 s)
- step `list_events` → verified: There are no calendars on this computer yet.
- answer: There are no calendars on this computer yet.
