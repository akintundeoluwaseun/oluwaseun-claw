# Changelog

## Unreleased — right-click, dragging, and jobs too long to wait for

The three gaps named last time, closed. 147 tools, 1500 tests.

**Right-click and double-click.** click_at takes a button and a double now.
A left click cannot open a context menu or open a file from its icon, and
the accessibility tree reaches neither: a context menu does not exist until
it is asked for. A driver that cannot do it raises rather than quietly
left-clicking instead - a right-click that silently becomes a left-click
opens the file instead of its menu and reports success.

**Dragging.** drag presses at one point, moves through a midpoint and
releases at another. The midpoint matters: a press and release with nothing
between them is not a drag to most applications, which begin the operation
on the first move. Moving a file into a folder, reordering a list, drawing
a selection - none of it reachable by clicking.

**Long jobs.** start_program, check_program and stop_program. run_command
waits and gives up after five minutes, which is right for most things and
wrong for the ones that matter most - a Blender render, an hour of footage
converted, a build. Being killed at five minutes throws the work away and
says nothing useful.

Running in the background is not a way round any gate: the same allowlist,
the same refusal of shell punctuation, the same authorised folder, the same
approval before anything starts, and tests for each. Output streams to a
file rather than memory, so a program that prints for twenty minutes cannot
fill the machine and what it said survives being stopped. A program that
dies immediately is reported immediately, not in ten minutes when somebody
thinks to look. On Linux each job gets its own process group, so stopping
it stops what it started.

## Unreleased — Claw can install a program, and use the clipboard

Two things it could not do that any person sitting at the machine can.
143 tools.

**Installing.** install_app puts a program on the computer from the official
catalogue - winget on Windows, which ships with Windows 10 and 11, and apt
on Linux. find_app_to_install looks one up first and installs nothing.

Three rules, none of which bends:
- Never silent. Destructive risk, so it asks every time, and the card names
  the exact package id - not the word typed, not the brain's paraphrase. The
  permission policy refuses to let destructive mean "allow", so no setting
  turns this into something that happens behind the person.
- The official catalogue only. A .exe, an .msi or a URL is refused outright:
  "install this installer I found" is how a machine gets what nobody wanted.
  A name with a space, a semicolon or a backtick in it is not a package name
  and is refused rather than handed to a shell - and the package manager is
  run directly, with no shell involved at all.
- Checked afterwards. The package manager reporting success and the program
  being on the machine are two different claims, so it asks the catalogue
  again and reports what is actually there.

Really installed on this machine while writing it: cowsay and sl, both
absent beforehand, both present and running afterwards.

**The clipboard.** read_clipboard and put_on_clipboard. Claw could press
Ctrl+C and had no idea what landed. The clipboard is the way out of every
app with no accessibility tree - a PDF viewer, a Java program, anything
drawn rather than built from controls - and it closes a verification gap:
"I copied the invoice number" was a claim with nothing behind it.

A picture on the clipboard reads as "no text", not as an empty clipboard,
because telling the brain nothing was copied when a screenshot is sitting
there sends it round the same loop again. A machine with no clipboard
program says so instead of returning an empty string that reads like an
empty clipboard.

## Unreleased — headroom in the catalogue, and the flaky test placed

- The tool catalogue had run out of room. Trimming turned detailed entries
  into bare names and stopped there; the line of names itself never shrank.
  With 139 tools the full catalogue sat at 4780 tokens of 4800 and a files
  step at 1789 of 1800, so the next tool anyone added would have gone over
  with nothing left to trim. The names line now trims too, least relevant
  first, and says how many were left out so the brain knows they exist and
  can still ask for them by name. It does not fire today - nothing about the
  current output changes - it is headroom.
- The intermittent planner test is explained. It failed with
  'task_cancelled' roughly twice in twenty full-suite runs and never alone.
  A bare TestClient ends its lifespan whenever it is garbage collected, and
  the app cancels a busy runner on the way out, so a task still running at
  that moment is cancelled mid-flight. The test now holds the client open,
  which is what the tests that never flaked already did.

## Unreleased — a table out of a PDF, without retyping it

table_from_document reads a bank statement, a supplier's invoice or a price
list straight into a spreadsheet. 139 tools.

There was already a way to do this and it was the wrong way: the brain reads
the page and calls list_to_table with the rows it has typed out, which puts
every digit through a language model. A small model transcribing a column of
amounts gets some of them wrong, and the spreadsheet that comes out looks
perfectly ordinary. This reads the file itself, so no number passes through
the model.

Two guards, because a wrong spreadsheet is worse than none:

- Every cell written is looked for in the document's own text, and the sign
  is part of the match. "2,500" is a substring of "(2,500)", so a plain
  search would accept a positive 2500 for a page that shows only a debit - a
  sign error passed silently, in the one column where it matters. Brackets
  and minus signs are matched explicitly, both ways round.
- A page whose lines do not agree on how many columns they have is refused
  rather than guessed at. A letter, or a scan with no text layer, says so
  plainly instead of producing a tidy, wrong sheet.

Amounts land as numbers, so the column totals, and "(2,500)" arrives as
-2500 the way a ledger means it.

## Unreleased — change the same text everywhere, join Word documents

- replace_in_files: the business changed its phone number, or a name was
  spelled wrong in forty quotations. Works on text files and Word documents,
  including a phrase Word has split across runs. It writes corrected COPIES
  into a new folder and never edits in place - a find-and-replace across a
  folder is the easiest way there is to lose an afternoon's work, and there
  is no undo. A preview mode reports what would change without writing
  anything, and when the text appears nowhere it refuses, rather than copying
  the folder and reporting success while the person believes it was changed.
- merge_documents: several Word files into one, in order, with page breaks.
  Checked by reopening the result and looking for the LAST document's text,
  because the way this fails is that the append quietly does nothing.

138 tools.

## Unreleased — benchmark v1.9, and a video bug it found

Six scenarios for the everyday jobs added above: opening the supplier's zip,
joining the month's invoices into one PDF, shrinking a folder of shop photos
for WhatsApp, a QR code that really scans, a reminder letter per customer,
and cutting a clip. Each check is tested both ways - the rejected answers are
the plausible ones: the folder left unpacked, three PDFs instead of one, the
originals overwritten instead of copied, a letter still saying {Name}, a
blank PNG passed off as a QR code.

Then every scenario was run through the real tools and scored by its own
checks: all six pass on Linux. Writing them found two bugs.

- **trim_video was wrong on a differently encoded video.** It cleared each
  frame's timestamp and let the encoder invent them. On one test video that
  came out right; on the benchmark's video every frame got the same
  timestamp, so cutting three seconds out of an eight-second advert saved a
  0.1-second file. The tool reported the mismatch, because it measures what
  it wrote, but it was still wrong - and only a second kind of source video
  showed it. Timestamps are counted now. shrink_video and extract_audio had
  the same bug waiting in them and are fixed too.
- Two of the new bench checks were themselves wrong: one looked for the
  smaller photos only inside the source folder when the tool correctly writes
  beside it, and excluded files by name when the copies correctly keep their
  names.

Correction: the wait_done deadline was raised from 20s to 60s earlier and
described as the fix for an intermittent planner test. That was wrong. When
that test fails the events are ['requested_task', 'model_call',
'task_cancelled'] - the task is CANCELLED, so the deadline never comes into
it. It is not reproduced in isolation and is not understood; both the test
and the helper now say so instead of carrying a false explanation.

## Unreleased — tools that existed but nothing pointed at

Auditing the fitting list against the registry found 62 of 136 tools that no
pattern ever named. Several were worse than unnamed, because a general
pattern claimed the words and sent the brain elsewhere:

- "Make an invoice" matched the word invoice and was answered with the tool
  that READS a PDF. The request failed with the right tool sitting there.
- "Write a python script to rename these files" landed on rename_file, so the
  whole code capability was unreachable by the words people use for it.
- "Which files mention the word refund" landed on find_files, which searches
  names, not contents.
- "Make a pivot table" landed on create_spreadsheet; "make a passport photo"
  on edit_image; "design a bracket 60 by 40 mm" on a 3D render rather than
  actual CAD.
- "What is taking up my disk space" matched nothing at all.

All fixed, plus routing for filtering rows, outliers, reconciling two tables,
summarising a column, collages, brightening a dark photo, product shots,
describing a picture, whether a program is running, and the time.

Down to 43 unnamed, and those are browser and desktop sub-steps (click_link,
switch_tab, scroll) that are reached once a flow is under way rather than
asked for by name.

The routing tests now hold 40 phrasings and separately assert that making an
invoice is not confused with reading one, that writing a program reaches the
code tools, and that searching inside files is not searching for files.

## Unreleased — the new tools can actually be reached

The sixteen tools added above were invisible. fitting_tools decides which
tools are described in full to the brain, and none of them was in that list,
so the brain was never shown them. Worse, the general patterns mis-routed
around them: "make my photos smaller" matched picture|photo|image and landed
on edit_image, which does one file at a time; "join these invoices" matched
"invoice" and landed on reading a PDF.

A tool the brain is never shown is, from the brain's side, a tool that does
not exist - which is most of the difference between "the app can do this" and
"the app does this".

Patterns added for all sixteen, placed before the general ones, phrased the
way a person asks rather than by tool name. Also:

- Packing and opening an archive are told apart ("zip up my folder" against
  "unzip the attachment"), and "what's in this zip" leads with the tool that
  only looks, so asking a question does not unpack two hundred files.
- "too big to send on whatsapp" now leads with shrinking the video rather
  than with the WhatsApp tools.
- Reading a PDF still beats changing one, which is checked.

tests/test_tool_routing.py holds 25 real phrasings, asserts each offers the
right tool AND offers it first, and checks that no pattern points at a tool
that no longer exists.

## Unreleased — mail merge

mail_merge: a Word or text template with {Name} style placeholders, plus a
CSV or spreadsheet whose headings match, makes one document per row in a new
folder. Letters, reminders, invoices, certificates - the job whose manual
version is open, change the name, save as, repeat fifty times.

Built around the two ways a mail merge produces output that looks finished
and is not:

- A letter that goes out saying "Dear {Name}". If a placeholder has no column
  to fill it, NOTHING is written and the error names the placeholder and
  lists the columns the table does have. Half a merge is found by the
  customer, not by us.
- A placeholder Word has split up. Typing a line and correcting a letter in
  the middle leaves Word storing "{Na", "m", "e}" as separate runs, and a
  replacement done run by run misses it while working perfectly on a
  template typed in one go. Paragraphs are joined before matching, and the
  test builds a template with a deliberately split placeholder.

Every document is reopened and checked: no placeholder left behind, and the
row's own details actually in it, so a letter cannot come out holding the
previous customer's figures. Two customers with the same name both get their
own file.

## Unreleased — the four video jobs that needed an editor

131 to 135. All on PyAV, already inside S-CLAW, so no editor and no
ffmpeg.exe to install.

- trim_video: cut out the part that matters. Times are written the way the
  player shows them - 30, 1:30, 00:01:30 or 2m30s. The span is re-encoded
  rather than copied: copying can only start on a keyframe, so "from 1:30"
  quietly becomes "from 1:27" or the clip opens on a grey smear.
- extract_audio: the sound on its own as mp3, m4a or wav, for a podcast, a
  voice note or a transcript. A silent video says so instead of writing an
  empty file.
- grab_frame: one still, for a thumbnail. The test takes two frames from
  different moments and checks they are actually different pictures, so
  "at 5 seconds" cannot be quietly ignored.
- shrink_video: small enough for WhatsApp, which stops at about 16 MB. Works
  out the bit rate from the length, drops to 720p when bigger, and measures
  the saved file to confirm it is under the limit. A video already small
  enough is left alone and no file is written.

## Unreleased — opening archives, folders of photos, QR codes

Five more tools. 126 to 131.

**Archives.** Claw could pack a .zip and could not open one, so a supplier's
folder of photos or a bank's statements meant doing it by hand.
- open_archive: unpack a .zip or .tar into a new folder, optionally only the
  files matching a pattern.
- look_inside_archive: see what is in it without unpacking anything.

An archive is made somewhere else by someone else, so the names inside it are
treated as data, not instructions. An entry that points outside the
destination ("../../something") is refused, and refused before a single byte
is written, so a bad archive cannot leave half its contents behind. Absolute
paths are refused. Symlink entries are skipped rather than followed. A file
that unpacks to far more than it claims is stopped. The tests include an
actual zip-slip archive, an actual tar-slip archive and an actual
decompression bomb, and check that nothing lands outside the folder.

**Folders of photographs.** edit_image did one picture; the job people have is
two hundred off a phone that will not go through WhatsApp.
- resize_photos: a whole folder, smaller, into a new folder, by name
  ("whatsapp", "email", "website", "thumbnail") or a pixel size. Measured on
  real photos: 25.1 MB down to 1.7 MB, 93% smaller. A picture already smaller
  than the target is left alone rather than blown up. One unreadable file does
  not stop the batch.
- watermark_photos: your name across every picture in a folder.

**QR codes.** make_qr_code, for a link, a phone number or a payment page, with
an optional label printed underneath. The code is read back off the saved
picture and checked before it is reported - a QR code that does not scan is
only discovered after it is printed on something. This adds one dependency,
zxing-cpp (Apache-2.0, self-contained wheels including Windows), recorded in
THIRD_PARTY_NOTICES.md.

## Unreleased — changing PDFs, not just reading them

Claw could open a PDF, OCR it, search it and summarise it, and could not
alter one. Everything a person does to a PDF between receiving it and sending
it on meant opening something else. Six new tools, all on pypdf, which Claw
already ships, so nothing new to install:

- combine_pdfs: join the month's invoices into one file, in the order given.
- extract_pages: "just pages 2 to 5 of this contract".
- split_pdf: a forty-page scan into separate files, one page each or every N.
- rotate_pdf: turn a sideways scan the right way up, whole file or named pages.
- stamp_pdf: PAID, DRAFT, COPY, CONFIDENTIAL across the page.
- shrink_pdf: make it small enough to e-mail, and say by how much. When it
  cannot help it says so rather than reporting a 2% saving as a win.

Every one writes a NEW file and leaves the original untouched - a scan is
often the only copy - and every one reopens what it wrote and counts it
before reporting. The tests check both: that the original is unchanged byte
for byte, and that no page went missing.

The stamp is drawn into the page's own content, not hung on it as an
annotation. The first version used an annotation: it rendered as small
left-aligned text rather than a stamp, and an annotation can be hidden, left
out of a printout or dropped by the next program that touches the file. A
document that only says PAID in some viewers is worse than one that does not.

## Unreleased — every spreadsheet prints properly

- The one-page-across fix now applies to every workbook Claw writes, not just
  invoices: pivot tables, charts, break-even and forecast models, outlier
  reports and combined tables. A break-even model's chart was being cut in
  half down the right-hand edge. These are made to be shown to somebody - a
  bank, a manager, a customer - and the file being right is no use when the
  printout is wrong. Wide tables turn landscape; long ones still run to as
  many pages down as they need.

## Unreleased — invoices can carry a discount

- The printed invoice was missing every figure. The four columns come to about
  8.7 inches and A4 portrait leaves roughly 6.8 once margins are off, so the
  Amount column - and the subtotal, tax and total with it - went onto a second
  page on its own. The file was right and the printout was wrong, which is the
  worse way round for a document whose only purpose is to be sent to somebody.
  Documents now fit one page across (and as many pages down as they need, so a
  long invoice is not squeezed until nobody can read it). Found by rendering
  one and looking at it.

- An invoice line's price could only be digits, so "1 x Loyalty discount @
  (N1,000)" was refused and the whole document could not be made. A discount,
  a credit note and a deposit already paid are ordinary lines, and all three
  are a negative price. Written "-1000", "(1,000)" or "(N1,000)". The totals
  were always a plain SUM, so the arithmetic needed no change: a discounted
  invoice adds up, is written as real formulas, and is still checked by
  reopening the saved file.
- make_document reads money through the same shared cleaner as the table
  tools, so it was the third of three parsers and is now one of one.
- A sign in front of a QUANTITY is refused instead of guessed at. It used to
  fall through to the pattern that defaults the quantity to 1 and keeps the
  rest as the description, so "-2 x poster @ 100" became a single
  "2 x poster" at 100: an invoice short by 100, with nothing on it looking
  wrong. A hyphen inside a description ("A-2 cable x 3 @ 50") still works.

## Unreleased — two bugs in how money was read

Found by probing the table tools with the kind of column a real ledger has,
rather than the tidy one the tests used. Both were silent: the tool reported
itself verified and gave a wrong number.

- A refund written the way ledgers, bank statements and accounts packages
  write one - "(2,000)" - was read by summarize_column and
  add_computed_column as POSITIVE 2000. A total with one bracketed refund in
  it came out wrong by twice the amount. table_tools.to_number had read
  brackets correctly all along, so the same column totalled by table_totals
  and summarized by summarize_column gave two different answers and nothing
  said which to believe. The Unicode minus sign (what Word's autocorrect and
  many spreadsheet exports produce) was also read as positive.
- "N2,000" - naira with a bare N, as written on invoices, in WhatsApp and in
  exported statements - was no number at all to the data tools, so the row was
  skipped and the total came out short with nothing to say it had.
- Both readers now share one cleaner (clean_number_text), so they cannot drift
  apart again, and tests hold them to the same table of cases. An en dash is
  still not a minus: "10-20" in a cell is a range.

Anyone who has totalled a column containing bracketed amounts or N-prefixed
naira should re-run it.

## Unreleased — jobs with no tool of their own

The gap this closes is not a missing tool. It is that every capability so far
had to be built in advance, so a job nobody had anticipated got a worse plan
made of the wrong tools, or nothing.

- New "code" capability: run_command runs a program on this computer and hands
  its output back to the brain, which reads it and decides what to do next;
  run_script writes a small Python or Node program and runs it. Both are
  destructive-risk, so they always ask first - the permission policy refuses to
  let destructive ever mean "allow".
- A program must be on a known list before it runs. Programs that delete things
  wholesale, change Windows outside a folder or need administrator rights are
  refused outright and cannot be added. Package managers (npm, pip, cargo and
  the rest) are not on the default list, because they fetch and execute code in
  one step; they can be added deliberately.
- Settings > Limits > "Other programs Claw may run" is where that list is
  added to. Before this, the refusal told people to add a program in Settings
  and there was no such setting anywhere - the advice was impossible to follow.
- The planner now names the job shapes that need a program (numbering files in
  an order, splitting a table by a column, checksums, tallying across files,
  converting a folder one by one) instead of only warning it off. Whether the
  brain actually reaches for it is a real-brain question: NOT YET MEASURED,
  pending a Windows bench run.
- Benchmark set v1.8, four scenarios: code-split-csv (one file per city,
  headers intact), code-checksum-manifest (real SHA-256, so invented hex
  fails), code-count-words, and files-rename-in-order (photos renamed into
  the order they were taken, as "Wedding 001"). NOT YET RUN against a real
  brain - they exist to answer "how many tasks can it really do" with a
  measurement rather than a claim. Their checks are themselves tested both
  ways: each passes a correct result and rejects a plausible wrong one
  (photos renamed alphabetically, a split that drops the header, a split
  that mixes two cities, made-up checksums, "the" called a theme).
- Correction: the first three have no tool that does the job directly, but the
  fourth does, and an earlier commit message called all four tool-free. It is
  wrong. Writing that scenario is what turned up rename_many already sorting
  by modified time, so it was most of the way there.
- rename_many gains "digits": pad the number to a given width. It used to take
  the width from how many files there were, so seven files could only be 1-7
  and a person asking for "Wedding 001" got "Wedding 1" - which also sorts
  wrongly in Explorer once there are ten. digits=0 is the old behaviour, so
  nothing that worked before changes.
- All four jobs were put through run_script for real, on real files, and scored
  by those same checks: PASS on all four (7 photos in the order they were
  taken; one CSV per city with headers and 15 rows each; three correct SHA-256
  sums; "generator" and "power" found as the themes). That measures the tool on
  Linux, which is what this container can honestly measure. It is NOT a Windows
  pass and NOT a real-brain pass: whether the brain chooses to write a program
  for a job like this is still unmeasured.
- A code step now gets list_folder, read_file and check_file described along
  with the code tools (136 tokens). They were already reachable by name but
  without their arguments, so checking a script's work meant guessing a call
  or trusting the script's own print - which is the script's word, not a check.

## Unreleased — milestone 8 (design campaign, logo animation, lower third)

- make_campaign: one design in several sizes at once (Instagram post, portrait, story, landscape, X header, Facebook cover, A5, A4), saved into a new folder; each file is reopened, its size checked and its headline read back with OCR. Everyday words ("instagram story", "facebook cover", "poster") map to the sizes. Photoshop is used when installed (not tested: no Photoshop here).
- Flyers on very wide sizes size their type from the height, so the contact line stays inside the picture.
- make_motion_video gains two styles: logo (a ring draws itself, the name scales in, the tagline follows; the whole name always fits) and lower_third (a name and role bar that slides in and out, saved as a see-through .mov for any video editor). Both by S-CLAW's built-in maker; the After Effects template still covers promo styles only, and S-CLAW says so.
- Benchmark set v1.7: design-campaign and design-lower-third (not yet run).
- Build 46 is now the download behind the direct links (Windows, Linux, Mac and the brains).

## Unreleased — fixes from benchmark run 6

- A folder named in the request ("in the 'Decks' folder") is used when the brain leaves the folder out.
- Word reports and documents go to save_report. A missing Office or Adobe app's error names S-CLAW's own tool for the job.
- read_page takes a url.
- New recipe, use-calculator: type the whole sum, then read the display.

## Unreleased — milestone 7 (video and audio by code)

- New tools, all on PyAV (FFmpeg libraries already inside S-CLAW), each writing a new file that is reopened and measured:
  - reformat_video: 9:16, 1:1, 4:5 or 16:9, by cropping the middle or adding bars, keeping the sound;
  - find_black_frames;
  - cut_silence: silent gaps removed, adapted to the recording's own level;
  - normalize_audio: several recordings brought to one loudness, never clipping.
- numpy is now pinned explicitly (it was already installed with other packages).
- New benchmark set v1.6: a vertical version of a video.

## Unreleased — milestone 6 (web research), and the backend hang fixed

- New tool, compare_pages, collects the same facts from several pages (or the last search results) into a spreadsheet.
  - The brain reads each page's own text, marked as untrusted.
  - A value is kept only if that page actually states it; anything else becomes "not found on the page".
  - Every row links to its page.
- New tools:
  - check_links: finds broken links on pages.
  - page_changes: keeps a copy of a page and reports what changed since the last check.
- New benchmark set v1.5: three repair-shop pages served locally, so the answer is fixed.
- **Fixed: the 20-minute backend hangs** of benchmark runs 3 and 5. launch_app's pre-check called Windows UI Automation from the server's thread. Driver calls now always run on the desktop thread, and the Start-menu search runs off the server thread.
- "Save a clean copy" now protects the original, and a copy never takes the source's name.
- The benchmark harness waits for a busy backend instead of failing every later task.

## Unreleased — video licence option 1 carried out

- The installer now includes `resources/licenses`: the GPL and LGPL texts, x264's COPYING, a README of the components, THIRD_PARTY_NOTICES and S-CLAW's MIT licence.
- Each release now attaches S-CLAW-third-party-sources.zip, with the exact FFmpeg, x264 and x265 sources and the build recipe.

## Unreleased — reuse plan steps 6 and 7 (video licences, Blender)

- Step 6: THIRD_PARTY_NOTICES had the wrong licence for the bundled video library. PyAV's FFmpeg is LGPL-3.0+, and it ships libx264 and libx265, which are GPL-2.0+. It is now corrected, and the options are written up in docs/LICENSING_VIDEO.md. No code changed.
- Step 7: new tool, make_3d_render, uses Blender (free, optional, detected, never bundled):
  - a product turntable: a placeholder shape or the person's own .obj/.stl/.glb, spun on a pivot and rendered with Cycles on the CPU, then encoded to MP4 by S-CLAW and checked;
  - 3D lettering as a PNG.
  - The person's words enter the script only as JSON. Without Blender it says so and makes nothing.
- The real run was tested here with Blender 5.2.3 LTS (the bpy module): 24 frames at 960×540. That test runs when CLAW_TEST_BPY is set.

## Unreleased — reuse plan step 5: milestone 5 (Word and PowerPoint)

- New tool, make_presentation (python-pptx 1.0.2, MIT): a 16:9 deck with a dark cover, an accent bar, bullets, speaker notes and chart slides. It is reopened to check the slide count, every title, the notes and the charts.
- New tool, export_pdf: Word, PowerPoint or Excel to PDF through LibreOffice, when installed; the page count is checked. Without LibreOffice it says so.
- save_report: an optional real table-of-contents field, page numbers, and real bullet and numbered lists.
- New dependencies: python-pptx 1.0.2 (MIT) and XlsxWriter 3.3.1 (BSD-2, needed by python-pptx for charts).
- New benchmark set v1.4: a deck and a Word report.

## Unreleased — reuse plan step 4: milestone 4 (the computer)

- New tools:
  - list_startup_apps: registry Run keys and the Startup folders; read-only.
  - top_memory: read-only.
  - find_broken_shortcuts: .lnk, .url and dead links.
  - rename_many: numbering, old name or date; done in two steps so names never collide; refuses to overwrite.
  - archive_folder: a .zip that is reopened and checked by count and checksum.
- New "data" capability: the table tools moved out of "files", so each capability's tool list fits a small brain's window.
- The whole-catalogue view leaves out argument notes.

## Unreleased — reuse plan steps 2 and 3

- Step 2: type_text now reads the text back from the control that has focus, the way FlaUI and pywinauto do (UIA TextPattern, then ValuePattern, then the window text).
  - Matching text marks the step verified.
  - Garbled text fails, and the result says what the window shows.
  - A window that cannot be read stays "done, not checked".
- Benchmark set v1.3 adds two desktop tasks: Calculator, and Notepad typing that is read back.
- Step 3: `tools/kinds.py` is now the single answer to "does this tool only look, or does it make files?". It replaces three hand-kept lists that had drifted apart: compare_folders and table_totals were counted as work done.

## Unreleased — reuse plan step 1: the limits in a request

- `agent/constraints.py` reads "do not create files", "don't change…", "don't delete…" and "don't send…" from the request before planning.
- A request that contradicts itself (make a spreadsheet, but create no files) is answered with a question before anything runs. The result is marked "Needs you".
- The limits are written into the brain's instructions, and any step that breaks one is refused.
- This replaces the single no-files guard (challenge 17.06).

## Unreleased — milestone 3, part 2 (models)

- New tool, build_model, makes two kinds of workbook, each with a chart:
  - break-even: inputs, contribution, break-even units and sales, and a revenue/cost table, all as live formulas;
  - forecast: from numbers or a CSV/Excel column, using Excel's FORECAST.LINEAR so it updates with new actuals.
- New benchmark set v1.2 has three data challenges: break-even, forecast and chart. Set v1 is unchanged.
- docs/CHALLENGES.md numbers all 286 challenges from the owner's list and tracks them by evidence.

## Unreleased — fixes aimed at the baseline benchmark's failures

- Folders are found by name for saving, listing and searching ("Flyers" finds Documents\S-CLAW Bench\Flyers). If two folders share the name, S-CLAW asks rather than guess.
- New tools:
  - find_duplicate_files: compares file contents, not names.
  - compare_folders: lists files missing, added or changed between two folders.
- find_files: now takes a date range (modified_from, modified_to).
- Answers with a wrong sum are sent back to the brain with the correct arithmetic, worked out by Claw.

## Unreleased — milestone 3, part 1 (data)

- New tools: combine_tables (a folder of CSV/Excel files into one sheet, with a column for each row's source file), remove_duplicates (a clean copy, matched on email or phone with formats ignored; the original is untouched), table_totals (a total across files, optionally per group), add_chart (bar, line or pie, with live SUMIF totals that follow the data).
- All four read money as people write it (₦12,000, (300)), match columns loosely, and find a folder by its name inside the authorized folders.
- Each one writes a new file, reopens it and counts the rows before reporting.
- A new recipe, work-with-tables, guides the brain to these tools.

## Unreleased — milestone 1 (benchmark) and milestone 2 (honest report, resume)

- `docs/ROADMAP.md`: eleven milestones, done one at a time.
- `scripts/challenge_bench.py` and the "Challenge benchmark" workflow: 16 realistic challenges from the owner's list, each with objective checks and a score per brain. A false completion ("done" when the checks fail) costs the honesty points.
- Every task result now carries a report: done and checked / done, not checked / not finished / needs you. It is built from what Claw observed, not from the brain's summary, and is shown on the result card.
- A task that stopped (closed, crashed, failed, stopped) can "Carry on from where it stopped". The new attempt is told which steps were already done and checked, and not to repeat them.

## Unreleased — motion graphics

- New tool, make_motion_video, makes a short animated promo video. The content is the headline, up to five selling points, and a contact line. The options are 4–30 seconds; landscape, square or story; and a slide, pop or fade style.
- With After Effects installed, it works the way Adobe documents automation: it writes an ExtendScript (`AfterFX.exe -r`) that builds the composition with eased keyframes, saves an .aep project you can open, and renders an MP4 through the render queue. The brain only supplies the words and colours; the script comes from a fixed template. After Effects itself has not been run yet: there is none in the build workspace or on GitHub's machines.
- Without After Effects, Claw's built-in maker draws the frames with Pillow and encodes H.264 with PyAV. This was tested end to end: 1920×1080, 10 s, 300 frames, and OCR reads the headline back from the video.
- A new recipe, make-a-promo-video, and "promotional video" now picks the video tool instead of the flyer.

## Unreleased — S-CLAW's own identity

- S-CLAW now has its own identity and voice. Two files the owner can edit hold them: `persona/IDENTITY.md` and `persona/SOUL.md` in the data folder. They are created on first run and never overwritten. This follows OpenClaw's workspace files (MIT), including how it trims long ones.
- Questions about S-CLAW itself are answered from IDENTITY.md without asking the brain. Examples: "Who are you?", "Who made you?", "Are you ChatGPT?", "Which is the best claw?" (answer: S-CLAW, with its reasons). A small brain would otherwise say it is Qwen.
- Every task's instructions now carry the identity, so answers come from S-CLAW whatever brain it runs on.
- Claw catches "the next steps are ...", finishes a half-done Notepad job, and retries a refused guessed path in the person's own folder. A refusal now names the folders the brain may use.
- Each brain finds its own vision file when several share one folder.
- Brains are shown by S-CLAW's own names everywhere in the app: S-CLAW Tiny, Light, Standard and Pro brain. The model's family and the library it downloads from are no longer shown. The licence note stays on the release page and in THIRD_PARTY_NOTICES, as the licence requires.

## Unreleased — fixes from the first real install (Light brain)
### From Windows-MCP (MIT) and voice notes
- **Open any installed app, Store apps included:** `Get-StartApps` lists every Start-menu app with the ID
  Windows starts it by, so WhatsApp Desktop (a Store app with no shortcut file) now opens like Notepad or
  Photoshop. System tools stay refused. Ported from Windows-MCP's `get_apps_from_start_menu`.
- **Typing lands in the right window:** when Windows refuses to hand over the keyboard, Claw joins the input
  of the current and target windows first (Windows-MCP's `bring_window_to_top`).
- **Voice notes from the phone:** send a voice note to your Telegram bot; it is decoded (PyAV) and heard by
  Claw's offline recogniser on the computer, Claw replies "Heard: ...", and does it. Nothing is uploaded.
- WhatsApp stays on the official app (decided: no unofficial WhatsApp link, which risks a ban).
### The S-CLAW phone app (same Wi-Fi) and Linux / Mac
- **Phone app:** Settings → Phone → "Phone app on this Wi-Fi" shows a QR code. Scan it with the phone: chats,
  new tasks, following a task, Allow / Don't allow, Stop - in light and dark, with the living orb. Add it to
  the home screen to keep it as an app. A second small server answers only home-network addresses and only
  with the pairing key from the QR code (constant-time check); "Unpair all phones" makes a new key.
  Checked for real: the backend served it on its network address, refused a call without the key, and the
  page was screenshotted at phone size. (`claw/channels/phonelink.py`, `claw/channels/mobile/`; QR by segno, BSD.)
- **Linux and Mac:** desktop drivers (xdotool/wmctrl on X11; System Events on macOS) for windows, opening apps,
  typing, keys, screenshots, and clicks/scrolls on Linux. Reading controls inside apps stays Windows-only and
  says so. `scripts/build-release.sh` makes an AppImage or a dmg (brain downloaded on first start), and the
  "Build Linux and Mac" workflow builds both. The Linux driver was tested on a real X display.

### Give Claw tasks from your phone (OpenClaw's main idea)
- Settings → Phone: make a free Telegram bot with @BotFather, paste its token, pair your phone with a
  six-digit code. Then message the bot: Claw runs the task on the computer in its own chat, asks on the
  phone before anything that needs your OK (Allow / Don't allow buttons, or yes / no), and sends the result
  and file names back. /new, /status and /stop work. Only the paired phone can give orders; anyone else
  gets "This Claw is private." The token is masked like a model key. (`claw/channels/`; no new library.)
- Honest note: this needs a Telegram bot token, which is free but is something the person sets up once.
  Tested against a stand-in Telegram server, not the real one.
### Taken from OpenClaw (MIT), rewritten in Python
- **OpenClaw's way of working a web page:** `look_at_page` lists every button, link and box with a ref (e12),
  and `click`, `type_in` and `choose_option` act on a ref and hand back the page as it is afterwards
  (`claw/browser/snapshot.py`, from `pw-role-snapshot.ts`; Playwright's own `aria-ref` finds the element).
  S-CLAW's safety stays: password/card/code boxes refused, paying/deleting buttons treated as destructive,
  sending/submitting buttons ask first. Tested against the local test site in a real browser. Plus a
  `work-a-web-page` recipe.
- **Web search without the browser page:** OpenClaw's DuckDuckGo HTML-results reader (`claw/browser/ddg_html.py`)
  is used when the browser's results page gives nothing, which happened in the fifth Windows trial.
- **Nearly-right JSON from the brain:** OpenClaw's JSON repair (`claw/agent/jsonfix.py`), including its rule for
  Windows paths written with single backslashes, plus taking the JSON out of chatter or code fences.
- **Skills:** OpenClaw's SKILL.md format (`claw/agent/skills.py`). Claw picks the recipe that fits a request
  and puts it next to the task, because a 2B brain will not go and open one. Seven recipes ship for the
  everyday tasks (documents, flyers, spreadsheets, search-and-save, Notepad, copying, WhatsApp). Anyone can
  add their own in `%APPDATA%\S-CLAW\skills\<name>\SKILL.md`; instruction-only OpenClaw skills work as
  they are, and ones needing a program this computer lacks are skipped.
- Also from the fifth trial: a made-up flyer picture no longer stops the flyer at the pre-check either.
### The living orb and the quick bar
- The logo is now a living orb everywhere (title bar, home, Claw's replies, quick bar): colour fields turn and
  change shape inside a glassy sphere with the claw blades turning on top. It never stops; it speeds up while
  Claw works, turns warm when it needs you, and swells with your voice.
- The quick bar is a rounded capsule with a light ring circling its edge (faint idle, bright working, warm
  when waiting). Light and dark both checked by screenshot (`desktop/tests/showcase.mjs`).
### Third real-brain trial (run 41175294811)
- Now working end to end with the 2B brain: Notepad (type, save, reopen, verify), web search with title and
  URL, finding PDFs in Documents, open windows, calendar.
- Fixed from it: colour names in flyers, near-miss spreadsheet rows, argument shape shown after a rejection,
  "I will create…" sent back, example call in pushbacks.
### New layout (user: "change everything, the arrangement")
- A slim rail on the left (New, Chats, Docs, theme, Settings); chats slide out as a drawer and are remembered open or closed.
- Status (agent and brain) moved to the top right.
- Home: the logo, one question, the task box, six tiles of what Claw can do (Files, Web, Apps, WhatsApp,
  Calendar, Flyers; each fills in an example), and "Pick up where you left off" with the three latest chats.
- A task is split in two: the conversation on the left (your messages, Claw's question or answer, the files it
  made, the reply box docked at the bottom) and a live Steps panel on the right with a progress bar.
- While Claw thinks, its reply says so ("Thinking about how to do this…", then "Working on it").
### Second real-brain trial (run 41173224236)
- The brain asked for "Documents" (relative): refused as outside the authorized folders. Relative names now start
  at the authorized folder they name (traversal still refused).
- Three tasks hit the 120 s reply limit while a 2B brain on a CPU read the tool list. A local brain now gets
  10 minutes per reply, and when tools plainly fit the request only those are described in full.
- A finish with no steps and no summary, and "I will now save…" with no save tool named, are now sent back
  with the fitting tools named.
### Found by the real-brain trial on Windows (`real-trial.yml`, Qwen3-VL 2B, run 41171556944)
- Every file task failed with "no folders have been authorized": a fresh install had no folders at all.
  **Fixed:** a new install (or one that never had folders) is given Documents, Desktop and Downloads once
  (OneDrive's copies when Windows keeps them there). Removing them later sticks. Writing still asks first.
- The brain said "I will now proceed…" after one step and the task was reported **completed**. It also said it
  had no tool for a flyer, a spreadsheet and a copy with `make_flyer`, `create_spreadsheet` and `copy_files`
  in its list. **Fixed:** the tools that fit the request are named next to the task and described in full, and
  a finish that describes work still to do, or gives up for want of a tool that exists, is sent back (twice
  at most). Shown in the timeline as "Claw stopped too early, so it was told to carry on".
- Settings said the brain was ready when its last start had failed, so every task errored with a "ready"
  brain on screen. **Fixed:** status reports "Brain did not start" with the reason, and the task box shows it.
- "Finished" in green over a list of failures. **Fixed:** "Finished, but nothing worked" (red) or "Finished
  with problems" (amber).
### Reported by the user
- **Chats.** A retry or a follow-up stays in the same chat: one history entry with a message count, instead
  of a new entry with the same name each time. Titles are written by the brain while planning (2–6 words),
  with a cleaned-up fallback, not the request pasted back. Follow-ups are planned knowing the last three
  messages. New: `thread_id`/`title` on tasks (schema 5), `GET /tasks?thread=`, `thread_id` on `/tasks/run`.
- **Settings appeared to switch back.** Settings now re-reads what is saved each time it opens, and after
  saving checks that the chosen way of thinking was kept, saying so if it was not.
- **"Not connecting".** llama-server needs the Microsoft Visual C++ runtime, which many home PCs lack; the
  engine then dies before printing anything. The installer now ships the runtime DLLs next to the engine, and
  the two Windows exit codes for "DLL missing" and "processor not supported" are explained in plain words.
  (Likely cause, not yet confirmed on the user's PC.)
- The edition profile written by PowerShell has a byte-order mark; it is now read with `utf-8-sig` instead
  of failing and falling back.
### Changed
- Charcoal, chat-style window with the logo's periwinkle as the only accent (no uppercase labels, no card around
  every block; Claw's answer leads the result). The logo tile now follows the theme: its inline style was
  blocked by the page's CSP, so it was always a black square. Before that: your request on the right, Claw's steps and outcome as its reply, a reply box at
  the foot of each chat, a breathing edge while Claw works. Dark is now the default theme.

## Unreleased — Windows build on GitHub
### Added
- `.github/workflows/build-windows.yml`: builds the installer (with its brain) on GitHub's Windows machines,
  runs the backend tests on real Windows, smoke-tests the frozen backend, and publishes a GitHub Release.
- `backend/packaging/fetch_brain.py`: downloads a brain with Claw's own checked downloader for bundling.
- The installer stores brain files uncompressed (faster builds) and can be split into parts below 2 GB.

## Unreleased — v0.6 Phase D
### Added
- **make_flyer:** promotional flyers (headline, subtitle, up to 6 points, contact band, up to 4 pictures) in
  square, story, A5, A4 or landscape, as PNG, JPG, PDF (or PSD with Photoshop). Uses **Photoshop when it is
  installed** (its scripting interface), otherwise Claw's built-in editor, and always says which one made it.
  The result is reopened, its size checked, and the headline read back with OCR.
- **edit_image** (crop, rotate, resize, brightness, contrast, black-and-white, convert; saves a new file) and
  **inspect_image**.

## Unreleased — v0.6 Phase C
### Added
- **TechDesk sales through the app's screen:** "Open TechDesk and prepare a sale for two phone chargers"
  opens Sales → New Sale, searches each product, reads the real names and prices shown, sets quantities,
  and checks TechDesk's total against prices × quantities. Preparing never records anything.
- Ambiguous or missing products: Claw asks, listing what TechDesk shows. PIN screens: Claw stops.
- **Recording** is a separate step that always asks; it only goes ahead if the screen still shows the
  approved total, then looks for the sale in the Sales list and reports a receipt/invoice number only if
  TechDesk displays one. **Cancel** closes the form without recording.

## Unreleased — v0.6 Phase B
### Added
- **WhatsApp unread check** in the official WhatsApp Desktop app (UI Automation): chat names and
  unread counts, "new since the last check", optional short previews (off by default). It opens
  WhatsApp if needed and says clearly when WhatsApp isn't installed, isn't linked, is still loading,
  or can't be read. Message text is never stored.
- **Settings → Messages (WhatsApp):** reading permission (Ask me / Go ahead / Never), optional
  background check every 15/30/60 minutes (only with Go ahead, never opens WhatsApp itself), a
  notification when chats get new messages, and a "Check WhatsApp now" button.
- **Send a WhatsApp message:** always asks, exact chat name only, checks the message appeared.
- In WhatsApp, Telegram, Teams, Outlook, Slack, Discord, Signal and other messaging apps, pressing
  Enter or typing a new line counts as sending and always needs your OK.

## Unreleased — v0.6 Phase A
### Added
- Browser: **fill_field** (text, dropdowns, checkboxes; never passwords, cards or codes; never submits)
  and **download_file** (into an authorized folder; programs and scripts refused; never overwrites).
- Files: **copy_files** (by pattern or "only screenshots", into a new folder; checked by checksum;
  originals untouched) and **check_file** (reopen a file and compare its exact contents).
- Windows: **scroll**, **choose_menu** (File > Save As…; "Delete"-type items need your OK),
  **wait_for_window**; pop-up dialogs are reported after every action, and error-like dialogs mark
  the step as not done.
- Typing runs in short bursts, so Stop / Ctrl+Alt+X interrupts long typing quickly.
- `docs/AUDIT_V06.md` (feature matrix and plan) and `docs/WINDOWS_ACCEPTANCE.md` (real-Windows test steps).

## Unreleased — Batch 5 (part 1)
### Added
- User guide, developer guide, known issues list and release checklist.
- Security review and dependency audit (no known vulnerabilities).

## 0.5.0 — 2026-10-26 (scanned documents + built-in engine)
### Added
- **Documents view:** open PDF, Word, Excel or text files; live progress; each page shows whether
  its text came from the file or from a scan, with OCR confidence and rotation; unclear or unread
  pages flagged; search with jump-to-page; "Ask Claw about this document"; save a searchable copy
  of a scanned PDF (never overwrites).
- **OCR (Tesseract):** only pages without real text are OCR'd, at 300 DPI; sideways pages turned
  upright; results cached; English built in, other languages can be added; works without the brain.
- **Agent document tools:** read pages with labels, search, summarise in bounded chunks with page
  references, make a searchable PDF (asks first). Text from documents is treated as untrusted.
- **Claw's own engine:** llama.cpp `llama-server`, started and stopped by Claw on 127.0.0.1 with a
  per-launch key; memory check, load wait, crash restart, idle unload; stops if Claw is killed.
- **Brains:** Standard (Qwen3-VL 4B) and Pro (Qwen3-VL 8B), with screenshot vision. Settings shows
  engine status and lets you download (size, progress, cancel, resume; licence and checksum
  checked), switch, remove (with confirmation), use your own GGUF file, or restart the brain.
- **Packaging:** frozen backend (PyInstaller), electron-builder layout, Inno Setup script for the
  Standard and Pro installers, `build-release.ps1`; `setup.ps1` now fetches llama.cpp and Tesseract.
- Tests: OCR (16), agent + documents (3), engine/runtime (19), e2e +13 checks (52 total), packaged-app smoke (9).
### Changed
- Developer custom server defaults to an OpenAI-compatible (llama.cpp) server on port 8080.
- Malformed or cut-off brain replies are retried instead of failing the task as a server error.
### Removed
- **Ollama is no longer required** (kept only as an optional developer adapter). The automatic
  Ollama model manager was removed.

## 0.4.0 — 2026-10-26 (Batch 4)
### Added
- **Re-planning:** after two failed steps Claw works out why and makes a new plan (max 2 per task).
- **Documents:** read PDF, Word and Excel files; write text files; save reports (Word or Markdown)
  that may only cite pages/files Claw opened; create spreadsheets (Excel or CSV) with a check of
  how many values match what Claw read; edit text files with an automatic backup.
- **Prompt-injection guard:** content that tries to instruct Claw is flagged in the timeline and
  outcome; after it, every change needs your OK. After reading any web/file content, changes
  outside the computer need your OK even if allowed in Settings.
- **Recovery:** the app restarts the agent if it crashes (up to 3 times in 5 minutes); interrupted
  tasks are marked; "Run this task again" on finished tasks.
- **Outcome card:** files Claw made, with Open and Show in folder (only files from that task).
- History search also finds words in Claw's answers and errors.
- Shorter prompts: full tool details only for the capabilities a plan needs.
### Removed
- Online mode and the Google key screen. Claw uses its built-in brain only.

## 0.3.0 — 2026-10-25 (Batch 3 + brain choice)
### Added
- **Claw's brain, chosen once on a welcome screen:** Online (Google Gemini with the user's own
  free key; Claw picks the model and falls back when a daily limit is hit) or Offline (Claw
  measures the computer, picks models by role, downloads them with progress, unloads when idle).
  No model picking for users. Key stored encrypted with Windows DPAPI.
- **Desktop control (Windows UI Automation via pywinauto):** list/switch windows, open apps from
  the Start menu (system tools refused), numbered controls, click/type/keys with before-and-after
  checks, screenshots, "look at the screen" through the brain, click-at-position fallback.
- **File tools:** list folders, read text files, find files, all within authorized folders.
- Buttons labelled Send/Delete/Buy/Pay/Submit/Post… always ask, in apps and on web pages.
- Global stop shortcut **Ctrl+Alt+X**; quick bar shows it while Claw uses the mouse and keyboard.
- Locked-screen and admin-window cases reported clearly.
### Changed
- Model settings moved to Settings → Claw's brain → Developer.

## 0.2.1 — 2026-10-25 (interface redesign + background mode)
### Added
- Redesigned main window: custom title bar, grouped task list, large task box with example
  tasks, timeline of steps, docked approval sheet, outcome card; light and dark themes.
- Quick bar: always-on-top pill at the top of the screen; click or press Ctrl+Shift+Space,
  type a task, press Enter. Shows live activity, "Needs your OK", and a stop button.
- Tray icon with status (idle / working / needs you) and menu: open, new task, stop, show
  quick bar, start with Windows, quit. Closing the window keeps Claw running.
- Desktop notifications when a task finishes or needs approval (click opens the task).
- Keeps the computer awake while a task runs (setting).
- Start with Windows (setting; launches hidden in the tray).
- App and tray icons; bundled Manrope font.

## 0.2.0 — 2026-10-25 (Batch 2)
### Added
- Tool system with schemas, risk levels, validation and pre-checks (13 tools).
- Browser control through Playwright with a dedicated profile (Edge default on Windows):
  web search, open address/result, read page, links, follow link, click button, tabs.
- Browser-history search (titles/addresses only, always asks or off).
- `save_links` to authorized folders (no overwrite, only links seen in the task).
- Executor loop and background runner: Run, Stop, approvals, limits, retries, audit events.
- UI: Run task, live activity, approval card, Stop, outcome summary, browser/limits settings.
- Database v2 with migration; unfinished tasks marked interrupted after restart.
- Local test website and 29 new backend tests; e2e test extended to 18 checks.
### Changed
- Ctrl+Enter now runs the task; "Plan only" is a separate button.

## 0.1.0 — 2026-10-25 (Batch 1)
### Added
- Repository audit and architecture decision (custom Electron + Python runtime).
- Python backend: settings with validation and readable errors, health check,
  Ollama and llama.cpp (OpenAI-compatible) adapters, model status/probe,
  task planner with schema-validated JSON and one corrective retry,
  permission policy with risk levels and folder scoping, SQLite history and
  audit events, JSON logging with secret redaction.
- Electron desktop app: starts the backend with a per-launch token, route
  allowlist, sandboxed UI with task input, Plan button, progress, results,
  history search, settings drawer (model, permissions, folders), error banner.
- Windows scripts: setup, start, check. Linux check script.
- Tests: 46 backend, 2 desktop unit, 12-check end-to-end.

### Not included yet
- No step is executed; plans are proposals only.
