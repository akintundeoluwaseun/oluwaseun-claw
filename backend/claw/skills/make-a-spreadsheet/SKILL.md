---
name: make-a-spreadsheet
description: Create a spreadsheet or table of data and save it as an Excel or CSV file.
triggers: spreadsheet, excel, xlsx, table, csv
---
1. Decide the columns, e.g. ["State", "Capital"].
2. Call create_spreadsheet with rows as a list of lists, one inner list per row:
   {"file_name": "states", "columns": ["State", "Capital"], "rows": [["Lagos", "Ikeja"], ["Oyo", "Ibadan"]]}
3. Give exactly as many rows as were asked for: five means five, not more and not fewer.
4. Only write facts you are sure of. For reference (pick from these, do not copy the whole list), Nigerian state capitals:
   Lagos - Ikeja, Oyo - Ibadan, Kano - Kano, Kaduna - Kaduna, Rivers - Port Harcourt, Enugu - Enugu,
   Ondo - Akure, Ekiti - Ado-Ekiti, Ogun - Abeokuta, Osun - Osogbo, Niger - Minna, Edo - Benin City.
