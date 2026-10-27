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

from claw.agent.executor import compact_args, estimate_tokens, tool_catalogue, _strip_titles
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


def test_the_catalogue_fits_the_window_it_has_to_fit():
    """The whole point: an 8192-token window, minus a reply reserve."""
    for cap in ("files", "documents", "organiser", "desktop", "browser"):
        cost = estimate_tokens(tool_catalogue(REG, {cap}))
        assert cost < 2000, f"{cap} catalogue is {cost} tokens"
    assert estimate_tokens(tool_catalogue(REG, None)) < 5000, "even the full catalogue should fit"
