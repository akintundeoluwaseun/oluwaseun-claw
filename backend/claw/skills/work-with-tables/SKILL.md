---
name: work-with-tables
description: Combine CSV or Excel files, remove duplicate records, total a column across files, or chart a spreadsheet.
triggers: csv, spreadsheet, excel, combine, merge, duplicate, total, sum, chart, sales
---
1. Several files into one: call combine_tables with the folder name exactly as the person said it (a name like "Branch sales" is found).
2. Duplicate customers or records: call remove_duplicates on the file; it saves a clean copy and never changes the original.
3. A total across files: call table_totals with the folder (or the files). Report the number exactly as the tool gives it.
4. A chart or dashboard: call add_chart with the label column and the number column.
5. Do not build tables by hand with create_spreadsheet when these tools fit, and do not make up any number.
