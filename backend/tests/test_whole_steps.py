"""A trimmed transcript never starts with the result of a step it cannot see.

A step is two messages: the assistant's action, then "Result of ...". fit_context
keeps a suffix, so an action can never lose its result - the result comes after
it. The reverse happens easily: the cut lands between the two, and the oldest
thing the model reads is the outcome of something it has no record of doing.

A large model shrugs at that. A 2B reads it as work still outstanding and does
it again, and again can mean a second file written or a second message sent -
the repeated-destructive-step risk the gap audit names.

The rule comes from OpenClaw (MIT), whose context engine pairs every tool call
with its result and refuses to let a cut separate them. The implementation is
ours and far smaller: S-CLAW's transcript is plain chat messages, so only one
kind of orphan is possible.
"""

from __future__ import annotations

from claw.agent.executor import OBSERVATION_PREFIX, fit_context
from claw.models.base import ChatMessage


def transcript(steps: int, body: str = "x" * 400) -> list[ChatMessage]:
    """System, task, then `steps` action/result pairs."""
    out = [ChatMessage(role="system", content="SYSTEM " + "s" * 200),
           ChatMessage(role="user", content="Do the thing")]
    for i in range(steps):
        out.append(ChatMessage(role="assistant", content=f'{{"action":"step_{i}","body":"{body}"}}'))
        out.append(ChatMessage(role="user", content=f"{OBSERVATION_PREFIX}step_{i}: OK — done. {body}"))
    return out


def _history(fitted) -> list[ChatMessage]:
    """What is left after the system message, the task and any dropped-note."""
    return [m for m in fitted.messages[2:] if not m.content.startswith("[...")]


def test_the_kept_history_never_opens_with_an_orphan_result():
    for window in range(700, 4000, 190):
        fitted = fit_context(transcript(14), window_tokens=window)
        body = _history(fitted)
        if not body:
            continue
        assert not body[0].content.startswith(OBSERVATION_PREFIX), (
            f"at window={window} the model's oldest step is a result with no action")


def test_the_action_and_its_result_stay_together():
    fitted = fit_context(transcript(12), window_tokens=1500)
    body = _history(fitted)
    # Walking the kept history, every result must follow an assistant message.
    for before, message in zip(body, body[1:]):
        if message.content.startswith(OBSERVATION_PREFIX):
            assert before.role == "assistant", "a result was kept away from its action"


def test_nothing_changes_when_it_all_fits():
    msgs = transcript(2, body="x" * 20)
    fitted = fit_context(msgs, window_tokens=100_000)
    assert fitted.messages == msgs and fitted.dropped == 0


def test_the_task_and_the_system_message_are_still_kept():
    fitted = fit_context(transcript(20), window_tokens=900)
    assert fitted.messages[0].role == "system"
    assert fitted.messages[1].content == "Do the thing"


def test_the_most_recent_step_always_survives():
    """Whatever else goes, the model must see what it just did."""
    msgs = transcript(20)
    fitted = fit_context(msgs, window_tokens=700)
    assert msgs[-1] in fitted.messages, "the model was blinded to its own last step"


def test_dropping_is_still_reported():
    fitted = fit_context(transcript(20), window_tokens=900)
    assert fitted.dropped > 0
    assert any(m.content.startswith("[...") for m in fitted.messages), \
        "a silent gap invites the model to redo finished work"


def test_a_transcript_that_is_only_results_is_not_emptied():
    """Defensive: malformed history must not make the model blind."""
    msgs = [ChatMessage(role="system", content="S"),
            ChatMessage(role="user", content="Do it"),
            *(ChatMessage(role="user", content=f"{OBSERVATION_PREFIX}s{i}: OK") for i in range(8))]
    fitted = fit_context(msgs, window_tokens=600)
    assert fitted.messages[0].role == "system"
    assert len(fitted.messages) >= 2
