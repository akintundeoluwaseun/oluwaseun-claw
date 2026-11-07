"""What the model is actually shown about each tool.

Two findings sit behind this file:

1. Five sixths of the catalogue was JSON Schema boilerplate — `maxLength`,
   `minLength`, `additionalProperties`, `anyOf [..., null]` — none of which
   helps a model choose a tool. Measured: 5,421 characters of description
   against 27,046 of schema across the 76 tools.
2. The function that removed JSON Schema's "title" annotations also removed any
   *argument* called `title`. Ten tools have one, and `create_event` requires
   it, so the model was asked for an argument it was never shown.
"""

import json

from claw.agent.executor import MIN_DETAILED, compact_args, estimate_tokens, tool_catalogue, _strip_titles
from claw.tools.registry import build_registry

REG = build_registry()


def args_of(tool):
    return _strip_titles(REG.get(tool).for_model()["args"])


# ---------- the title bug ----------
def test_an_argument_called_title_is_not_mistaken_for_a_schema_annotation():
    assert "title" in args_of("create_event")["properties"], \
        "create_event requires 'title'; stripping it leaves the model guessing"


def test_every_tool_with_a_title_argument_still_shows_it():
    missing = []
    for spec in REG.all():
        raw = spec.for_model()["args"].get("properties", {})
        shown = _strip_titles(spec.for_model()["args"]).get("properties", {})
        missing += [f"{spec.name}.{p}" for p in raw if p not in shown]
    assert missing == [], f"arguments vanished from the catalogue: {missing}"


def test_schema_annotations_are_still_dropped():
    """The annotation is noise; only the argument of that name was worth keeping."""
    stripped = _strip_titles({"title": "Args", "properties": {"title": {"title": "Title", "type": "string"}}})
    assert "title" not in stripped
    assert stripped["properties"]["title"] == {"type": "string"}


# ---------- the compact rendering ----------
def test_required_and_optional_arguments_are_distinguishable():
    line = compact_args(args_of("create_event"))
    assert "title:str," in line, "a required argument must not be marked optional"
    assert "minutes:int?" in line, "an argument with a default must be marked optional"


def test_a_nullable_argument_reads_as_optional_not_as_null():
    line = compact_args(args_of("list_events"))
    assert "calendar:str?" in line and "null" not in line


def test_a_tool_with_no_arguments_says_so():
    assert compact_args(args_of("daily_brief")) == "none"


def test_argument_descriptions_survive_because_they_are_the_useful_part():
    assert "When it starts" in compact_args(args_of("create_event"))


def test_the_catalogue_still_names_every_tool_the_plan_cannot_see():
    text = tool_catalogue(REG, {"organiser"})
    assert "Also available" in text
    assert "launch_app" in text, "a tool outside the capability must still be nameable"


#: A request of the shape the executor really passes. run_agent always sends
#: the task text, so every measurement below uses one.
A_REAL_REQUEST = "Make an invoice for Riverside Hotel for 2 banners at 15000 each"


def test_the_catalogue_fits_the_window_it_has_to_fit():
    """The whole point: an 8192-token window, minus a reply reserve."""
    for cap in ("files", "data", "documents", "organiser", "desktop", "browser"):
        cost = estimate_tokens(tool_catalogue(REG, {cap}, task=A_REAL_REQUEST))
        assert cost < 2000, f"{cap} catalogue is {cost} tokens"
    # The whole registry, which the runner does send: it passes `caps or None`,
    # so a plan naming no capability gets every tool.
    whole = estimate_tokens(tool_catalogue(REG, None, task=A_REAL_REQUEST))
    assert whole < 5000, f"the full catalogue is {whole} tokens"


def test_the_full_catalogue_is_kept_in_bounds_by_trimming_not_by_luck():
    """Why the test above passes, stated so it cannot pass for the wrong reason.

    The untrimmed registry is over 5000 tokens and will keep growing - that is
    what adding tools means. It used to be held under the limit by nobody
    adding any, which failed the build instead of degrading. Now the least
    relevant tools drop to names, and this asserts that is what is happening
    rather than the registry having shrunk.
    """
    untrimmed = estimate_tokens(tool_catalogue(REG, None))
    trimmed = tool_catalogue(REG, None, task=A_REAL_REQUEST)
    assert untrimmed > estimate_tokens(trimmed), "nothing was trimmed; this test is now meaningless"
    detailed = [l for l in trimmed.splitlines() if l.startswith("- ")]
    assert len(detailed) >= MIN_DETAILED
    # The tool this request needs is kept, in full, near the top. Not first:
    # across all 115 tools "make" matches make_flyer as strongly as "invoice"
    # matches make_document, and weighting words by rarity was measured and
    # removed for ranking worse inside a capability, which is the common path.
    # Rank 4 of 108 kept in full is a nudge, not a gate - and when a plan names
    # a capability, which is the usual case, make_document is first of 13.
    top = [l[2:].split("(")[0] for l in detailed[:5]]
    assert "make_document" in top, top
    # nothing vanished: what lost its arguments is still named
    assert trimmed.splitlines()[-1].startswith("Also available")
    named = {n.strip() for n in trimmed.splitlines()[-1].split(":", 1)[1].split(",")}
    kept = {l[2:].split("(")[0] for l in detailed}
    assert set(REG.names()) == kept | named


# --- the names line has a floor too ----------------------------------------
#
# Trimming turned detailed entries into bare names and stopped there: the
# line of names itself never shrank. With 139 tools the full catalogue sat at
# 4780 of 4800 tokens and a files step at 1789 of 1800, so the next tool
# anyone added would have gone over with nothing left to trim, and the build
# would have failed on a budget test with no way to satisfy it.

def test_todays_catalogue_still_names_every_tool():
    """The valve must not be firing now - this is headroom, not a change."""
    from claw.agent.executor import tool_catalogue
    from claw.tools.registry import build_registry

    registry = build_registry()
    for caps in ({"files"}, {"documents"}, {"design"}, None):
        cat = tool_catalogue(registry, caps, [], task="make a flyer from the pictures")
        assert "more (ask for any tool by name)" not in cat, (
            f"names are being trimmed for {caps} when there is still room")


def test_when_there_is_no_room_the_names_are_trimmed_and_counted():
    """And the brain is TOLD, so a missing name is not a missing tool."""
    import claw.agent.executor as ex
    from claw.tools.registry import build_registry

    registry = build_registry()
    was = ex.CATALOGUE_BUDGET
    try:
        ex.CATALOGUE_BUDGET = 320          # far too small on purpose
        cat = ex.tool_catalogue(registry, {"files"}, [], task="tidy up the downloads folder")
    finally:
        ex.CATALOGUE_BUDGET = was

    assert "more (ask for any tool by name)" in cat, "nothing was trimmed under a tiny budget"

    # It does not reach 320: MIN_DETAILED entries and MIN_NAMED names are
    # kept on purpose, and that floor is the point of those constants. What
    # matters is that it is much smaller than the untrimmed catalogue, so a
    # budget that is merely tight can now be met.
    full = ex.tool_catalogue(registry, {"files"}, [], task="")
    assert ex.estimate_tokens(cat) < ex.estimate_tokens(full) * 0.6, (
        f"trimmed {ex.estimate_tokens(cat)} against untrimmed {ex.estimate_tokens(full)}")
    # It never trims away the whole list.
    line = [l for l in cat.splitlines() if l.startswith("Also available")][0]
    named = line.split(":", 1)[1].split(", and ")[0]
    assert len(named.split(",")) >= ex.MIN_NAMED - 1, "the names line was gutted"


def test_the_tools_that_fit_are_never_the_ones_dropped():
    """Relevance ordering decides what goes, so the request's own tools stay."""
    import claw.agent.executor as ex
    from claw.tools.registry import build_registry

    registry = build_registry()
    was = ex.CATALOGUE_BUDGET
    try:
        ex.CATALOGUE_BUDGET = 320
        cat = ex.tool_catalogue(registry, {"files"}, ["sort_into_folders"],
                                task="tidy up the downloads folder into subfolders by type")
    finally:
        ex.CATALOGUE_BUDGET = was
    assert "sort_into_folders" in cat, "the tool that fits the request was trimmed away"
