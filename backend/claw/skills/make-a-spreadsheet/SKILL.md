---
name: make-a-spreadsheet
description: Create a spreadsheet or table of data and save it as an Excel or CSV file.
triggers: spreadsheet, excel, xlsx, table, csv
---
1. Decide the columns, e.g. ["State", "Capital"].
2. Call create_spreadsheet with rows as a list of lists, one inner list per row:
   {"file_name": "states", "columns": ["State", "Capital"], "rows": [["Lagos", "Ikeja"], ["Oyo", "Ibadan"]]}
3. Give exactly as many rows as were asked for: five means five, not more and not fewer.
4. Only write facts you are sure of. Choose the rows yourself; never paste a longer list than was asked for.
