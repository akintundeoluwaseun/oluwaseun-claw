"""Plugins: teaching Claw to drive one particular program.

Claw can work a window it has never seen by looking at the controls - but
that is guessing, and twenty guesses at 95% each finish 36% of the time. A
plugin is somebody who actually uses the program writing down how it is
done.

Most of this file is about one rule: A PLUGIN CARRIES NO CODE. If a plugin
downloaded from a website could run a program, the website becomes a way of
putting malware on every machine that trusts it, and one bad plugin ends the
product. So the tests here mostly try to sneak code past the installer.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from claw.plugins.pack import (
    EXECUTABLE, Plugin, PluginRefused, check_contents, install, installed, parse,
    read_folder, remove, safe_member,
)

GOOD = """---
name: drive-example
description: Drive the Example program to do the thing people ask for.
app: Example
programs: example-app
door: python
version: 1
triggers: example, thing
---
1. Write the job as a script.
2. Run it with run_command.
3. Reopen what was written and check it.
"""


def make(folder: Path, text: str = GOOD, name: str = "PLUGIN.md") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    return folder


# ---------- reading one ----------
def test_a_plugin_says_which_program_it_drives_and_how(tmp_path):
    p = read_folder(make(tmp_path / "example"))
    assert p.name == "drive-example" and p.app == "Example"
    assert p.door == "python", "the scripting door is the point of a plugin"
    assert p.programs == ["example-app"] and p.triggers == ["example", "thing"]
    assert "run_command" in p.body


def test_a_plugin_for_software_you_do_not_have_knows_it(tmp_path):
    """Offering it would send the brain confidently down a dead end."""
    here = read_folder(make(tmp_path / "a", GOOD.replace("programs: example-app",
                                                         "programs: python3")))
    gone = read_folder(make(tmp_path / "b", GOOD.replace("programs: example-app",
                                                         "programs: no-such-program-xyz")))
    assert here.installed_here() is True
    assert gone.installed_here() is False


def test_the_built_in_blender_plugin_is_valid():
    """The first real one, in the shipped format."""
    p = read_folder(Path(__file__).resolve().parents[1] / "claw" / "skills" / "drive-blender")
    assert p.app == "Blender" and p.door == "python"
    assert "--background" in p.body, "it must say how to open the door"
    assert "mouse" in p.body.lower(), "it should say NOT to drive Blender by mouse"


@pytest.mark.parametrize("text,why", [
    ("no front matter at all", "settings block"),
    ("---\ndescription: a thing\n---\nbody", "name"),
    ("---\nname: a\n---\nbody", "description"),
    ("---\nname: a\ndescription: b\n---\n", "instructions"),
])
def test_a_broken_plugin_says_what_is_wrong(tmp_path, text, why):
    folder = make(tmp_path / "broken", text)
    with pytest.raises(PluginRefused, match=why):
        read_folder(folder)


# ---------- the rule that matters: no code ----------
@pytest.mark.parametrize("bad", ["run.exe", "setup.msi", "go.bat", "hack.ps1", "thing.py",
                                 "x.vbs", "y.jar", "z.sh", "a.dll", "b.lnk", "c.js"])
def test_a_plugin_carrying_anything_runnable_is_refused(tmp_path, bad):
    folder = make(tmp_path / "sneaky")
    (folder / bad).write_bytes(b"whatever")
    with pytest.raises(PluginRefused, match="not something a plugin may contain"):
        check_contents(folder)


def test_the_refusal_explains_the_alternative(tmp_path):
    """A plugin author told only "no" will try to work round it."""
    folder = make(tmp_path / "sneaky")
    (folder / "helper.py").write_text("print('hi')")
    with pytest.raises(PluginRefused) as exc:
        check_contents(folder)
    assert "approve" in str(exc.value), "it should point at the approved route"


def test_text_and_pictures_are_fine(tmp_path):
    folder = make(tmp_path / "fine")
    (folder / "notes.md").write_text("more instructions")
    (folder / "screenshot.png").write_bytes(b"\x89PNG fake")
    (folder / "data.json").write_text("{}")
    assert len(check_contents(folder)) == 4


def test_every_executable_suffix_is_actually_refused(tmp_path):
    """The list is the guard, so nothing in it may slip through."""
    for suffix in sorted(EXECUTABLE):
        folder = tmp_path / f"p{suffix.replace('.', '')}"
        make(folder)
        (folder / f"thing{suffix}").write_bytes(b"x")
        with pytest.raises(PluginRefused):
            check_contents(folder)


# ---------- installing ----------
def test_installing_from_a_folder_keeps_it(tmp_path):
    store = tmp_path / "plugins"
    p = install(make(tmp_path / "src" / "example"), store)
    assert p.name == "drive-example"
    assert (p.path / "PLUGIN.md").is_file()
    assert [x.name for x in installed(store)] == ["drive-example"]


def test_installing_from_a_zip(tmp_path):
    src = make(tmp_path / "src" / "example")
    bundle = tmp_path / "example.zip"
    with zipfile.ZipFile(bundle, "w") as z:
        z.write(src / "PLUGIN.md", "example/PLUGIN.md")
    store = tmp_path / "plugins"
    p = install(bundle, store)
    assert p.name == "drive-example" and (p.path / "PLUGIN.md").is_file()


def test_a_zip_that_climbs_out_is_refused(tmp_path):
    """The same zip-slip that breaks archive extractors."""
    for evil in ("../escaped.md", "/etc/passwd", r"..\..\escaped.md"):
        with pytest.raises(PluginRefused):
            safe_member(evil)

    bundle = tmp_path / "evil.zip"
    with zipfile.ZipFile(bundle, "w") as z:
        z.writestr("example/PLUGIN.md", GOOD)
        z.writestr("../ESCAPED.md", "got out")
    store = tmp_path / "plugins"
    with pytest.raises(PluginRefused):
        install(bundle, store)
    assert not (tmp_path / "ESCAPED.md").exists(), "a plugin wrote outside its folder"


def test_a_zip_carrying_code_is_refused_and_nothing_is_kept(tmp_path):
    bundle = tmp_path / "bad.zip"
    with zipfile.ZipFile(bundle, "w") as z:
        z.writestr("example/PLUGIN.md", GOOD)
        z.writestr("example/payload.exe", "MZ...")
    store = tmp_path / "plugins"
    with pytest.raises(PluginRefused, match="not something a plugin may contain"):
        install(bundle, store)
    assert installed(store) == [], "a refused plugin was kept anyway"
    assert not list(store.glob("*/payload.exe"))


def test_installing_again_replaces_rather_than_doubling(tmp_path):
    store = tmp_path / "plugins"
    install(make(tmp_path / "src" / "example"), store)
    newer = make(tmp_path / "src2" / "example", GOOD.replace("version: 1", "version: 2"))
    install(newer, store)
    kept = installed(store)
    assert len(kept) == 1 and kept[0].version == "2"


def test_removing_one(tmp_path):
    store = tmp_path / "plugins"
    install(make(tmp_path / "src" / "example"), store)
    assert remove(store, "drive-example") is True
    assert installed(store) == []
    assert remove(store, "drive-example") is False


def test_a_broken_plugin_in_the_folder_does_not_hide_the_good_ones(tmp_path):
    store = tmp_path / "plugins"
    install(make(tmp_path / "src" / "example"), store)
    make(store / "rubbish", "this is not a plugin")
    assert [p.name for p in installed(store)] == ["drive-example"]


# ---------- it has to reach the brain ----------
def test_a_plugin_is_also_a_skill_so_the_brain_already_gets_it(tmp_path):
    """The format is the one Claw already reads, which is why this works.

    A plugin that installs but never reaches the brain would be decoration.
    """
    from claw.agent import skills

    store = tmp_path / "plugins"
    install(make(tmp_path / "src" / "example"), store)
    found = skills.load(store)
    assert [s.name for s in found] == ["drive-example"]

    chosen = skills.pick("do the example thing with the Example program", found)
    assert chosen is not None and chosen.name == "drive-example"
    assert "run_command" in skills.for_prompt(chosen)


def test_the_blender_plugin_is_picked_for_a_blender_job():
    from claw.agent import skills

    found = skills.load(Path(__file__).resolve().parents[1] / "claw" / "skills")
    chosen = skills.pick("render a turntable of this model in blender", found)
    assert chosen is not None and chosen.name == "drive-blender"


# ---------- the format is ours, and versioned ----------
def test_a_plugin_may_declare_the_format_it_was_written_for(tmp_path):
    from claw.plugins.pack import FORMAT_ID
    p = read_folder(make(tmp_path / "v", GOOD.replace("---\nname:", f"---\nformat: {FORMAT_ID}\nname:", 1)))
    assert p.format == FORMAT_ID


def test_a_plugin_from_the_future_says_so_instead_of_half_working(tmp_path):
    folder = make(tmp_path / "future",
                  GOOD.replace("---\nname:", "---\nformat: sclaw-plugin/99\nname:", 1))
    with pytest.raises(PluginRefused, match="Update S-CLAW"):
        read_folder(folder)


def test_somebody_elses_plugin_format_is_refused(tmp_path):
    folder = make(tmp_path / "other",
                  GOOD.replace("---\nname:", "---\nformat: someone-else/1\nname:", 1))
    with pytest.raises(PluginRefused, match="This is S-CLAW"):
        read_folder(folder)


def test_a_plugin_with_no_format_line_still_works(tmp_path):
    """The eleven recipes that shipped before the format was named."""
    p = read_folder(make(tmp_path / "old"))
    assert p.format == "" and p.name == "drive-example"


def test_the_shipped_blender_plugin_declares_the_format():
    from claw.plugins.pack import FORMAT_ID
    p = read_folder(Path(__file__).resolve().parents[1] / "claw" / "skills" / "drive-blender")
    assert p.format == FORMAT_ID


def test_the_written_spec_matches_the_code():
    """A spec that drifts from the code sends developers down a dead end."""
    from claw.plugins.pack import EXECUTABLE, FORMAT_ID
    spec = (Path(__file__).resolve().parents[2] / "docs" / "PLUGINS.md").read_text()
    assert FORMAT_ID in spec
    for field in ("name", "description", "app", "programs", "door", "triggers"):
        assert f"`{field}`" in spec, f"the spec does not document {field}"
    for suffix in (".exe", ".py", ".ps1"):
        assert suffix in spec, f"the spec does not warn about {suffix}"
        assert suffix in EXECUTABLE
