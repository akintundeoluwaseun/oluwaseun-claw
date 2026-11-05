"""Challenge 17.18: compare the final output against the original request.

Every other part of the final report describes what Claw did. This part asks
the question the person actually cares about - did I get what I asked for? -
and answers it from the files on disk, so the brain cannot satisfy it by
saying yes.

Deliberately narrow. A request that names the file it wants, the folder it
wants it in, or the format it wants it in has said something a saved file
either satisfies or does not. Anything vaguer ("make it nice") is not checked,
because a guess in this list would be the same confident wrongness the rest of
the report exists to prevent.
"""

from claw.agent.report import final_report, unmet_requirements


def f(path, verified=True):
    return {"path": path, "verified": verified}


# ---------- a named file ----------
def test_a_file_saved_under_the_wrong_name_is_reported():
    got = unmet_requirements("Make a flyer and save it as promo.png", [f("/u/Documents/flyer.png")])
    assert got and "promo.png" in got[0] and "flyer.png" in got[0]


def test_the_right_name_says_nothing():
    assert unmet_requirements("Make a flyer and save it as promo.png", [f("/u/Documents/promo.png")]) == []


def test_the_name_is_matched_whatever_the_case():
    assert unmet_requirements("save it as Report.PDF", [f("/u/Documents/report.pdf")]) == []


def test_a_named_file_and_nothing_saved_at_all():
    got = unmet_requirements("call it budget.xlsx", [])
    assert got and "no file was saved" in got[0]


# ---------- a named folder ----------
def test_the_wrong_folder_is_reported():
    got = unmet_requirements("Summarise it and save it in Documents", [f("/u/Downloads/summary.docx")])
    assert got and "Documents" in got[0] and "Downloads" in got[0]


def test_the_right_folder_says_nothing():
    assert unmet_requirements("save it in Documents", [f("/u/Documents/summary.docx")]) == []


def test_a_folder_requirement_with_no_files_is_not_reported_twice():
    # Nothing was saved; the named-file rule covers that, and a second line
    # about the folder would be noise.
    assert unmet_requirements("save it in Documents", []) == []


# ---------- a named format ----------
def test_the_wrong_format_is_reported():
    got = unmet_requirements("Export the sales figures as a PDF", [f("/u/Documents/sales.xlsx")])
    assert got and "pdf" in got[0].lower() and "sales.xlsx" in got[0]


def test_the_right_format_says_nothing():
    for task, name in (("Export it as a PDF", "sales.pdf"),
                       ("Give me the totals as a spreadsheet", "totals.xlsx"),
                       ("Write it up as a Word document", "notes.docx"),
                       ("Make it as a presentation", "deck.pptx")):
        assert unmet_requirements(task, [f(f"/u/Documents/{name}")]) == [], task


def test_a_format_word_that_is_not_a_format_is_ignored():
    # "as a test", "as a favour" - not formats, nothing to check.
    assert unmet_requirements("Do it as a test", [f("/u/Documents/x.txt")]) == []


# ---------- saying nothing when nothing was asked ----------
def test_a_request_with_no_stated_output_is_not_second_guessed():
    for task in ("Tell me what is in my Downloads folder", "hi",
                 "Find every PDF and list them by date", "What can you do?"):
        assert unmet_requirements(task, []) == [], task
        assert unmet_requirements(task, [f("/u/Documents/out.txt")]) == [], task


def test_only_the_first_line_of_a_long_request_is_read():
    # The rest is usually pasted context, not the instruction.
    task = "Save it as promo.png\nHere is some text mentioning budget.xlsx for reference"
    assert unmet_requirements(task, [f("/u/Documents/promo.png")]) == []


# ---------- in the report ----------
def test_the_report_carries_it_under_incomplete():
    rep = final_report(
        steps=[{"tool": "make_flyer", "outcome": "verified", "detail": "made a flyer"}],
        files=[f("/u/Documents/flyer.png")],
        status="completed",
        task="Make a flyer and save it as promo.png",
    )
    assert rep["completed"], "the work that was done is still reported"
    assert any("promo.png" in line for line in rep["incomplete"]), rep


def test_a_report_without_a_task_still_works():
    # Every existing caller that does not pass the request keeps working.
    rep = final_report([{"tool": "make_flyer", "outcome": "verified"}], [f("/u/x.png")], "completed")
    assert rep["completed"] and rep["incomplete"] == []


# ---------- the two regex bugs this check had, found by probing it ----------
def test_a_request_that_starts_with_the_verb_is_matched():
    # The verbs were case-sensitive, so "Save it in Downloads" - the way a
    # request is normally written - never matched at all.
    got = unmet_requirements("Save it in Downloads", [f("/u/Documents/out.txt")])
    assert got and "Downloads" in got[0]
    assert unmet_requirements("Export the chart to my Desktop", [f("/u/Documents/c.png")])


def test_a_filename_between_the_verb_and_the_folder_does_not_break_it():
    # The gap excluded every full stop, so "sales.csv" cut the match in half.
    assert unmet_requirements("Copy sales.csv into Backup", [f("/u/Documents/sales.csv")])
    assert unmet_requirements("Copy sales.csv into Backup", [f("/u/Backup/sales.csv")]) == []


def test_the_claim_does_not_run_past_the_end_of_a_sentence():
    # "Save the report. Tell me what is in Downloads" is two sentences, and the
    # second is a question, not a destination.
    assert unmet_requirements("Summarise the report. Tell me what is in Downloads",
                              [f("/u/Documents/s.docx")]) == []
