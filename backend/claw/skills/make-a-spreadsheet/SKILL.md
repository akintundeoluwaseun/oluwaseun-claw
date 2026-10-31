---
name: make-a-spreadsheet
description: Create a spreadsheet or table of data and save it as an Excel or CSV file.
triggers: spreadsheet, excel, xlsx, table, csv
---
1. Decide the columns, e.g. ["State", "Capital"].
2. Call create_spreadsheet with rows as a list of lists, one inner list per row:
   {"file_name": "states", "columns": ["State", "Capital"], "rows": [["Lagos", "Ikeja"], ["Oyo", "Ibadan"]]}
3. Put in every row that was asked for: if the person asked for five, give five.
4. Only write facts you are sure of. Nigerian state capitals, for example:
   Lagos - Ikeja, Oyo - Ibadan, Kano - Kano, Kaduna - Kaduna, Rivers - Port Harcourt, Enugu - Enugu,
   Ondo - Akure, Ekiti - Ado-Ekiti, Ogun - Abeokuta, Osun - Osogbo, Niger - Minna, Edo - Benin City.
