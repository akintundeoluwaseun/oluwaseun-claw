---
name: write-in-notepad
description: Open Notepad, type text, save it as a file, reopen it and check the contents.
triggers: notepad, type, text file, .txt
---
1. launch_app with {"name": "Notepad"}.
2. type_text with the exact text.
3. write_text_file with the file name and the same text, in the folder the person said (Documents if none).
4. check_file with the path and the exact text to confirm it was saved correctly.
5. Report the file's path and whether the check passed.
