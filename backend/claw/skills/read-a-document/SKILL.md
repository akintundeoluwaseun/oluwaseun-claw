---
name: read-a-document
description: Read a PDF, Word or Excel file the person names and answer a question about it, such as a total, a date or a name.
triggers: invoice, receipt, statement, pdf, total, amount due
---
1. Call read_document_pages with the file's path, for example {"path": "Documents/invoice.pdf", "first_page": 1}.
   A bare name like "Documents/invoice.pdf" is fine; Claw finds the folder.
2. If the answer is not on the pages you read, read the next pages.
3. Answer with the exact figure as written in the document, and the page it is on.
4. Never guess a number you did not see in the document.
