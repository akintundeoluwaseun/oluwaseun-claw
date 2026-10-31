"""Every tool the registry can run has words a person can read.

The first Windows run showed an approval card asking "Allow Claw to
write_spreadsheet?" and a finished step titled "read_document". Those are
variable names. A third of the registry - 25 of 73 tools - had no entry in the
interface's label maps, so a third of everything Claw could do introduced
itself to the person as an identifier with underscores in it.

The reason it went unnoticed is that the failure is silent: app.js falls back
to the raw tool name, which looks like a deliberate label until you read it. So
this is the test that has to exist, and it has to live here rather than in the
desktop suite, because only this side can ask the registry what tools exist.

TOOL_LABEL is the past tense, shown once a step has run. TOOL_ASK is the
present tense, shown on the approval card - so it is only needed for tools that
can actually stop and ask, which is anything not READ_ONLY.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from claw.permissions.policy import RiskLevel
from claw.tools.registry import build_registry

APP_JS = Path(__file__).resolve().parents[2] / "desktop" / "src" / "renderer" / "app.js"


def _map_keys(name: str) -> set[str]:
    source = APP_JS.read_text(encoding="utf-8")
    match = re.search(rf"const {name} = \{{(.*?)\n\}};", source, re.S)
    assert match, f"app.js no longer declares {name}"
    body = re.sub(r"/\*.*?\*/", " ", match.group(1), flags=re.S)
    return set(re.findall(r"(?:^|[\s,{])([a-z_][a-z0-9_]*)\s*:", body))


@pytest.fixture(scope="module")
def tools():
    return build_registry()


def test_every_tool_has_a_past_tense_label(tools):
    missing = sorted(set(tools.names()) - (_map_keys("TOOL_LABEL") | _map_keys("TOOL_ASK")))
    assert not missing, (
        "these tools would show their own identifier to the person instead of a "
        f"readable label: {missing}"
    )


def test_every_tool_that_can_ask_has_a_question(tools):
    asks = _map_keys("TOOL_ASK")
    needs = sorted(
        name for name in tools.names()
        if getattr(tools.get(name), "risk", None) is not RiskLevel.READ_ONLY
    )
    missing = [n for n in needs if n not in asks]
    assert not missing, (
        "these tools can stop and ask for approval, and the card would name them "
        f"in code rather than in words: {missing}"
    )


def test_no_label_survives_a_tool_being_removed(tools):
    """A label for a tool that no longer exists is dead weight and misleads the
    next person to read the list."""
    names = set(tools.names())
    stale = sorted((_map_keys("TOOL_LABEL") | _map_keys("TOOL_ASK")) - names)
    assert not stale, f"labels for tools the registry no longer has: {stale}"


def test_labels_are_words_not_identifiers():
    """The whole point: no entry may simply restate the tool's own name."""
    source = APP_JS.read_text(encoding="utf-8")
    for name in ("TOOL_LABEL", "TOOL_ASK"):
        match = re.search(rf"const {name} = \{{(.*?)\n\}};", source, re.S)
        for key, value in re.findall(r"([a-z_][a-z0-9_]*)\s*:\s*'([^']*)'", match.group(1)):
            assert "_" not in value, f"{name}.{key} is an identifier, not a label: {value!r}"
            assert value[:1].isupper(), f"{name}.{key} does not read as a sentence: {value!r}"
