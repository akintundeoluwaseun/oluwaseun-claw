"""Every model call Claw makes asks the brain not to think.

Measured through `make_plan` against a real llama-server running Qwen3.5-2B
under Claw's own production flags, on the held-out 16, temperature 0:

    thinking ON     usable  2/16   right  2/16   median 162.0s   total 2330s
    thinking OFF    usable 16/16   right 14/16   median  15.7s   total  226s

Seven times faster and seven times more accurate at once, because the failure
with thinking on is TOTAL rather than slow: fourteen of the sixteen generated
their entire 1024-token budget twice (2 x 1024 / 13 tok/s = 158s, against a
measured 150-170s) and put every token in `reasoning_content`, leaving
`content` empty. There is no speed-versus-care trade to make with an answer
that is never written.

This test is structural on purpose. The bug is silent - a new lane added
without `thinking=False` does not raise, it just quietly answers nothing after
eighty seconds - and it has already hidden from five phases of this audit. So
rather than trusting that the next person remembers, every `.chat(...)` call
in the package is found and checked.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "claw"

#: `see()` is the vision call and takes no messages, so the switch does not
#: apply to it. Nothing else is exempt.
EXEMPT_METHODS = {"see"}


def chat_calls() -> list[tuple[str, int, ast.Call]]:
    """Every `<something>.chat(...)` call in the package, with where it is."""
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "chat"
                    # `super().chat(...)` inside an adapter is the adapter
                    # forwarding a caller's own choice, not a lane choosing.
                    and not (isinstance(node.func.value, ast.Call)
                             and isinstance(node.func.value.func, ast.Name)
                             and node.func.value.func.id == "super")):
                found.append((str(path.relative_to(PACKAGE.parent)), node.lineno, node))
    return found


def test_there_are_chat_calls_to_check():
    """Guards the guard: an AST walk that silently finds nothing proves nothing."""
    assert len(chat_calls()) >= 6, "the finder stopped finding call sites; fix the finder"


@pytest.mark.parametrize("where,line,call",
                         chat_calls(),
                         ids=[f"{w}:{ln}" for w, ln, _ in chat_calls()])
def test_the_call_asks_the_brain_not_to_think(where, line, call):
    passed = {kw.arg for kw in call.keywords if kw.arg}
    assert "thinking" in passed, (
        f"{where}:{line} calls .chat() without thinking=False. On this engine a "
        f"thinking model spends its whole budget in reasoning_content and returns "
        f"content empty - measured 2/16 usable plans against 16/16 with it off. "
        f"If this call genuinely wants thinking, pass thinking=True explicitly so "
        f"the choice is visible.")
    value = next(kw.value for kw in call.keywords if kw.arg == "thinking")
    assert isinstance(value, ast.Constant), f"{where}:{line} passes a non-literal thinking="
    assert value.value is False, (
        f"{where}:{line} passes thinking={value.value!r}. That is allowed, but it must be "
        f"deliberate: see the measurement in this file's docstring before leaving it on.")
