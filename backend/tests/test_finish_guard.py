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
