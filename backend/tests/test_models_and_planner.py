import json

import pytest

from claw.agent.planner import PlanningFailed, make_plan
from claw.models.base import ModelNotFound, ModelServerUnavailable
from claw.models.ollama import OllamaAdapter
from claw.models.openai_compat import OpenAICompatAdapter
from claw.permissions.policy import Decision, PermissionPolicy
from tests.conftest import VALID_PLAN


def ollama(url, model="qwen2.5:7b"):
    return OllamaAdapter(url, model, timeout_s=5, temperature=0.1)


async def test_ollama_lists_models(fake_server):
    models = await ollama(fake_server.base_url).list_models()
    assert [m.name for m in models] == ["qwen2.5:7b"]


async def test_status_ready(fake_server):
    st = await ollama(fake_server.base_url).status()
    assert st.server_reachable and st.model_available


async def test_status_missing_model_suggests_pull(fake_server):
    st = await ollama(fake_server.base_url, "llama3.2:3b").status()
    assert st.server_reachable and not st.model_available
    assert "ollama pull llama3.2:3b" in st.message


async def test_status_latest_alias(fake_server):
    fake_server.models = ["qwen2.5:latest"]
    assert (await ollama(fake_server.base_url, "qwen2.5").status()).model_available


async def test_server_down_is_explained():
    adapter = ollama("http://127.0.0.1:9")  # nothing listens on port 9
    with pytest.raises(ModelServerUnavailable) as exc:
        await adapter.list_models()
    assert "Ollama" in exc.value.message and exc.value.hint
    st = await adapter.status()
    assert not st.server_reachable


async def test_chat_sends_schema_and_returns_text(fake_server):
    fake_server.replies.append("hello")
    out = await ollama(fake_server.base_url).chat([], json_schema={"type": "object"})
    assert out == "hello"
    assert fake_server.requests[-1]["body"]["format"] == {"type": "object"}
    assert fake_server.requests[-1]["body"]["stream"] is False


async def test_chat_unknown_model_raises(fake_server):
    with pytest.raises(ModelNotFound):
        await ollama(fake_server.base_url, "nope").chat([])


async def test_openai_compat_adapter(fake_server):
    a = OpenAICompatAdapter(fake_server.base_url, "qwen2.5:7b", timeout_s=5, temperature=0)
    assert [m.name for m in await a.list_models()] == ["qwen2.5:7b"]
    fake_server.replies.append("hi")
    assert await a.chat([], json_schema={"type": "object"}) == "hi"
    assert fake_server.requests[-1]["body"]["response_format"]["schema"] == {"type": "object"}


async def test_planner_valid_plan_annotated(fake_server):
    fake_server.replies.append(json.dumps(VALID_PLAN))
    policy = PermissionPolicy({}, [])
    plan = await make_plan("summarize my newest pdf", ollama(fake_server.base_url), policy)
    assert len(plan.steps) == 3
    assert plan.steps[0].index == 1 and plan.steps[0].permission == Decision.ALLOW
    assert all(s.state == "proposed" for s in plan.steps)
    assert plan.executable is False


async def test_planner_recovers_from_bad_first_reply(fake_server):
    fake_server.replies.extend(["this is not json", "```json\n" + json.dumps(VALID_PLAN) + "\n```"])
    plan = await make_plan("task", ollama(fake_server.base_url), PermissionPolicy({}, []))
    assert plan.goal.startswith("Find")
    # second request carried the rejection feedback
    assert "rejected" in fake_server.requests[-1]["body"]["messages"][-1]["content"]


async def test_planner_gives_up_honestly(fake_server):
    bad = {"goal": "x", "steps": []}
    fake_server.replies.extend([json.dumps(bad), json.dumps(bad)])
    with pytest.raises(PlanningFailed) as exc:
        await make_plan("task", ollama(fake_server.base_url), PermissionPolicy({}, []))
    assert exc.value.details


async def test_destructive_step_requires_approval(fake_server):
    plan_json = {
        "goal": "Delete duplicates",
        "steps": [{"description": "Delete duplicate files", "capability": "files", "risk": "destructive", "expected_result": "Duplicates removed"}],
    }
    fake_server.replies.append(json.dumps(plan_json))
    plan = await make_plan("task", ollama(fake_server.base_url), PermissionPolicy({}, []))
    assert plan.steps[0].permission == Decision.ASK


# ---------- a refused key is not an unreachable server ----------
# These are distinct states on purpose: reporting a rejected credential as
# "could not connect" sends the user to check their internet when the problem
# is the key, which is exactly the online/offline confusion being fixed.

@pytest.mark.parametrize("code,reason,needle", [
    (401, "auth_failed", "refused the API key"),
    (403, "auth_failed", "refused the API key"),
    (429, "rate_limited", "rate limiting"),
])
async def test_provider_errors_are_told_apart(fake_server, code, reason, needle):
    fake_server.status_override = code
    adapter = OpenAICompatAdapter(base_url=fake_server.base_url, model="m", timeout_s=5, temperature=0.2)
    adapter.api_key = "sk-wrong"
    st = await adapter.status()
    assert st.reason == reason
    assert st.server_reachable is True  # it answered; it just said no
    assert st.model_available is False
    assert needle in st.message


async def test_a_refused_key_does_not_echo_the_providers_body():
    """A provider may repeat the key back in its error; it must not reach the user."""
    from claw.models.base import ModelAuthFailed

    exc = ModelAuthFailed("The AI service refused the API key.", "Check the key and the address in Settings.")
    assert "sk-" not in f"{exc.message} {exc.hint}"


async def test_an_unreachable_server_is_still_unreachable():
    adapter = OpenAICompatAdapter(base_url="http://127.0.0.1:9", model="m", timeout_s=2, temperature=0.2)
    st = await adapter.status()
    assert st.reason == "unreachable" and st.server_reachable is False
