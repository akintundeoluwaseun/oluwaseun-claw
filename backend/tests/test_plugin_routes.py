"""The door into the plugin format.

claw/plugins/pack.py could unpack and check a plugin and nothing ever asked it
to: there was no route and no tool, so the only way to install one was to copy
a folder by hand. These are the three routes that make it reachable.

Installing takes a file PATH, so it is a main-process-only route: the path
comes from a Windows file dialog and the page can never send its own. Listing
and removing take no path and are callable from the UI.
"""

import io
import json
import zipfile

import pytest

from claw.plugins import pack

PLUGIN = """---
format: sclaw-plugin/1
name: drive-inkscape
description: Draw and export SVG artwork in Inkscape by writing its command line.
app: Inkscape
door: cli
author: Someone Else
categories: design
prompts:
  - Trace this logo to SVG, then export a 1024px PNG
---
Use `inkscape --export-type=png` rather than clicking anything.
"""


def _zip(files: dict[str, str]):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


@pytest.fixture
def client(make_client):
    return make_client({})


def test_an_empty_list_is_not_an_error(client):
    r = client.get("/plugins")
    assert r.status_code == 200
    assert r.json()["plugins"] == []
    assert r.json()["format"] == pack.FORMAT_ID


def test_install_then_list_then_remove(client, tmp_path):
    source = tmp_path / "inkscape-plugin.zip"
    source.write_bytes(_zip({"drive-inkscape/PLUGIN.md": PLUGIN}))

    r = client.post("/plugins/install", json={"path": str(source)})
    assert r.status_code == 200, r.text
    installed = r.json()["installed"]
    assert installed["name"] == "drive-inkscape"
    assert installed["categories"] == ["design"]
    assert installed["prompts"] == ["Trace this logo to SVG, then export a 1024px PNG"]
    assert installed["door"] == "cli"

    listed = client.get("/plugins").json()["plugins"]
    assert [p["name"] for p in listed] == ["drive-inkscape"]
    assert "program_present" in listed[0]

    r = client.post("/plugins/remove", json={"name": "drive-inkscape"})
    assert r.status_code == 200 and r.json()["removed"] == "drive-inkscape"
    assert client.get("/plugins").json()["plugins"] == []


def test_an_installed_plugin_reaches_the_brain(client, tmp_path, data_dir):
    """Installing is pointless if the recipe is never offered. It was, once."""
    from claw.agent import skills

    source = tmp_path / "p.zip"
    source.write_bytes(_zip({"drive-inkscape/PLUGIN.md": PLUGIN}))
    assert client.post("/plugins/install", json={"path": str(source)}).status_code == 200

    loaded = skills.load(skills.BUILTIN, data_dir / "skills")
    mine = [s for s in loaded if s.name == "drive-inkscape"]
    assert mine, "the installed plugin was not offered to the brain"
    # And it is not mistaken for one of Claw's own.
    assert mine[0].builtin is False
    assert "Trace this logo to SVG" in " ".join(mine[0].prompts)


def test_a_plugin_that_can_execute_is_refused(client, tmp_path):
    source = tmp_path / "bad.zip"
    source.write_bytes(_zip({"evil/PLUGIN.md": PLUGIN, "evil/run.ps1": "echo hi"}))
    r = client.post("/plugins/install", json={"path": str(source)})
    assert r.status_code == 422
    assert "not something a plugin may contain" in r.text
    assert client.get("/plugins").json()["plugins"] == []


def test_a_plugin_that_climbs_out_of_its_folder_is_refused(client, tmp_path):
    source = tmp_path / "escape.zip"
    source.write_bytes(_zip({"../../PLUGIN.md": PLUGIN}))
    r = client.post("/plugins/install", json={"path": str(source)})
    assert r.status_code == 422
    assert "climbs out" in r.text


def test_a_plugin_with_no_instructions_is_refused(client, tmp_path):
    source = tmp_path / "thin.zip"
    source.write_bytes(_zip({"thin/notes.txt": "nothing here"}))
    r = client.post("/plugins/install", json={"path": str(source)})
    assert r.status_code == 422
    assert "PLUGIN.md" in r.text


def test_a_refusal_says_what_to_do_about_it(client, tmp_path):
    """PluginRefused is written for a person to read, so it is the message."""
    source = tmp_path / "nofront.zip"
    source.write_bytes(_zip({"x/PLUGIN.md": "Just instructions, no settings block.\n"}))
    body = client.post("/plugins/install", json={"path": str(source)}).json()
    assert "starts with ---" in json.dumps(body)


def test_install_with_no_path_is_refused(client):
    assert client.post("/plugins/install", json={}).status_code == 422


def test_install_of_something_that_is_not_there(client, tmp_path):
    r = client.post("/plugins/install", json={"path": str(tmp_path / "missing.zip")})
    assert r.status_code == 422


def test_removing_what_is_not_installed_is_a_404(client):
    r = client.post("/plugins/remove", json={"name": "never-existed"})
    assert r.status_code == 404
    assert "no plugin called" in r.text


def test_remove_with_no_name_is_refused(client):
    assert client.post("/plugins/remove", json={}).status_code == 422


def test_installing_twice_replaces_rather_than_duplicates(client, tmp_path):
    source = tmp_path / "p.zip"
    source.write_bytes(_zip({"drive-inkscape/PLUGIN.md": PLUGIN}))
    assert client.post("/plugins/install", json={"path": str(source)}).status_code == 200
    assert client.post("/plugins/install", json={"path": str(source)}).status_code == 200
    assert len(client.get("/plugins").json()["plugins"]) == 1


# ---------- the window can actually do this ----------
#
# A route nothing calls is the bug this milestone is fixing, one layer up:
# pack.py existed for weeks with no caller. So the wiring is asserted, not
# assumed - the same check test_code_tools.py makes for extra_programs.

from pathlib import Path  # noqa: E402

import claw  # noqa: E402

_DESKTOP = Path(claw.__file__).resolve().parents[2] / "desktop" / "src"


def _read(*parts: str) -> str:
    return _DESKTOP.joinpath(*parts).read_text(encoding="utf-8")


def test_there_is_a_plugins_section_with_a_heading():
    import re
    html = _read("renderer", "index.html")
    headings = {h.strip() for h in re.findall(r"<h3>([^<]+)</h3>", html)}
    assert "Plugins" in headings, f"no Plugins section. Sections: {sorted(headings)}"


def test_the_plugins_section_is_reachable_from_a_tab():
    """A section with no tab is a section nobody opens."""
    html = _read("renderer", "index.html")
    assert 'data-panel="set-plugins"' in html
    assert 'id="set-plugins"' in html


def test_the_window_can_install_and_list_and_remove():
    html = _read("renderer", "index.html")
    app_js = _read("renderer", "app.js")
    assert 'id="plugin-install"' in html and 'id="plugin-list"' in html
    assert "api.installPlugin()" in app_js, "the Install button never calls through"
    assert "'GET', '/plugins'" in app_js, "the list is never fetched"
    assert "'/plugins/remove'" in app_js, "Remove never calls through"


def test_installing_goes_through_the_main_process():
    """The path comes from a file dialog, so the page must not send one."""
    preload = _read("preload.js")
    main = _read("main.js")
    backend_js = _read("backend.js")
    assert "claw:install-plugin" in preload and "claw:install-plugin" in main
    assert "showOpenDialog" in main
    # Listed as main-only, and NOT in the page's allowlist.
    page_list, main_list = backend_js.split("const MAIN_ONLY_ROUTES")
    assert "/plugins\\/install" not in page_list.replace("\\\\", "\\")
    assert "plugins\\/install" in main_list
    assert "/plugins$" in page_list and "plugins\\/remove" in page_list


def test_the_author_s_example_prompts_are_shown():
    """prompts exist to answer "what do I type?". Parsing them and not
    showing them would make the field decorative."""
    app_js = _read("renderer", "app.js")
    assert "p.prompts" in app_js
    assert "plugin-prompts" in app_js
    assert "plugin-prompts" in _read("renderer", "styles.css")


def test_the_window_says_that_a_plugin_raises_the_bar():
    """If Claw will start asking about every change, the person is told why
    before they install, not after it surprises them."""
    import re
    # The markup is wrapped, so compare on normalised whitespace rather than
    # on where the lines happen to break.
    html = re.sub(r"\s+", " ", _read("renderer", "index.html"))
    assert "Claw checks each change with you" in html
    assert "written by someone else" in html
