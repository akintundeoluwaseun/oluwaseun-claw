---
name: copy-files
description: Copy files from one folder into another folder, for a backup or to organise them.
triggers: copy, backup, back up, duplicate
---
1. Call copy_files: {"source_folder": "Documents", "pattern": "sales.csv", "destination_folder": "Backup"}.
   The destination folder is created if it is missing, so you do not need create_folder first.
2. Report how many files were copied and where.
