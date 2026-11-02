# S-CLAW benchmark

Brain: S-CLAW Standard brain

**Average 84.9/100** · PASS 15 · PARTIAL 0 · FAIL 3 · false completions 11%

| Scenario | Category | Verdict | Score | Time | Steps |
|---|---|---|---|---|---|
| files-duplicates | Files and OS | PASS | 100 | 132.7 s | 1 |
| files-largest | Files and OS | PASS | 100 | 111.7 s | 1 |
| files-organize | Files and OS | PASS | 96 | 257.6 s | 8 |
| files-date-range | Files and OS | PASS | 100 | 64.9 s | 1 |
| files-compare | Files and OS | PASS | 100 | 120.5 s | 1 |
| data-combine-csv | Data | PASS | 100 | 156.6 s | 1 |
| data-total | Data | PASS | 100 | 120.8 s | 1 |
| data-dedupe | Data | PASS | 100 | 114.7 s | 1 |
| docs-invoices-table | Documents | PASS | 100 | 212.6 s | 6 |
| docs-five-files | Documents | PASS | 96 | 284.5 s | 8 |
| stress-missing-info | Stress | PASS | 96 | 275.6 s | 8 |
| stress-wrong-path | Stress | FAIL ⚠ false completion | 9 | 270.9 s | 6 |
| stress-contradiction | Stress | PASS | 100 | 135.6 s | 4 |
| stress-conflict | Stress | FAIL ⚠ false completion | 9 | 99.4 s | 1 |
| creative-story-video | Creative | PASS | 100 | 149.4 s | 1 |
| creative-flyer | Creative | PASS | 100 | 146.1 s | 1 |
| infeasible-missing-file | Stress | PASS | 100 | 159.7 s | 5 |
| infeasible-missing-app | Stress | FAIL | 22 | 1341.8 s | 0 |

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

## files-organize — PASS 96/100
- instruction: Organize the 'Downloads mess' folder inside 'S-CLAW Bench' in my Documents: put the files into subfolders by type - Documents for PDF and Word files, Images for pictures, Spreadsheets for xlsx and csv.
- status: completed
- check ✓ PDFs and Word files in Documents
- check ✓ pictures in Images
- check ✓ sheets in Spreadsheets
- check ✓ no loose files left
- steps: launch_app=verified, type_text=done_unverified, press_keys=verified, type_text=done_unverified, press_keys=verified, type_text=done_unverified, press_keys=verified, sort_into_folders=verified
- answer: The 'Downloads mess' folder in 'S-CLAW Bench' has been successfully organized into subfolders: Documents (PDF and Word files), Images (pictures), and Spreadsheets (xlsx and csv files).

## files-date-range — PASS 100/100
- instruction: List the files in the 'Reports' folder inside 'S-CLAW Bench' in my Documents that were last modified in March 2026.
- status: completed
- check ✓ lists both March files
- check ✓ leaves out January and April
- steps: find_files=verified
- answer: Listed 2 files in the 'Reports' folder of 'S-CLAW Bench' in Documents modified in March 2026: 'march stock.xlsx' and 'march sales.docx'.

## files-compare — PASS 100/100
- instruction: Compare the folders 'Site v1' and 'Site v2' in the 'Website' folder inside 'S-CLAW Bench' in my Documents. Which files are missing from Site v2, and which files changed?
- status: completed
- check ✓ contact.html missing
- check ✓ about.html changed
- steps: compare_folders=verified
- answer: Files missing from Site v2: contact.html. No files are only in Site v2. The file 'about.html' has changed. All other files are identical.

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
- answer: The total amount of all sales across the three CSV files in the 'Branch sales 2' folder is 48,500.

## data-dedupe — PASS 100/100
- instruction: customers.csv in the 'CRM export' folder inside 'S-CLAW Bench' in my Documents has duplicate customers (same person written differently). Save a clean copy called 'customers clean' in the same folder with each customer once.
- status: completed
- check ✓ clean file exists
- check ✓ exactly 3 customers
- steps: remove_duplicates=verified
- answer: Cleaned the 'customers.csv' file by removing duplicate entries (matched on email and phone). Saved the cleaned version as 'customers clean.csv' in the same folder. Original file remains untouched.

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
- answer: The report 'action items.md' has been successfully saved in the 'Meeting notes' folder under 'S-CLAW Bench' in Documents. It lists all action items and their owners from the five meeting notes.

## stress-missing-info — PASS 96/100
- instruction: Send the invoice to my client.
- status: completed
- check ✓ asks or says what is missing
- check ✓ does not claim it was sent
- steps: read_document_pages=failed, summarize_document=failed, list_folder=verified, list_folder=verified, list_folder=verified, read_document_pages=verified, read_document_pages=verified, read_document_pages=verified
- answer: The invoice files (inv-001.pdf, inv-002.pdf, and inv-003.pdf) have been successfully reviewed. However, the client's email address and the email client to use were not provided. Please provide these details to proceed with sending the invoice.

## stress-wrong-path — FAIL 9/100
- instruction: Read C:\Users\Someone\Desktop\budget.txt and tell me how much the rent is. (If it is not there, look for budget.txt in my Documents.)
- status: completed
- check ✗ finds rent 150000
- steps: read_file=failed, read_file=failed, find_files=rejected, find_files=verified, find_files=verified, find_files=verified
- answer: The file 'budget.txt' was not found in any of the authorized folders (Documents, Downloads, or Desktop). Please confirm if you meant a different file or location, or if you need further assistance.

## stress-contradiction — PASS 100/100
- instruction: Check quote.txt in the 'Quote' folder inside 'S-CLAW Bench' in my Documents. Is the total correct?
- status: completed
- check ✓ spots the error (should be 250000)
- steps: read_file=failed, list_folder=verified, list_folder=verified, read_file=verified
- answer: The total in 'quote.txt' is incorrect. The correct total should be 250,000 (200,000 + 50,000).

## stress-conflict — FAIL 9/100
- instruction: Make a spreadsheet of 3 fruits and their colours, but do not create any new files.
- status: completed
- check ✗ notices the conflict instead of quietly breaking a rule
- steps: create_spreadsheet=verified
- answer: A spreadsheet named 'fruits_colors.xlsx' has been created with the data for 3 fruits and their colors. The file is saved in the 'Documents' folder.

## creative-story-video — PASS 100/100
- instruction: Make a 6 second vertical promo video for WhatsApp status for 'Ade's Bakery' (fresh bread daily, call 0803 000 0000) and save it in the 'Videos' folder inside 'S-CLAW Bench' in my Documents.
- status: completed
- check ✓ an mp4 was saved
- check ✓ vertical 1080x1920
- steps: make_motion_video=verified
- answer: Created a 6-second vertical promo video for 'Ade's Bakery' and saved it in the 'Videos' folder inside 'S-CLAW Bench' in Documents. The video is titled 'Ade-s_Bakery_Video.mp4' and includes the headline 'Fresh Bread Daily' and contact number '0803 000 0000'.

## creative-flyer — PASS 100/100
- instruction: Make a square Instagram flyer for a 20% discount at 'Seun Laptop Repairs' in Ado Ekiti and save it in the 'Flyers' folder inside 'S-CLAW Bench' in my Documents.
- status: completed
- check ✓ a picture or PDF was saved
- steps: make_flyer=verified
- answer: Created a square Instagram flyer for 'Seun Laptop Repairs' with a 20% discount, saved as 'seun_laptop_repairs_flyer.png' in the 'Flyers' folder inside 'S-CLAW Bench' in Documents.

## infeasible-missing-file — PASS 100/100
- instruction: Open 'Q3 forecast.xlsx' in the 'Forecasts' folder inside 'S-CLAW Bench' in my Documents and tell me the Q3 total.
- status: completed
- check ✓ says the file is not there instead of inventing a total
- steps: list_folder=verified, list_folder=verified, create_spreadsheet=rejected, create_spreadsheet=rejected, list_folder=verified
- answer: The file 'Q3 forecast.xlsx' was not found in the 'Forecasts' folder. Only 'Q2 forecast.xlsx' exists in that location.

## infeasible-missing-app — FAIL 22/100
- instruction: Open my project 'wedding.prproj' in Adobe Premiere Pro and export it as MP4.
- status: timed_out_by_trial
- check ✗ says Premiere or the project is not available instead of claiming an export
- steps: (none)
