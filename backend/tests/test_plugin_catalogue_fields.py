"""categories and prompts: what a plugin tells the list it appears in.

A plugin store needs two things the format did not carry. Where a plugin
belongs among the others, and what a person can actually say to use it - the
second written by whoever wrote the plugin, because they know the words their
users type and a description written for a human reader rarely contains them.

prompts are sentences, so they are a list of lines, never a comma-split field:
"Make a cup, then render it" is one prompt.

Both are optional. Every plugin and skill that shipped before them still
loads, which the last tests here check.
"""

from pathlib import Path

import pytest

from claw.agent import skills
from claw.plugins.pack import MAX_CATEGORIES, MAX_PROMPTS, parse

HEAD = "---\nname: drive-blender\ndescription: make 3D models\n"


def _plugin(extra: str = ""):
    return parse(HEAD + extra + "---\nOpen Blender and run a script.\n", Path("PLUGIN.md"))


def test_categories_are_read_and_lowercased():
    assert _plugin("categories: Design, 3D\n").categories == ["design", "3d"]


def test_categories_are_capped():
    many = ", ".join(f"c{i}" for i in range(20))
    assert len(_plugin(f"categories: {many}\n").categories) == MAX_CATEGORIES


def test_prompts_keep_their_commas():
    """The whole reason prompts are lines and not a comma-split field."""
    p = _plugin("prompts:\n  - Make a cup, then render it to a PNG\n  - Open Blender\n")
    assert p.prompts == ["Make a cup, then render it to a PNG", "Open Blender"]


def test_prompts_are_capped():
    block = "prompts:\n" + "".join(f"  - say thing {i}\n" for i in range(30))
    assert len(_plugin(block).prompts) == MAX_PROMPTS


def test_a_long_prompt_is_trimmed_rather_than_refused():
    p = _plugin("prompts:\n  - " + "x" * 500 + "\n")
    assert len(p.prompts[0]) == 120


def test_quotes_around_a_prompt_are_stripped():
    p = _plugin('prompts:\n  - "Make a cup"\n')
    assert p.prompts == ["Make a cup"]


def test_an_inline_list_is_accepted_too():
    assert _plugin("prompts: [Open Blender; Render it]\n").prompts == ["Open Blender", "Render it"]


def test_prompts_do_not_swallow_the_next_field():
    p = _plugin("prompts:\n  - Open Blender\nauthor: Ada\n")
    assert p.prompts == ["Open Blender"]
    assert p.author == "Ada"


def test_a_field_after_a_block_list_is_still_read():
    p = _plugin("prompts:\n  - Open Blender\ncategories: design\ndoor: python\n")
    assert p.categories == ["design"]
    assert p.door == "python"


# --- the brain sees them too --------------------------------------------------

def test_prompts_reach_the_matching_words():
    text = HEAD + "prompts:\n  - Render the scene to a PNG\n---\nBody.\n"
    s = skills.parse(text, Path("PLUGIN.md"))
    assert s is not None
    assert {"render", "scene", "png"} <= s.words()


def test_prompts_help_a_recipe_be_found(tmp_path):
    """A request phrased the author's way finds the plugin; without prompts it did not."""
    text = HEAD + "prompts:\n  - Sculpt a low-poly bust\n---\nBody.\n"
    with_prompts = skills.parse(text, Path("PLUGIN.md"))
    without = skills.parse(HEAD + "---\nBody.\n", Path("PLUGIN.md"))
    task = "sculpt a low-poly bust for me"
    assert skills.pick(task, [with_prompts]) is with_prompts
    assert skills.pick(task, [without]) is None


# --- nothing that shipped before this breaks ----------------------------------

def test_a_plugin_without_the_new_fields_still_loads():
    p = _plugin()
    assert p.categories == [] and p.prompts == []


def test_every_shipped_skill_still_parses():
    loaded = skills.load(skills.BUILTIN)
    assert loaded, "no built-in skills found"
    for s in loaded:
        assert s.name and s.description and s.body


def test_the_shipped_plugin_still_reads_as_a_plugin():
    main = skills.BUILTIN / "drive-blender" / "PLUGIN.md"
    if not main.exists():
        pytest.skip("drive-blender is not shipped in this tree")
    p = parse(main.read_text(encoding="utf-8-sig"), main)
    assert p.name and p.description and p.body
