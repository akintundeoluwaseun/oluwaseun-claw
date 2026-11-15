"""Asking a thinking model not to think, and coping when it cannot be asked.

WHY THIS EXISTS, measured on a real llama-server (not llama-cpp-python, which
does not reproduce it) with Qwen3-2B on four CPU cores, temperature 0, the
chat prompt and "What is the capital of France?":

    max_tokens   time   finish   content   reasoning_content
       512      38.2s   length     0 ch        1977 ch
      1024      82.7s   length     0 ch        4006 ch
      1536     127.1s   length     0 ch        5995 ch
      2048     160.7s   length     0 ch        7859 ch

The model NEVER answered. Not slowly - never, at any budget, because the
reasoning grows to fill whatever it is given. Raising the limit cannot fix
this and lowering it cannot cause it. With the chat template's thinking turned
off, the same question answered correctly in 1.4 seconds.

So this is not a tuning knob, it is the difference between an answer and no
answer, and the failure was ugly: the chat lane raised, fell through to
planning, and held Claw's single-task runner for 90 seconds, after which every
other task was rejected as busy.

`reasoning_format: "none"` is NOT a substitute and is tested against below: it
leaves the thinking on and inlines the <think> block into `content`, so the
person reads the monologue (measured: 81.5s, 4014 characters of it).
"""

import pytest

from claw.models.base import ModelBadRequest
from claw.models.ollama import OllamaAdapter
from claw.models.openai_compat import OpenAICompatAdapter
from tests.fake_model_server import FakeModelServer

MODEL = "qwen3:2b"


def adapter(server, cls=OpenAICompatAdapter):
    return cls(server.base_url, MODEL, timeout_s=10, temperature=0.0)


# ---------------------------------------------------------------- the request

@pytest.mark.asyncio
async def test_thinking_off_asks_the_template_not_to_think():
    with FakeModelServer(models=[MODEL]) as server:
        server.default_reply = "Paris."
        assert await adapter(server).chat([], thinking=False) == "Paris."
    assert server.requests[-1]["body"]["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.asyncio
async def test_thinking_is_left_alone_by_default():
    """Planning and tool choice are untouched until measured, so the default
    must send nothing at all - not `enable_thinking: true`."""
    with FakeModelServer(models=[MODEL]) as server:
        server.default_reply = "{}"
        await adapter(server).chat([])
    assert "chat_template_kwargs" not in server.requests[-1]["body"]


@pytest.mark.asyncio
async def test_it_never_asks_for_the_thinking_to_be_inlined():
    """`reasoning_format: none` would put the raw <think> block in the reply
    the person reads. Measured, and never wanted."""
    with FakeModelServer(models=[MODEL]) as server:
        server.default_reply = "Paris."
        await adapter(server).chat([], thinking=False)
    assert "reasoning_format" not in server.requests[-1]["body"]


# ------------------------------------------------- a server that cannot be asked

@pytest.mark.asyncio
async def test_a_server_that_refuses_the_field_still_gives_its_answer():
    """A cloud provider answers 400 for an argument it does not know. That must
    cost a round trip, not the reply."""
    with FakeModelServer(models=[MODEL]) as server:
        server.rejects_thinking_switch = True
        server.default_reply = "Paris."
        a = adapter(server)
        assert await a.chat([], thinking=False) == "Paris."
        assert a.quiet_thinking_ok is False, "it must remember, not re-learn"
    bodies = [r["body"] for r in server.requests]
    assert "chat_template_kwargs" in bodies[0]
    assert "chat_template_kwargs" not in bodies[1]


@pytest.mark.asyncio
async def test_the_refusal_is_learned_once_not_every_call():
    with FakeModelServer(models=[MODEL]) as server:
        server.rejects_thinking_switch = True
        server.default_reply = "Paris."
        a = adapter(server)
        for _ in range(3):
            await a.chat([], thinking=False)
    sent = sum("chat_template_kwargs" in r["body"] for r in server.requests)
    assert sent == 1, f"the dead field was sent {sent} times, not once"
    assert len(server.requests) == 4, "one wasted trip in total, then three clean ones"


@pytest.mark.asyncio
async def test_a_400_that_is_not_about_thinking_is_still_an_error():
    """The fallback must not swallow a genuinely bad request."""
    with FakeModelServer(models=[MODEL]) as server:
        server.status_override = 400
        with pytest.raises(ModelBadRequest):
            await adapter(server).chat([], thinking=False)


@pytest.mark.asyncio
async def test_a_400_with_thinking_on_is_not_retried():
    with FakeModelServer(models=[MODEL]) as server:
        server.status_override = 400
        with pytest.raises(ModelBadRequest):
            await adapter(server).chat([])
    assert len(server.requests) == 1, "nothing to fall back from, so nothing to retry"


# ------------------------------------------------------------------- ollama

@pytest.mark.asyncio
async def test_ollama_has_its_own_spelling_of_the_same_switch():
    with FakeModelServer(models=[MODEL]) as server:
        server.default_reply = "Paris."
        assert await adapter(server, OllamaAdapter).chat([], thinking=False) == "Paris."
    assert server.requests[-1]["body"]["think"] is False


@pytest.mark.asyncio
async def test_ollama_recovers_when_the_model_cannot_be_asked():
    """Ollama refuses `think` on a model that does not support it."""
    with FakeModelServer(models=[MODEL]) as server:
        server.rejects_thinking_switch = True
        server.default_reply = "Paris."
        a = adapter(server, OllamaAdapter)
        assert await a.chat([], thinking=False) == "Paris."
        assert a.quiet_thinking_ok is False
    assert "think" not in server.requests[-1]["body"]


@pytest.mark.asyncio
async def test_ollama_sends_nothing_by_default():
    with FakeModelServer(models=[MODEL]) as server:
        await adapter(server, OllamaAdapter).chat([])
    assert "think" not in server.requests[-1]["body"]


# --------------------------------------------- the lane that must switch it off

def test_the_chat_lane_asks_for_no_thinking():
    """A regression guard on the fix itself, at the call site.

    Pinned by reading the source because the alternative - driving a whole task
    through the runner - needs a model server and would not say WHICH call had
    the flag.
    """
    import inspect

    from claw.agent import runner

    src = inspect.getsource(runner.TaskRunner._run)
    chat_call = src.split("conversation.CHAT_SYSTEM")[1].split(")).strip()")[0]
    assert "thinking=False" in chat_call, (
        "the chat lane must ask the brain not to think: with thinking on, a 2B "
        "spent its entire budget reasoning and never answered at all")


# ------------------------------------------- the self-test says so out loud

def test_the_self_test_warns_when_the_engine_refuses_the_switch(make_client, fake_server):
    """The one moment Claw can tell somebody, while they are looking.

    An engine that will not be asked to stop thinking is where the worst
    failure measured in this audit can still happen. The self-test is the only
    place a brain is loaded AND a person is waiting for a verdict, so it is
    where this belongs.
    """
    fake_server.rejects_thinking_switch = True
    fake_server.default_reply = "ready"
    c = make_client({"model": {"mode": "custom", "provider": "openai_compatible",
                               "base_url": fake_server.base_url, "model": "qwen2.5:7b"}})
    body = c.post("/models/selftest", json={}).json()

    assert body["ok"] is True, "the brain answered, so the test must still pass"
    assert body["thinking_switch"] is False
    assert "answer nothing" in body["warning"]
    assert "Update the AI engine" in body["warning"]


def test_the_self_test_is_quiet_when_the_engine_is_fine(make_client, fake_server):
    """No warning on a healthy engine - a message that always appears is noise."""
    fake_server.default_reply = "ready"
    c = make_client({"model": {"mode": "custom", "provider": "openai_compatible",
                               "base_url": fake_server.base_url, "model": "qwen2.5:7b"}})
    body = c.post("/models/selftest", json={}).json()

    assert body["ok"] is True
    assert body["thinking_switch"] is True
    assert "warning" not in body


def test_setup_checks_the_flag_the_switch_depends_on():
    """scripts/setup.ps1 fetches whichever llama.cpp build was newest at the
    time, so the engine version is not reproducible. A build without --jinja
    cannot honour chat_template_kwargs, and a thinking brain then answers
    nothing. Setup must say so rather than leave it to be discovered."""
    from pathlib import Path

    setup = Path(__file__).resolve().parents[2] / "scripts" / "setup.ps1"
    text = setup.read_text()
    assert "--help" in text and "'--jinja'" in text, "setup no longer verifies --jinja"
    assert "answer nothing at all" in text, "the warning no longer says what goes wrong"
