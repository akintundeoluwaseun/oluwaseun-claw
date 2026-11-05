"""The tool list a small brain reads, in the order it reads it.

A quarter of everything a 2B brain can read is the tool catalogue, and it was
in registry order - whatever order the tools happened to be registered in. For
"make a promotional flyer", make_flyer was ninth of twenty, behind
find_black_frames and cut_silence. The brain reads from the top.

Ordering never hides anything: a tool that loses its place keeps its full
entry. Only going over CATALOGUE_BUDGET reduces the least relevant tools to
names, and they stay callable - calling one with the wrong arguments returns
its shape, as it always did.
"""

from claw.agent.executor import (
    CATALOGUE_BUDGET, MIN_DETAILED, estimate_tokens, fitting_tools, tool_catalogue, tool_relevance,
)
from claw.tools.registry import build_registry

REG = build_registry()


def detailed(text):
    return [l[2:].split("(")[0] for l in text.splitlines() if l.startswith("- ")]


def named(text):
    last = text.splitlines()[-1]
    if not last.startswith("Also available"):
        return []
    return [n.strip() for n in last.split(":", 1)[1].split(",")]


# ---------- the score ----------
def test_a_word_in_the_name_counts_for_more_than_one_in_the_description():
    flyer = REG.get("make_flyer")
    report = REG.get("save_report")
    task = "Make a promotional flyer and save it"
    assert tool_relevance(task, flyer) > tool_relevance(task, report)


def test_a_request_with_no_useful_words_scores_nothing():
    assert tool_relevance("", REG.get("make_flyer")) == 0.0
    assert tool_relevance("the and for with", REG.get("make_flyer")) == 0.0


# ---------- the ordering ----------
def test_the_tool_for_the_job_comes_first():
    """A request naming one job puts that job's tool at the top."""
    for task, cap, want in (
        ("Make a promotional flyer for my business and save it in Documents", "documents", "make_flyer"),
        ("Combine these five CSV files and remove duplicates", "data", "combine_tables"),
        ("Put Friday's team call in my calendar", "organiser", "create_event"),
    ):
        order = detailed(tool_catalogue(REG, {cap}, task=task))
        assert order[0] == want, f"{task!r} put {order[0]} before {want}: {order[:4]}"


def test_a_request_naming_two_jobs_brings_both_to_the_top():
    # "Open Notepad and type my shopping list" needs launch_app AND type_text.
    # Relevance measures how well a tool matches the words, not which step comes
    # first, so asserting an order between two tools the task genuinely needs
    # would be asserting a coincidence. Both at the top is the real property.
    order = detailed(tool_catalogue(REG, {"desktop"}, task="Open Notepad and type my shopping list"))
    assert set(order[:2]) == {"launch_app", "type_text"}, order[:4]


def test_the_case_the_keyword_matcher_misses():
    # fitting_tools has no pattern for this, so the whole capability is sent and
    # the order is all the brain has to go on.
    task = "Find every PDF in my Documents folder and list them by date"
    assert fitting_tools(task, REG) == [], "this test is about the case with no curated match"
    order = detailed(tool_catalogue(REG, {"files"}, task=task))
    assert "find_files" in order[:3], order[:5]


def test_ordering_alone_removes_nothing():
    for cap in ("files", "browser", "data", "desktop", "organiser", "design"):
        task = "Find every PDF in my Documents folder and list them by date"
        before = set(detailed(tool_catalogue(REG, {cap})))
        after = tool_catalogue(REG, {cap}, task=task)
        assert before == set(detailed(after)) | (set(named(after)) & before), cap


def test_without_a_task_the_catalogue_is_exactly_what_it_was():
    for cap in ("files", "browser", "documents", "data"):
        assert tool_catalogue(REG, {cap}) == tool_catalogue(REG, {cap}, task="")


# ---------- the budget ----------
def test_a_capability_over_budget_degrades_instead_of_blocking_everything():
    task = "Make a promotional flyer for my business and save it in Documents"
    full = tool_catalogue(REG, {"documents"})
    trimmed = tool_catalogue(REG, {"documents"}, task=task)
    assert estimate_tokens(full) > CATALOGUE_BUDGET, "documents is no longer the over-budget one"
    assert estimate_tokens(trimmed) <= CATALOGUE_BUDGET
    # what was dropped is the least relevant, and still callable by name
    assert detailed(trimmed)[0] == "make_flyer"
    assert "cut_silence" in named(trimmed) and "find_black_frames" in named(trimmed)


def test_nothing_is_lost_when_the_budget_bites():
    task = "Make a promotional flyer for my business and save it in Documents"
    trimmed = tool_catalogue(REG, {"documents"}, task=task)
    docs = {s.name for s in REG.all() if s.capability.value == "documents"}
    assert docs <= set(detailed(trimmed)) | set(named(trimmed))


def test_the_brain_is_never_left_with_a_handful_of_tools():
    task = "Make a promotional flyer for my business and save it in Documents"
    assert len(detailed(tool_catalogue(REG, {"documents"}, task=task))) >= MIN_DETAILED


def test_a_curated_match_is_never_trimmed_away():
    task = "Make a promotional flyer for my business and save it in Documents"
    for name in fitting_tools(task, REG):
        assert name in detailed(tool_catalogue(REG, {"documents"}, task=task)), name


def test_every_capability_still_fits_the_window_it_has_to_fit():
    for cap in ("files", "data", "documents", "organiser", "desktop", "browser"):
        task = "Make a promotional flyer for my business and save it in Documents"
        assert estimate_tokens(tool_catalogue(REG, {cap}, task=task)) < 2000, cap
