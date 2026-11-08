# Real trial

## Open Notepad, type 'S-CLAW release check', save it as release-check.txt in Documents, reopen it, and verify the exact contents.
- status: **completed** (92.3 s)
- step `launch_app` → verified: Opened Notepad: window 'Untitled - Notepad'.
- step `type_text` → verified: Typed 20 characters and read them back from the window: they match.
- step `write_text_file` → verified: Created release-check (2).txt (20 characters). A file called release-check.txt was already there, so this one is release-check (2).txt; check release-check (2).txt, not release-check.txt.
- step `check_file` → verified: Checked release-check (2).txt: its contents match exactly.
- answer: Typed 'S-CLAW release check' into Notepad, saved it as 'release-check (2).txt' in Documents, and verified its exact contents match the expected text.

## Read invoice.pdf in my Documents folder and tell me the total amount due.
- status: **completed** (37.8 s)
- step `read_document_pages` → verified: Read pages 1–1 of invoice.pdf (1 pages).
- answer: The total amount due on the invoice is 580.50.

## Make a promotional flyer for my software TechDesk and save it in Documents.
- status: **completed** (63.4 s)
- step `make_flyer` → failed: Access to 'C:\Users\Public\Pictures\TechDesk.jpg' is not allowed: it is outside the folders you authorized. The folders you can use are: Documents (C:\Users\runneradmin\Documents), Desktop (C:\Users\runneradmin\Desktop), Downloads (C:\Users\runneradmin\Downloads). Write the path starting with the fo
- step `make_flyer` → verified: Made the flyer with Claw's built-in image editor (Photoshop was not used): TechDesk_Flyer.pdf (PDF); OCR read 100% of the headline words back from the image.
- answer: A promotional flyer for TechDesk software has been created and saved as 'TechDesk_Flyer.pdf' in the Documents folder. The flyer was designed using Claw's built-in editor, as Photoshop was not available.
- event failed: {"step": 1, "tool": "make_flyer", "detail": "Access to 'C:\\Users\\Public\\Pictures\\TechDesk.jpg' is not allowed: it is outside the folders you authorized. The folders you can use are: Documents (C:\\Users\\runneradmin\\Documents), Desktop (C:\\Users\\runneradmin\\Desktop), Downloads (C:\\Users\\ru

## Make a 10 second promo video for my software TechDesk and save it in Documents.
- status: **completed** (51.3 s)
- step `make_motion_video` → verified: Made the video with Claw's built-in video maker (After Effects was not used): promo video.mp4 (1920×1080, 10.0 s, 300 frames); OCR read 100% of the headline words in the video.
- answer: A 10-second promo video for TechDesk has been created and saved in the Documents folder as 'promo video.mp4'.
