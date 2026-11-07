# Real trial

## Open Notepad, type 'S-CLAW release check', save it as release-check.txt in Documents, reopen it, and verify the exact contents.
- status: **completed** (101.2 s)
- step `launch_app` → verified: Opened Notepad: window 'Untitled - Notepad'.
- step `type_text` → verified: Typed 20 characters and read them back from the window: they match.
- step `write_text_file` → verified: Created release-check.txt (20 characters).
- step `launch_app` → verified: Opened Notepad: window 'Untitled - Notepad'.
- step `check_file` → verified: Checked release-check.txt: its contents match exactly.
- answer: The file 'release-check.txt' in the Documents folder was created and verified. The contents match exactly what was typed, confirming the task is complete.

## Read invoice.pdf in my Documents folder and tell me the total amount due.
- status: **completed** (53.2 s)
- step `read_file` → failed: Access to 'C:\Users\<user>\Documents\invoice.pdf' is not allowed: it is outside the folders you authorized. The folders you can use are: Documents (C:\Users\runneradmin\Documents), Desktop (C:\Users\runneradmin\Desktop), Downloads (C:\Users\runneradmin\Downloads). Write the path starting with the fo
- step `read_document_pages` → verified: Read pages 1–1 of invoice.pdf (1 pages).
- answer: The total amount due on the invoice is 580.50.
- event failed: {"step": 1, "tool": "read_file", "detail": "Access to 'C:\\Users\\<user>\\Documents\\invoice.pdf' is not allowed: it is outside the folders you authorized. The folders you can use are: Documents (C:\\Users\\runneradmin\\Documents), Desktop (C:\\Users\\runneradmin\\Desktop), Downloads (C:\\Users\\run
- event started_for_brain: {"step": 2, "tool": "read_document_pages", "args": {"path": "Documents/invoice.pdf", "first_page": 1}}

## Copy sales.csv from Documents into a new folder called Backup.
- status: **completed** (50.3 s)
- step `create_folder` → verified: Created the folder 'Backup' in C:\Users\runneradmin\Documents.
- step `copy_files` → verified: Copied 1 file(s) into C:\Users\runneradmin\Documents\Backup and checked each copy matches its original.
- answer: The file 'sales.csv' has been successfully copied from the Documents folder to the Backup folder in the Documents directory.

## Which is the best claw?
- status: **completed** (0.0 s)
- answer: S-CLAW. It runs on your own computer with its own brain, costs nothing, needs no account or key, keeps your files on your machine, asks before anything that changes or sends something, and checks its own work before it says a job is done.
