"""An empty reply is explained, not hidden.

llama-server parses a thinking model's chain of thought out of the answer and
returns it separately as `reasoning_content`. A brain that spends its whole
budget thinking therefore comes back HTTP 200 with `content` empty and all the
work in a field nothing reads.

Verified against a REAL llama-server with Qwen3-2B: at max_tokens 120 the
reply was finish_reason "length", content 0 characters, reasoning_content 485.
llama-cpp-python's server does not split the two, which is why this never
showed up until the real engine was used.
"""

import pytest

from claw.models.openai_compat import _why_it_said_nothing


def test_the_budget_ran_out_while_thinking():
    why = _why_it_said_nothing({"finish_reason": "length",
                                "message": {"reasoning_content": "thinking..."}})
    assert "thinking" in why and "budget" in why
    assert "larger budget" in why, "it must say what to do about it"


def test_it_thought_and_never_answered():
    why = _why_it_said_nothing({"finish_reason": "stop",
                                "message": {"reasoning_content": "thinking..."}})
    assert "reasoning" in why and "no answer" in why


def test_cut_off_with_nothing_to_show():
    why = _why_it_said_nothing({"finish_reason": "length", "message": {}})
    assert "cut off" in why


def test_an_empty_reply_with_no_clue_still_says_so():
    assert "empty reply" in _why_it_said_nothing({"finish_reason": "stop", "message": {}})


def test_it_never_blames_the_person():
    for choice in ({"finish_reason": "length", "message": {"reasoning_content": "t"}},
                   {"finish_reason": "stop", "message": {}}):
        why = _why_it_said_nothing(choice).lower()
        assert "you " not in why and "your fault" not in why


def test_a_missing_message_does_not_crash():
    assert _why_it_said_nothing({}) 
    assert _why_it_said_nothing({"message": None})


@pytest.mark.asyncio
async def test_an_empty_content_is_raised_rather_than_returned():
    """Returning "" would travel as a plan that cannot be parsed, and the
    person would be told the reply was unusable instead of why."""
    from claw.models.base import ChatMessage, ModelResponseError
    from claw.models.openai_compat import OpenAICompatAdapter

    a = OpenAICompatAdapter("http://127.0.0.1:1/v1", "m", timeout_s=5, temperature=0.0)

    async def fake_request(method, path, *, timeout, json=None):
        return {"choices": [{"finish_reason": "length",
                             "message": {"content": "", "reasoning_content": "thinking..."}}]}

    a._request = fake_request
    with pytest.raises(ModelResponseError) as e:
        await a.chat([ChatMessage(role="user", content="hi")])
    assert "thinking" in str(e.value)


@pytest.mark.asyncio
async def test_a_real_reply_is_untouched():
    from claw.models.base import ChatMessage
    from claw.models.openai_compat import OpenAICompatAdapter

    a = OpenAICompatAdapter("http://127.0.0.1:1/v1", "m", timeout_s=5, temperature=0.0)

    async def fake_request(method, path, *, timeout, json=None):
        return {"choices": [{"finish_reason": "stop",
                             "message": {"content": '{"ok": true}', "reasoning_content": "thought"}}]}

    a._request = fake_request
    assert await a.chat([ChatMessage(role="user", content="hi")]) == '{"ok": true}'
