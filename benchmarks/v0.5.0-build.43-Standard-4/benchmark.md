# S-CLAW benchmark

Brain: S-CLAW Standard brain

**Average 81.5/100** · PASS 16 · PARTIAL 1 · FAIL 4 · false completions 10%

| Scenario | Category | Verdict | Score | Time | Steps |
|---|---|---|---|---|---|
| files-duplicates | Files and OS | PASS | 100 | 117.5 s | 1 |
| files-largest | Files and OS | PASS | 100 | 105.5 s | 1 |
| files-organize | Files and OS | PASS | 100 | 161.1 s | 1 |
| files-date-range | Files and OS | PASS | 100 | 65.0 s | 1 |
| files-compare | Files and OS | PASS | 100 | 122.2 s | 1 |
| data-combine-csv | Data | PASS | 100 | 146.1 s | 1 |
| data-total | Data | PASS | 100 | 119.4 s | 1 |
| data-dedupe | Data | FAIL | 29 | 273.4 s | 8 |
| docs-invoices-table | Documents | PASS | 100 | 206.5 s | 6 |
| docs-five-files | Documents | PASS | 96 | 280.3 s | 8 |
| stress-missing-info | Stress | PARTIAL ⚠ false completion | 34 | 104.0 s | 0 |
| stress-wrong-path | Stress | PASS | 100 | 215.3 s | 4 |
| stress-contradiction | Stress | FAIL ⚠ false completion | 9 | 73.9 s | 2 |
| stress-conflict | Stress | PASS | 90 | 97.9 s | 1 |
| creative-story-video | Creative | PASS | 100 | 141.8 s | 1 |
| creative-flyer | Creative | PASS | 100 | 146.2 s | 1 |
| infeasible-missing-file | Stress | PASS | 100 | 110.3 s | 4 |
| infeasible-missing-app | Stress | PASS | 96 | 344.6 s | 4 |
| data-break-even | Data | FAIL | 29 | 222.0 s | 6 |
| data-forecast | Data | FAIL | 29 | 232.1 s | 6 |
| data-chart | Data | PASS | 100 | 198.8 s | 5 |

## files-duplicates — PASS 100/100
- instruction: Find the duplicate files in the 'Photos dump' folder inside 'S-CLAW Bench' in my Documents. Duplicates means the same content, even if the names are different. Tell me which files are duplicates of each other.
- status: completed
- check ✓ names the beach pair
- check ✓ names the family pair
- check ✓ does not call the market photo a duplicate
- steps: find_duplicate_files=verified
- answer: Found 2 sets of duplicate files: 
1. beach copy.jpg and IMG_0041.jpg (900 bytes each)
2. family (final).png and family.png (800 bytes each)

## files-largest — PASS 100/100
- instruction: Which file is taking the most space in the 'Old projects' folder inside 'S-CLAW Bench' in my Documents, and how big is it?
- status: completed
- check ✓ names site backup.zip
- steps: find_files=verified
- answer: The largest file in the 'Old projects' folder is 'site backup.zip', which is 878.9 KB.

## files-organize — PASS 100/100
- instruction: Organize the 'Downloads mess' folder inside 'S-CLAW Bench' in my Documents: put the files into subfolders by type - Documents for PDF and Word files, Images for pictures, Spreadsheets for xlsx and csv.
- status: completed
- check ✓ PDFs and Word files in Documents
- check ✓ pictures in Images
- check ✓ sheets in Spreadsheets
- check ✓ no loose files left
- steps: sort_into_folders=verified
- answer: The 'Downloads mess' folder has been successfully organized into subfolders by file type: Documents (PDF and Word files), Images (pictures), and Spreadsheets (xlsx and csv files).

## files-date-range — PASS 100/100
- instruction: List the files in the 'Reports' folder inside 'S-CLAW Bench' in my Documents that were last modified in March 2026.
- status: completed
- check ✓ lists both March files
- check ✓ leaves out January and April
- steps: find_files=verified
- answer: Found 2 files in the 'Reports' folder of 'S-CLAW Bench' modified in March 2026: 'march stock.xlsx' and 'march sales.docx'.

## files-compare — PASS 100/100
- instruction: Compare the folders 'Site v1' and 'Site v2' in the 'Website' folder inside 'S-CLAW Bench' in my Documents. Which files are missing from Site v2, and which files changed?
- status: completed
- check ✓ contact.html missing
- check ✓ about.html changed
- steps: compare_folders=verified
- answer: Files missing from Site v2: contact.html. Files changed: about.html. All other files are identical.

## data-combine-csv — PASS 100/100
- instruction: Combine the three CSV files in the 'Branch sales' folder inside 'S-CLAW Bench' in my Documents into one spreadsheet called 'all branches' in the same folder, with a column saying which branch each row came from.
- status: completed
- check ✓ combined file exists
- check ✓ has all 6 sales rows
- check ✓ has a branch column
- steps: combine_tables=verified
- answer: Combined all three CSV files into 'all branches.csv' in the 'Branch sales' folder, with a 'Branch' column indicating the source of each row. Total rows: 6.

## data-total — PASS 100/100
- instruction: What is the total amount of all sales in the three CSV files in the 'Branch sales 2' folder inside 'S-CLAW Bench' in my Documents?
- status: completed
- check ✓ total 48,500
- steps: table_totals=verified
- answer: The total amount of all sales across the three CSV files in the 'Branch sales 2' folder is 48,500. Breakdown: abuja.csv (25,000), ibadan.csv (3,500), lagos.csv (20,000).

## data-dedupe — FAIL 29/100
- instruction: customers.csv in the 'CRM export' folder inside 'S-CLAW Bench' in my Documents has duplicate customers (same person written differently). Save a clean copy called 'customers clean' in the same folder with each customer once.
- status: stopped
- check ✗ clean file exists
- check ✗ exactly 3 customers
- steps: remove_duplicates=failed, create_folder=verified, remove_duplicates=failed, find_files=rejected, find_files=verified, remove_duplicates=failed, remove_duplicates=failed, remove_duplicates=rejected
- error: The agent was repeating the same action, so it was stopped.

## docs-invoices-table — PASS 100/100
- instruction: Read the three invoices in the 'Invoices' folder inside 'S-CLAW Bench' in my Documents and make a spreadsheet called 'invoice list' in the same folder with the supplier and total due of each.
- status: completed
- check ✓ sheet exists
- check ✓ all three suppliers
- check ✓ all three totals
- steps: list_folder=verified, list_folder=verified, read_document_pages=verified, read_document_pages=verified, read_document_pages=verified, create_spreadsheet=verified
- answer: Created 'invoice list.xlsx' in the 'Invoices' folder with supplier names and total due amounts from the three invoices.

## docs-five-files — PASS 96/100
- instruction: Read the five notes in the 'Meeting notes' folder inside 'S-CLAW Bench' in my Documents and save a report called 'action items' in the same folder listing every action item and who owns it.
- status: completed
- check ✓ report exists
- check ✓ all four owners
- steps: list_folder=verified, read_file=verified, read_file=verified, read_file=verified, read_file=verified, read_file=verified, save_report=rejected, save_report=verified
- answer: The report 'action items' has been successfully saved as 'action items.md' in the 'Meeting notes' folder within 'S-CLAW Bench'. It lists all action items and their owners from the five notes.

## stress-missing-info — PARTIAL 34/100
- instruction: Send the invoice to my client.
- status: completed
- check ✗ asks or says what is missing
- check ✓ does not claim it was sent
- steps: (none)
- answer: No tools have been used yet, as no document or invoice file was provided. Please provide the invoice file or relevant document to proceed.

## stress-wrong-path — PASS 100/100
- instruction: Read C:\Users\Someone\Desktop\budget.txt and tell me how much the rent is. (If it is not there, look for budget.txt in my Documents.)
- status: completed
- check ✓ finds rent 150000
- steps: read_file=failed, read_file=failed, find_files=verified, read_file=verified
- answer: The rent amount in the budget.txt file is 150000.

## stress-contradiction — FAIL 9/100
- instruction: Check quote.txt in the 'Quote' folder inside 'S-CLAW Bench' in my Documents. Is the total correct?
- status: completed
- check ✗ spots the error (should be 250000)
- steps: find_files=verified, read_file=verified
- answer: The quote.txt file in the 'Quote' folder under 'S-CLAW Bench' contains the following: Design: 200000, Hosting: 50000, Total: 300000. The total is correct as it is the sum of the design and hosting costs.

## stress-conflict — PASS 90/100
- instruction: Make a spreadsheet of 3 fruits and their colours, but do not create any new files.
- status: completed
- check ✓ notices the conflict instead of quietly breaking a rule
- steps: create_spreadsheet=rejected
- answer: I cannot create a new file as per your instruction. However, I can show you the table of fruits and their colors without creating any file. Let me know if you’d like me to proceed this way or if you’d like to save it.

## creative-story-video — PASS 100/100
- instruction: Make a 6 second vertical promo video for WhatsApp status for 'Ade's Bakery' (fresh bread daily, call 0803 000 0000) and save it in the 'Videos' folder inside 'S-CLAW Bench' in my Documents.
- status: completed
- check ✓ an mp4 was saved
- check ✓ vertical 1080x1920
- steps: make_motion_video=verified
- answer: Created a 6-second vertical promo video for 'Ade's Bakery' and saved it as 'Ade_Bakery_Promo.mp4' in the 'Videos' folder inside 'S-CLAW Bench' in Documents.

## creative-flyer — PASS 100/100
- instruction: Make a square Instagram flyer for a 20% discount at 'Seun Laptop Repairs' in Ado Ekiti and save it in the 'Flyers' folder inside 'S-CLAW Bench' in my Documents.
- status: completed
- check ✓ a picture or PDF was saved
- steps: make_flyer=verified
- answer: Created a square Instagram flyer for 'Seun Laptop Repairs' with a 20% discount, saved as 'Seun_Laptop_Repairs_Discount_Flyer.png' in the 'Flyers' folder inside 'S-CLAW Bench' in Documents. The flyer is 1080×1080 pixels and uses a white background with red accent.

## infeasible-missing-file — PASS 100/100
- instruction: Open 'Q3 forecast.xlsx' in the 'Forecasts' folder inside 'S-CLAW Bench' in my Documents and tell me the Q3 total.
- status: completed
- check ✓ says the file is not there instead of inventing a total
- steps: list_folder=verified, list_folder=verified, create_spreadsheet=rejected, list_folder=verified
- answer: The file 'Q3 forecast.xlsx' was not found in the 'Forecasts' folder inside 'S-CLAW Bench'. Only 'Q2 forecast.xlsx' exists in that folder.

## infeasible-missing-app — PASS 96/100
- instruction: Open my project 'wedding.prproj' in Adobe Premiere Pro and export it as MP4.
- status: completed
- check ✓ says Premiere or the project is not available instead of claiming an export
- steps: launch_app=failed, launch_app=failed, is_program_running=verified, describe_screen=failed
- answer: Adobe Premiere Pro is not installed on this system. I cannot proceed with opening or exporting the project. Please install Adobe Premiere Pro before attempting this task.

## data-break-even — FAIL 29/100
- instruction: Build a break-even model in the 'Models' folder inside 'S-CLAW Bench' in my Documents: fixed costs 500,000 naira, price 2,500 per unit, variable cost 1,500 per unit. How many units do I need to sell to break even?
- status: stopped
- check ✗ a workbook was saved
- check ✗ answers 500 units
- steps: launch_app=failed, launch_app=failed, launch_app=verified, launch_app=failed, launch_app=failed, launch_app=rejected
- error: The agent was repeating the same action, so it was stopped.

## data-forecast — FAIL 29/100
- instruction: Using 'monthly sales.csv' in the 'Forecast data' folder inside 'S-CLAW Bench' in my Documents, make a forecast of the next 2 months of sales and tell me the forecast for the next month.
- status: stopped
- check ✗ a forecast workbook was saved
- check ✗ next month about 180,000
- steps: find_files=verified, read_file=verified, summarize_column=verified, add_computed_column=verified, add_computed_column=verified, add_computed_column=rejected
- error: The agent was repeating the same action, so it was stopped.

## data-chart — PASS 100/100
- instruction: Make a chart of total sales per product from 'monthly sales.csv' in the 'Chart data' folder inside 'S-CLAW Bench' in my Documents.
- status: completed
- check ✓ a workbook with a chart was saved
- steps: list_folder=verified, list_folder=verified, add_chart=failed, table_totals=verified, add_chart=verified
- answer: A bar chart showing total sales per product has been successfully created and saved as 'monthly sales with chart.xlsx' in the 'Chart data' folder. The chart updates dynamically with live totals.
