# Real trial

## Read invoice.pdf in my Documents folder and tell me the total amount due.
- status: **completed** (277.2 s)
- step `find_files` → rejected: Invalid arguments for find_files: file_name: Extra inputs are not permitted
- step `find_files` → verified: Found 1 file(s) under C:\Users\runneradmin\Documents.
- step `read_document_pages` → verified: Read pages 1–1 of invoice.pdf (1 pages).
- answer: The total amount due on the invoice is $580.50.
- event rejected: {"step": 1, "reason": "Invalid arguments for find_files: file_name: Extra inputs are not permitted"}
