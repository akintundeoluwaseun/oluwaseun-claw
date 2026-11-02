"""A finish that is not one is sent back to the model (seen with the 2B brain on Windows).

The real-brain trial reported "completed" for a Notepad task after only opening Notepad
("I will now proceed with these steps"), and for a flyer and a spreadsheet the brain said
it had no tool for, with make_flyer and create_spreadsheet in its list. Replies are
scripted here (TEST DOUBLE); the trial itself runs on Windows with the real brain.
"""

import json

from claw.agent.executor import fitting_tools, premature_finish
from claw.tools.registry import build_registry
from tests.conftest import VALID_PLAN
from tests.test_api import settings_for
from tests.test_chats import finish, wait_done


def test_the_tools_that_fit_are_named():
    r = build_registry()
    assert fitting_tools("Make a promotional flyer for my software TechDesk", r) == ["make_flyer"]
    assert fitting_tools("Create a spreadsheet of five states and their capitals", r) == ["create_spreadsheet"]
    assert fitting_tools("Copy sales.csv from Documents into a new folder called Backup", r)[:2] == ["copy_files", "create_folder"]
    assert fitting_tools("hello there", r) == []


def test_premature_finishes_are_recognised_and_real_ones_are_not():
    assert premature_finish("Notepad has been opened. I will now proceed with these steps.", [{"outcome": "verified"}], [])
    assert premature_finish("The necessary tools are not available in the list of tools provided.", [], ["create_spreadsheet"])
    assert premature_finish("I cannot make a flyer.", [], ["make_flyer"])
    assert premature_finish("There are no calendars on this computer yet.", [{"outcome": "verified"}], ["list_events"]) is None
    assert premature_finish("Saved flyer.png in Documents.", [{"outcome": "verified"}], ["make_flyer"]) is None


def test_a_premature_finish_is_sent_back_and_the_task_carries_on(make_client, fake_server):
    fake_server.replies += [json.dumps(VALID_PLAN), finish("Notepad has been opened. I will now proceed with these steps."),
                            finish("Done: the file was written and checked.")]
    c = make_client(settings_for(fake_server)).__enter__()
    tid = c.post("/tasks/run", json={"task": "Write a note for me"}).json()["id"]
    assert wait_done(c, tid) == "completed"
    kinds = [e["kind"] for e in c.get(f"/tasks/{tid}/events").json()["events"]]
    assert "pushed_back" in kinds
    assert c.get(f"/tasks/{tid}").json()["result"]["final_answer"].startswith("Done")


def test_pushback_is_limited_so_a_stubborn_model_still_ends(make_client, fake_server):
    stubborn = finish("I will now proceed.")
    fake_server.replies += [json.dumps(VALID_PLAN), stubborn, stubborn, stubborn]
    c = make_client(settings_for(fake_server)).__enter__()
    tid = c.post("/tasks/run", json={"task": "Write a note for me"}).json()["id"]
    assert wait_done(c, tid) == "completed"
    kinds = [e["kind"] for e in c.get(f"/tasks/{tid}/events").json()["events"]]
    assert kinds.count("pushed_back") == 2


def test_near_miss_arguments_from_the_third_trial_are_accepted():
    from claw.tools.document_tools import SheetArgs
    from claw.tools.image_tools import FlyerArgs

    rows = SheetArgs.model_validate({"file_name": "states", "columns": ["State", "Capital"],
                                     "rows": [{"State": "Lagos", "Capital": "Ikeja"}, "Oyo, Ibadan"]}).rows
    assert rows == [["Lagos", "Ikeja"], ["Oyo", "Ibadan"]]
    f = FlyerArgs.model_validate({"title": "TechDesk", "background": "dark blue", "accent": "rainbow"})
    assert f.background == "#14213d" and f.accent == "#3cc2aa"


def test_i_will_create_is_not_a_finish():
    assert premature_finish("I will create a new folder named Backup and copy the file.", [], ["copy_files"])


def test_claw_reads_the_named_pdf_when_the_brain_will_not_start():
    from claw.agent.executor import obvious_first_step

    a = obvious_first_step("Read invoice.pdf in my Documents folder and tell me the total amount due.",
                           ["read_document_pages", "summarize_document"])
    assert a.tool == "read_document_pages" and a.args == {"path": "Documents/invoice.pdf", "first_page": 1}
    assert obvious_first_step("Copy sales.csv into Backup", ["copy_files"]) is None   # changes things: never forced


def test_a_refusing_brain_gets_the_first_read_done_for_it(make_client, fake_server, tmp_path):
    import json as _json

    refuse = finish("I cannot read PDF files.")
    fake_server.replies += [_json.dumps(VALID_PLAN), refuse, refuse, refuse, finish("The file could not be read.")]
    c = make_client(settings_for(fake_server)).__enter__()
    tid = c.post("/tasks/run", json={"task": "Read invoice.pdf and tell me the total"}).json()["id"]
    wait_done(c, tid)
    events = c.get(f"/tasks/{tid}/events").json()["events"]
    kinds = [e["kind"] for e in events]
    assert kinds.count("pushed_back") == 2 and "started_for_brain" in kinds
    assert any(e["kind"] == "requested" and e["data"]["tool"] == "read_document_pages" for e in events)


def test_fourth_trial_near_misses():
    from claw.agent.executor import obvious_first_step

    r = build_registry()
    assert r.get("list_folder").parse_args({"path": "Documents"}).folder == "Documents"   # "path" for "folder"
    t = "Copy sales.csv from Documents into a new folder called Backup."
    a = obvious_first_step(t, fitting_tools(t, r), [{"tool": "create_folder", "outcome": "verified"}])
    assert a.tool == "copy_files" and a.args == {"source_folder": "Documents", "pattern": "sales.csv", "destination_folder": "Backup"}
    web = "Search the web for free video editors, open a good result, and save its title and URL."
    f = fitting_tools(web, r)
    assert f[0] == "web_search" and "save_links" in f
    assert "nothing has been saved" in premature_finish("Title: X, URL: Y", [{"tool": "web_search", "outcome": "verified"}], f, wants_save=True)
    # a failed last step with "I will try again" is an honest end, not a premature one
    assert premature_finish("WhatsApp didn't open. I will try again later.", [{"tool": "check_whatsapp", "outcome": "failed"}], ["check_whatsapp"]) is None


def test_asked_for_five_rows_and_made_two_is_sent_back():
    steps = [{"tool": "create_spreadsheet", "outcome": "verified", "detail": "Created states.xlsx with 2 row(s) and 2 column(s)."}]
    why = premature_finish("Done.", steps, ["create_spreadsheet"], task="Create a spreadsheet of five Nigerian states and their capitals")
    assert why and "five" not in why and "5" in why
    assert premature_finish("Done.", steps, ["create_spreadsheet"], task="Create a spreadsheet of two states") is None


def test_builtin_skills_fit_the_everyday_tasks():
    from claw.agent import skills

    ss = skills.load(skills.BUILTIN)
    assert skills.pick("Make a promotional flyer for my software TechDesk", ss).name == "make-a-flyer"
    assert skills.pick("Read invoice.pdf and tell me the total", ss).name == "read-a-document"
    assert skills.pick("What is on my calendar today?", ss) is None


def test_a_persons_own_skill_and_openclaw_format(tmp_path):
    from claw.agent import skills

    (tmp_path / "shop-prices").mkdir()
    (tmp_path / "shop-prices" / "SKILL.md").write_text(
        "---\nname: shop-prices\ndescription: Answer questions about laptop repair prices in my shop\n---\nScreen: 25,000 naira.\n")
    (tmp_path / "needs-brew.md").write_text(
        '---\nname: summarize\ndescription: summarize things\nmetadata: {"openclaw": {"requires": {"bins": ["no-such-program-xyz"]}}}\n---\nRun it.\n')
    ss = skills.load(skills.BUILTIN, tmp_path)
    names = {s.name for s in ss}
    assert "shop-prices" in names and "summarize" not in names
    assert skills.pick("How much is laptop screen repair in my shop?", ss).name == "shop-prices"


async def test_flyer_with_a_made_up_picture_is_still_made(tool_ctx):
    from claw.tools.image_tools import FlyerArgs, check_flyer

    check_flyer(FlyerArgs(title="TechDesk", images=["logo.png"]), tool_ctx)   # no error


def test_sixth_trial_near_misses():
    from claw.agent.executor import closest_tool

    r = build_registry()
    assert closest_tool("open_page", r) == "open_url" and closest_tool("web_serch", r) == "web_search"
    assert closest_tool("launch_rocket", r) is None
    twelve = [{"tool": "create_spreadsheet", "outcome": "verified", "detail": "Created states.xlsx with 12 row(s)"}]
    assert "exactly 5" in premature_finish("Done.", twelve, ["create_spreadsheet"], task="Create a spreadsheet of five states")
    rejected = [{"tool": "web_search", "outcome": "verified"}, {"tool": "open_page", "outcome": "rejected"}]
    assert "nothing has been saved" in premature_finish("Title X URL Y", rejected, ["save_links"], wants_save=True)


def test_quote_relevant_lines_for_a_silent_brain():
    from claw.agent.executor import quote_relevant_lines

    doc = "INVOICE 2041\nCustomer: Ekiti Grand Hotel\nSubtotal: 45,000\nTotal amount due: 48,500 naira\nThank you"
    q = quote_relevant_lines("Read invoice.pdf in my Documents folder and tell me the total amount due.", doc)
    assert "Total amount due: 48,500 naira" in q and "Thank you" not in q


def test_open_notepad_is_the_obvious_first_step():
    from claw.agent.executor import obvious_first_step

    t = "Open Notepad, type 'S-CLAW desktop-control test', save it as claw-test.txt in Documents"
    a = obvious_first_step(t, fitting_tools(t, build_registry()))
    assert a.tool == "launch_app" and a.args == {"name": "Notepad"}


def test_a_spelled_out_notepad_job_is_carried_through():
    from claw.agent.executor import obvious_first_step

    t = "Open Notepad, type 'S-CLAW desktop-control test', save it as claw-test.txt in Documents, reopen it, and verify the exact contents."
    f = fitting_tools(t, build_registry())
    ok = lambda tool: {"tool": tool, "outcome": "verified"}
    assert obvious_first_step(t, f, []).tool == "launch_app"
    assert obvious_first_step(t, f, [ok("launch_app")]).args == {"text": "S-CLAW desktop-control test"}
    w = obvious_first_step(t, f, [ok("launch_app"), {"tool": "type_text", "outcome": "done_unverified"}])
    assert w.tool == "write_text_file" and w.args == {"file_name": "claw-test.txt", "text": "S-CLAW desktop-control test", "folder": "Documents"}
    c = obvious_first_step(t, f, [ok("launch_app"), ok("type_text"), ok("write_text_file")])
    assert c.tool == "check_file" and c.args["path"] == "Documents/claw-test.txt"
    assert obvious_first_step(t, f, [ok("launch_app"), ok("type_text"), ok("write_text_file"), ok("check_file")]) is None


def test_next_steps_are_counts_as_unfinished():
    # Release check, 1 Nov: Light opened Notepad and said "The next steps are to type ...".
    from claw.agent.executor import _STILL_TO_DO, _unfinished_recipe

    final = "Notepad has been opened. The next steps are to type 'S-CLAW release check', save it ..."
    assert _STILL_TO_DO.search(final)
    t = "Open Notepad, type 'S-CLAW release check', save it as release-check.txt in Documents, reopen it, and verify the exact contents."
    assert _unfinished_recipe(t, [{"tool": "launch_app", "outcome": "verified"}])
    assert not _unfinished_recipe(t, [{"tool": "launch_app", "outcome": "verified"},
                                      {"tool": "write_text_file", "outcome": "verified"},
                                      {"tool": "check_file", "outcome": "verified"}])
    assert not _unfinished_recipe(t, [{"tool": "launch_app", "outcome": "verified"},
                                      {"tool": "type_text", "outcome": "denied"}])


def test_a_refused_guessed_path_is_retried_in_the_persons_folder():
    # Release check, 1 Nov: Pro asked for C:\Users\Public\Documents\invoice.pdf and gave up.
    from claw.agent.executor import _unfinished_recipe, obvious_first_step

    t = "Read invoice.pdf in my Documents folder and tell me the total amount due."
    refused = {"tool": "read_document_pages", "args": {"path": "C:\\Users\\Public\\Documents\\invoice.pdf"},
               "outcome": "failed", "detail": "Access to 'C:\\Users\\Public\\Documents\\invoice.pdf' is not allowed: "
                                              "it is outside the folders you authorized. The folders you can use are: ..."}
    assert _unfinished_recipe(t, [refused])
    a = obvious_first_step(t, fitting_tools(t, build_registry()), [refused])
    assert a.tool == "read_document_pages" and a.args == {"path": "Documents/invoice.pdf", "first_page": 1}
    tried = {"tool": "read_document_pages", "args": {"path": "Documents/invoice.pdf"}, "outcome": "failed",
             "detail": "Access to 'Documents/invoice.pdf' is not allowed: it is outside the folders you authorized."}
    assert not _unfinished_recipe(t, [refused, tried])


def test_refusal_names_the_folders_that_can_be_used(tmp_path):
    from claw.permissions.policy import PathNotAuthorized, PermissionPolicy

    docs = tmp_path / "Documents"
    docs.mkdir()
    pol = PermissionPolicy({}, [str(docs)])
    try:
        pol.check_path(tmp_path / "elsewhere" / "invoice.pdf")
    except PathNotAuthorized as e:
        assert str(docs) in str(e) and "'Documents/<file name>'" in str(e)
    else:
        raise AssertionError("should be refused")


def test_amounts_keep_the_documents_currency():
    from claw.agent.executor import match_money

    doc = "INVOICE\nSubtotal 500.00\nTOTAL DUE 580.50\nPaid by card: $100.00"
    assert match_money("The total amount due is £580.50.", doc) == "The total amount due is 580.50."
    assert match_money("You paid $100.00.", doc) == "You paid $100.00."
    assert match_money("It costs €12.", doc) == "It costs €12."          # not in the document: left alone
    assert match_money("Due: ₦48,500", "Total amount due: ₦48,500 naira") == "Due: ₦48,500"


def test_a_saved_but_unchecked_notepad_job_is_not_finished():
    # Release check, 1 Nov: Light saved the file, called a wrong tool and said "I will retry".
    from claw.agent.executor import _STILL_TO_DO, _unfinished_recipe, obvious_first_step

    assert _STILL_TO_DO.search("The provided arguments were invalid. I will retry with the correct parameters.")
    t = "Open Notepad, type 'S-CLAW release check', save it as release-check.txt in Documents, reopen it, and verify the exact contents."
    steps = [{"tool": "launch_app", "outcome": "verified"}, {"tool": "type_text", "outcome": "done_unverified"},
             {"tool": "write_text_file", "outcome": "verified"}, {"tool": "open_search_result", "outcome": "rejected"}]
    assert _unfinished_recipe(t, steps)
    c = obvious_first_step(t, fitting_tools(t, build_registry()), steps)
    assert c.tool == "check_file" and c.args["path"] == "Documents/release-check.txt"
    assert not _unfinished_recipe(t, steps + [{"tool": "check_file", "outcome": "verified"}])


def test_a_wrong_sum_in_the_answer_is_sent_back():
    # Baseline benchmark, 2 Nov: "The total in quote.txt is correct: 300,000 (Design: 200,000 + Hosting: 50,000)."
    from claw.agent.executor import arithmetic_slip, premature_finish
    bad = "The total in quote.txt is correct: 300,000 (Design: 200,000 + Hosting: 50,000)."
    msg = arithmetic_slip(bad)
    assert msg and "250,000" in msg and "300,000" in msg
    assert premature_finish(bad, [{"tool": "read_file", "outcome": "verified"}], ["read_file"]) == msg
    assert arithmetic_slip("No: 200,000 + 50,000 = 250,000, so the total of 300,000 is wrong.") is None
    assert arithmetic_slip("The total is 48,500 (12,000 + 8,000 + 15,000 + 4,000 + 6,000 + 3,500).") is None
    assert arithmetic_slip("Call 0803 000 0000 + bring your receipt.") is None


async def test_duplicates_dates_and_folder_comparison(tool_ctx):
    import os
    import time
    from pathlib import Path
    from tests.test_phase_a import call
    root = Path(tool_ctx.settings.permissions.authorized_folders[0]) / "S-CLAW Bench"
    d = root / "Photos dump"
    d.mkdir(parents=True)
    (d / "IMG_0041.jpg").write_bytes(b"beach" * 50)
    (d / "beach copy.jpg").write_bytes(b"beach" * 50)
    (d / "IMG_0042.jpg").write_bytes(b"market" * 50)
    r = await call(tool_ctx, "find_duplicate_files", folder="Photos dump")
    assert len(r.data["groups"]) == 1 and "IMG_0041.jpg = beach copy.jpg" in r.summary.replace("beach copy.jpg = IMG_0041.jpg", "IMG_0041.jpg = beach copy.jpg")
    rep = root / "Reports"
    rep.mkdir()
    for name, day in (("jan.docx", "2026-01-15"), ("march.docx", "2026-03-10"), ("april.docx", "2026-04-02")):
        (rep / name).write_text("x")
        t = time.mktime(time.strptime(day, "%Y-%m-%d"))
        os.utime(rep / name, (t, t))
    r = await call(tool_ctx, "find_files", folder="Reports", modified_from="2026-03-01", modified_to="2026-03-31")
    assert [Path(f["path"]).name for f in r.data["files"]] == ["march.docx"]
    w = root / "Website"
    (w / "Site v1").mkdir(parents=True)
    (w / "Site v2").mkdir()
    for n, t in (("index.html", "home"), ("about.html", "about"), ("contact.html", "c")):
        (w / "Site v1" / n).write_text(t)
    (w / "Site v2" / "index.html").write_text("home")
    (w / "Site v2" / "about.html").write_text("about us")
    r = await call(tool_ctx, "compare_folders", first="Site v1", second="Site v2")
    assert r.data["missing_from_second"] == ["contact.html"] and r.data["changed"] == ["about.html"]
