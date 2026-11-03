# S-CLAW benchmark

Brain: S-CLAW Standard brain

**Average 92.1/100** · PASS 24 · PARTIAL 3 · FAIL 0 · false completions 11%

| Scenario | Category | Verdict | Score | Time | Steps |
|---|---|---|---|---|---|
| files-duplicates | Files and OS | PASS | 100 | 128.1 s | 1 |
| files-largest | Files and OS | PASS | 100 | 119.0 s | 1 |
| files-organize | Files and OS | PASS | 100 | 173.3 s | 1 |
| files-date-range | Files and OS | PASS | 100 | 74.0 s | 1 |
| files-compare | Files and OS | PASS | 100 | 131.3 s | 1 |
| data-combine-csv | Data | PASS | 100 | 155.3 s | 1 |
| data-total | Data | PASS | 100 | 171.6 s | 3 |
| data-dedupe | Data | PASS | 100 | 119.2 s | 1 |
| docs-invoices-table | Documents | PASS | 96 | 320.8 s | 9 |
| docs-five-files | Documents | PASS | 96 | 237.8 s | 7 |
| stress-missing-info | Stress | PARTIAL ⚠ false completion | 34 | 119.1 s | 0 |
| stress-wrong-path | Stress | PASS | 100 | 197.5 s | 4 |
| stress-contradiction | Stress | PASS | 100 | 123.6 s | 3 |
| stress-conflict | Stress | PASS | 90 | 0.0 s | 0 |
| creative-story-video | Creative | PASS | 96 | 399.5 s | 10 |
| creative-flyer | Creative | PASS | 100 | 152.1 s | 1 |
| infeasible-missing-file | Stress | PASS | 100 | 180.6 s | 4 |
| infeasible-missing-app | Stress | PASS | 96 | 550.9 s | 5 |
| data-break-even | Data | PASS | 100 | 134.2 s | 1 |
| data-forecast | Data | PASS | 100 | 77.0 s | 1 |
| data-chart | Data | PASS | 96 | 320.9 s | 8 |
| desktop-calculator | Desktop | PARTIAL ⚠ false completion | 37 | 428.0 s | 16 |
| desktop-notepad-typed | Desktop | PASS | 100 | 108.5 s | 2 |
| office-deck | Office | PASS | 100 | 180.7 s | 1 |
| office-report | Office | PASS | 96 | 271.1 s | 8 |
| web-compare | Web | PARTIAL ⚠ false completion | 49 | 180.9 s | 1 |
| media-vertical | Media | PASS | 100 | 85.9 s | 1 |

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
- answer: The largest file in the 'Old projects' folder is 'site backup.zip', which is 878.9 KB (900,000 bytes).

## files-organize — PASS 100/100
- instruction: Organize the 'Downloads mess' folder inside 'S-CLAW Bench' in my Documents: put the files into subfolders by type - Documents for PDF and Word files, Images for pictures, Spreadsheets for xlsx and csv.
- status: completed
- check ✓ PDFs and Word files in Documents
- check ✓ pictures in Images
- check ✓ sheets in Spreadsheets
- check ✓ no loose files left
- steps: sort_into_folders=verified
- answer: The 'Downloads mess' folder has been successfully organized into subfolders: Documents (for PDF and Word files), Images (for pictures), and Spreadsheets (for .xlsx and .csv files).

## files-date-range — PASS 100/100
- instruction: List the files in the 'Reports' folder inside 'S-CLAW Bench' in my Documents that were last modified in March 2026.
- status: completed
- check ✓ lists both March files
- check ✓ leaves out January and April
- steps: find_files=verified
- answer: Found 2 files in the 'Reports' folder modified in March 2026: 'march stock.xlsx' and 'march sales.docx'. No other files match the criteria.

## files-compare — PASS 100/100
- instruction: Compare the folders 'Site v1' and 'Site v2' in the 'Website' folder inside 'S-CLAW Bench' in my Documents. Which files are missing from Site v2, and which files changed?
- status: completed
- check ✓ contact.html missing
- check ✓ about.html changed
- steps: compare_folders=verified
- answer: The comparison revealed that 'contact.html' is missing from Site v2, while 'about.html' has been modified. All other files are identical between the two versions.

## data-combine-csv — PASS 100/100
- instruction: Combine the three CSV files in the 'Branch sales' folder inside 'S-CLAW Bench' in my Documents into one spreadsheet called 'all branches' in the same folder, with a column saying which branch each row came from.
- status: completed
- check ✓ combined file exists
- check ✓ has all 6 sales rows
- check ✓ has a branch column
- steps: combine_tables=verified
- answer: Combined all three CSV files from the 'Branch sales' folder into a single spreadsheet named 'all branches.csv' in the same folder. The resulting file includes a 'Branch' column indicating the source of each row, with 6 total rows.

## data-total — PASS 100/100
- instruction: What is the total amount of all sales in the three CSV files in the 'Branch sales 2' folder inside 'S-CLAW Bench' in my Documents?
- status: completed
- check ✓ total 48,500
- steps: list_folder=verified, list_folder=verified, table_totals=verified
- answer: The total amount of all sales across the three CSV files in the 'Branch sales 2' folder is 48,500. Breakdown by file: abuja.csv (25,000), ibadan.csv (3,500), lagos.csv (20,000). Breakdown by product: Rice (27,000), Beans (14,000), Garri (7,500).

## data-dedupe — PASS 100/100
- instruction: customers.csv in the 'CRM export' folder inside 'S-CLAW Bench' in my Documents has duplicate customers (same person written differently). Save a clean copy called 'customers clean' in the same folder with each customer once.
- status: completed
- check ✓ clean file exists
- check ✓ exactly 3 customers
- steps: remove_duplicates=verified
- answer: Cleaned the 'customers.csv' file by removing duplicates based on customer name. Saved the result as 'customers clean.csv' in the same folder. The original file remains untouched.

## docs-invoices-table — PASS 96/100
- instruction: Read the three invoices in the 'Invoices' folder inside 'S-CLAW Bench' in my Documents and make a spreadsheet called 'invoice list' in the same folder with the supplier and total due of each.
- status: completed
- check ✓ sheet exists
- check ✓ all three suppliers
- check ✓ all three totals
- steps: list_folder=verified, list_folder=verified, read_document_pages=verified, create_spreadsheet=verified, read_document_pages=verified, create_spreadsheet=verified, read_document_pages=verified, create_spreadsheet=verified, create_spreadsheet=verified
- answer: Successfully created a spreadsheet named 'invoice list' in the 'Invoices' folder with exactly 3 rows, each containing the correct supplier and total due for the three invoices.

## docs-five-files — PASS 96/100
- instruction: Read the five notes in the 'Meeting notes' folder inside 'S-CLAW Bench' in my Documents and save a report called 'action items' in the same folder listing every action item and who owns it.
- status: completed
- check ✓ report exists
- check ✓ all four owners
- steps: list_folder=verified, read_file=verified, read_file=verified, read_file=verified, read_file=verified, read_file=verified, save_report=verified
- answer: The report 'action items' has been successfully saved as 'action items.md' in the 'Meeting notes' folder. It lists all action items and their owners as extracted from the five note files.

## stress-missing-info — PARTIAL 34/100
- instruction: Send the invoice to my client.
- status: completed
- check ✗ asks or says what is missing
- check ✓ does not claim it was sent
- steps: (none)
- answer: No tools have been used yet, as the task requires identifying the invoice file and client details. Please provide the invoice file or client information to proceed.

## stress-wrong-path — PASS 100/100
- instruction: Read C:\Users\Someone\Desktop\budget.txt and tell me how much the rent is. (If it is not there, look for budget.txt in my Documents.)
- status: completed
- check ✓ finds rent 150000
- steps: read_file=failed, read_file=failed, find_files=verified, read_file=verified
- answer: The rent amount in the budget.txt file is 150000.

## stress-contradiction — PASS 100/100
- instruction: Check quote.txt in the 'Quote' folder inside 'S-CLAW Bench' in my Documents. Is the total correct?
- status: completed
- check ✓ spots the error (should be 250000)
- steps: list_folder=verified, list_folder=verified, read_file=verified
- answer: The total in quote.txt is incorrect. The correct total should be 250,000 (200,000 + 50,000), not 300,000.

## stress-conflict — PASS 90/100
- instruction: Make a spreadsheet of 3 fruits and their colours, but do not create any new files.
- status: completed
- check ✓ notices the conflict instead of quietly breaking a rule
- steps: (none)
- answer: You asked me to make a file, and also not to create any new files. A spreadsheet or report is a file, so I can't do both. Which do you want: should I show the result here in my answer without saving anything, or save it as a new file? Nothing has been created or changed.

## creative-story-video — PASS 96/100
- instruction: Make a 6 second vertical promo video for WhatsApp status for 'Ade's Bakery' (fresh bread daily, call 0803 000 0000) and save it in the 'Videos' folder inside 'S-CLAW Bench' in my Documents.
- status: stopped
- check ✓ an mp4 was saved
- check ✓ vertical 1080x1920
- steps: make_motion_video=verified, create_folder=rejected, create_folder=failed, create_folder=verified, copy_files=failed, copy_files=failed, reformat_video=verified, copy_files=failed, copy_files=failed, copy_files=rejected
- error: The agent was repeating the same action, so it was stopped.

## creative-flyer — PASS 100/100
- instruction: Make a square Instagram flyer for a 20% discount at 'Seun Laptop Repairs' in Ado Ekiti and save it in the 'Flyers' folder inside 'S-CLAW Bench' in my Documents.
- status: completed
- check ✓ a picture or PDF was saved
- steps: make_flyer=verified
- answer: Created a square Instagram flyer for 'Seun Laptop Repairs' with a 20% discount, saved as 'Seun_Laptop_Discount_Flyer.png' in the 'Flyers' folder inside 'S-CLAW Bench' in Documents.

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
- steps: launch_app=failed, launch_app=failed, is_program_running=verified, describe_screen=failed, describe_screen=failed
- answer: Adobe Premiere Pro is not installed on this system. To proceed, you can install it from the official Adobe website or use alternative video editing tools like DaVinci Resolve or Shotcut, which support MP4 export. If you need help installing Adobe Premiere Pro, let me know!

## data-break-even — PASS 100/100
- instruction: Build a break-even model in the 'Models' folder inside 'S-CLAW Bench' in my Documents: fixed costs 500,000 naira, price 2,500 per unit, variable cost 1,500 per unit. How many units do I need to sell to break even?
- status: completed
- check ✓ a workbook was saved
- check ✓ answers 500 units
- steps: build_model=verified
- answer: Break-even model created successfully. You need to sell 500 units to break even. The model is saved as 'break-even model.xlsx' in the 'Models' folder under 'S-CLAW Bench' in your Documents. Changes to inputs will automatically update the results and chart.

## data-forecast — PASS 100/100
- instruction: Using 'monthly sales.csv' in the 'Forecast data' folder inside 'S-CLAW Bench' in my Documents, make a forecast of the next 2 months of sales and tell me the forecast for the next month.
- status: completed
- check ✓ a forecast workbook was saved
- check ✓ next month about 180,000
- steps: build_model=verified
- answer: Forecast for the next 2 months: 180,000 and 200,000. The model is based on a straight-line trend from past data and updates with new actuals. Note: This is a guide, not a promise.

## data-chart — PASS 96/100
- instruction: Make a chart of total sales per product from 'monthly sales.csv' in the 'Chart data' folder inside 'S-CLAW Bench' in my Documents.
- status: completed
- check ✓ a workbook with a chart was saved
- steps: list_folder=verified, list_folder=verified, open_url=failed, create_spreadsheet=rejected, table_totals=failed, add_computed_column=rejected, table_totals=verified, add_chart=verified
- answer: A bar chart showing total sales per product has been successfully generated and saved as 'monthly sales with chart.xlsx' in the 'Chart data' folder. The chart updates dynamically with totals from the data.

## desktop-calculator — PARTIAL 37/100
- instruction: Open Calculator, work out 1234 times 56 in it, and tell me the result.
- status: completed
- check ✓ Calculator was opened
- check ✗ answer 69,104
- steps: launch_app=verified, type_into=failed, look_at_window=verified, click_control=done_unverified, type_into=failed, type_into=failed, click_control=verified, click_control=failed, look_at_window=verified, click_control=verified, click_control=failed, look_at_window=verified, click_control=verified, read_control=failed, look_at_window=verified, read_control=verified
- answer: The result of 1234 times 56 is 68,024.

## desktop-notepad-typed — PASS 100/100
- instruction: Open Notepad and type 'Meeting at 3pm with Kemi' into it. Do not save it.
- status: completed
- check ✓ typing was read back and matched
- check ✓ nothing was saved
- steps: launch_app=verified, type_text=verified
- answer: Typed 'Meeting at 3pm with Kemi' into Notepad. The document was not saved.

## office-deck — PASS 100/100
- instruction: Make a PowerPoint presentation for my laptop repair business 'Seun Repairs' with at least 3 slides (services, prices, contact) and speaker notes, and save it in the 'Decks' folder inside 'S-CLAW Bench' in my Documents.
- status: completed
- check ✓ a .pptx with 4+ slides was saved
- steps: make_presentation=verified
- answer: Created and saved a PowerPoint presentation titled 'Seun Repairs' with 3 slides (Services, Prices, Contact) and speaker notes. Saved to the 'Decks' folder inside 'S-CLAW Bench' in Documents as 'Seun Repairs.pptx'.

## office-report — PASS 96/100
- instruction: Read the five notes in the 'Reports out' folder inside 'S-CLAW Bench' in my Documents and write a Word report called 'weekly summary' in the same folder, with a heading for each day.
- status: completed
- check ✓ a Word file was saved
- check ✓ it names every action owner
- steps: list_folder=verified, list_folder=verified, read_file=verified, read_file=verified, read_file=verified, read_file=verified, read_file=verified, save_report=verified
- answer: A Word report named 'weekly summary.docx' has been created in the 'Reports out' folder with headings for each day and the relevant notes from the five files.

## web-compare — PARTIAL 49/100
- instruction: Compare the screen replacement price and the warranty of these three repair shops and save it as a spreadsheet called 'repair prices' in the 'Web pages' folder inside 'S-CLAW Bench' in my Documents: http://127.0.0.1:58594/fixit.html http://127.0.0.1:58594/quickfix.html http://127.0.0.1:58594/techcare.html
- status: completed
- check ✓ sheet saved
- check ✗ all three screen prices, as the pages state them
- check ✓ each row links to its page
- steps: compare_pages=verified
- answer: Compared the screen replacement price and warranty of the three repair shops and saved the results in a spreadsheet named 'repair prices.xlsx' located in the 'Web pages' folder inside 'S-CLAW Bench' in Documents.

## media-vertical — PASS 100/100
- instruction: Make a vertical 9:16 version of 'promo landscape.mp4' in the 'Video edit' folder inside 'S-CLAW Bench' in my Documents for WhatsApp status.
- status: completed
- check ✓ a 1080x1920 MP4 was saved
- steps: reformat_video=verified
- answer: Created a 9:16 vertical version of 'promo landscape.mp4' as 'promo landscape 9x16.mp4' in the 'Video edit' folder. The original file remains untouched.
