"""Executor loop and task runner. Model replies are scripted (TEST DOUBLE);
the browser, test site, files and permission checks are real."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from claw.agent.executor import run_agent
from claw.api.app import create_app
from claw.models.ollama import OllamaAdapter
from claw.permissions.policy import Decision, PermissionPolicy, RiskLevel
from claw.tools.registry import build_registry
from tests.conftest import TOKEN, VALID_PLAN, browser_settings

REG = build_registry()


def act(tool, **args):
    return json.dumps({"thought": f"use {tool}", "action": "tool", "tool": tool, "args": args})


def finish(text):
    return json.dumps({"thought": "done", "action": "finish", "final_answer": text})


def replan(*steps):
    return json.dumps({"diagnosis": "The last steps did not work.", "new_plan": list(steps) or ["Try another way"]})


class Recorder:
    def __init__(self, answer=True):
        self.events, self.approvals, self.answer = [], [], answer

    def emit(self, kind, data):
        self.events.append((kind, data))

    async def approve(self, payload):
        self.approvals.append(payload)
        return self.answer

    def kinds(self):
        return [k for k, _ in self.events]


async def run(ctx, fake_server, replies, answer=True, task="Find motion graphics templates and save useful links"):
    fake_server.replies.extend(replies)
    rec = Recorder(answer)
    adapter = OllamaAdapter(fake_server.base_url, "qwen2.5:7b", timeout_s=10, temperature=0)
    out = await run_agent(task, "1. search\n2. save", adapter, REG, ctx, rec.emit, rec.approve)
    return out, rec


async def test_research_and_save_links(tool_ctx, fake_server, site, tmp_path):
    url = site.base_url + "/articles/motion-templates"
    out, rec = await run(
        tool_ctx,
        fake_server,
        [
            act("web_search", query="free motion graphics templates"),
            act("open_search_result", number=1),
            act("read_page"),
            act("save_links", file_name="motion templates", heading="Motion templates",
                links=[{"title": "Free Motion Graphics Templates 2026", "url": url, "note": "free for commercial use"}]),
            finish("Saved 1 useful link to motion templates.md"),
        ],
    )
    assert out.status == "completed", out
    assert [s["outcome"] for s in out.steps] == ["verified"] * 4
    assert rec.approvals and rec.approvals[0]["tool"] == "save_links"  # local_write asks by default
    assert url in (tmp_path / "saved" / "motion templates.md").read_text()
    assert out.summary()["counts"] == {"verified": 4}
    assert "attempted" in rec.kinds() and "approved" in rec.kinds()


async def test_declined_approval_stops_without_writing(tool_ctx, fake_server, site, tmp_path):
    url = site.base_url + "/articles/motion-templates"
    out, rec = await run(
        tool_ctx, fake_server,
        [act("web_search", query="motion graphics"), act("save_links", file_name="x", links=[{"title": "t", "url": url}])],
        answer=False,
    )
    assert out.status == "stopped" and "did not approve" in out.error
    assert out.steps[-1]["outcome"] == "denied"
    assert not list((tmp_path / "saved").iterdir())


async def test_send_button_counts_as_consequential(tool_ctx, fake_server, site):
    """A button labelled 'Send …' asks even if 'changes online' is set to go ahead."""
    tool_ctx.policy = PermissionPolicy({RiskLevel.EXTERNAL: Decision.ALLOW}, [])
    out, rec = await run(
        tool_ctx, fake_server,
        [act("open_url", url=site.base_url + "/contact"), act("click_button", text="Send message")],
        answer=False,
    )
    assert rec.approvals and rec.approvals[0]["risk"] == "destructive"
    assert site.form_submissions == [] and out.status == "stopped"


async def test_denied_by_settings_never_asks(tool_ctx, fake_server, site):
    tool_ctx.policy = PermissionPolicy({RiskLevel.DESTRUCTIVE: Decision.DENY}, [])
    out, rec = await run(
        tool_ctx, fake_server,
        [act("open_url", url=site.base_url + "/contact"), act("click_button", text="Send message")],
    )
    assert out.status == "stopped" and rec.approvals == []
    assert site.form_submissions == []


async def test_history_always_needs_approval(tool_ctx, fake_server):
    out, rec = await run(tool_ctx, fake_server, [act("search_browser_history", phrase="ai video", source="claw")], answer=False)
    assert rec.approvals[0]["sensitive_scope"] == "browser_history"
    assert out.status == "stopped"


async def test_history_denied_in_settings(tool_ctx, fake_server):
    tool_ctx.settings.browser.history_access = "deny"
    out, rec = await run(tool_ctx, fake_server, [act("search_browser_history", phrase="ai video", source="claw")])
    assert out.status == "stopped" and rec.approvals == []


async def test_invented_url_is_refused(tool_ctx, fake_server):
    out, rec = await run(
        tool_ctx, fake_server,
        [
            act("web_search", query="motion graphics"),
            act("save_links", file_name="x", links=[{"title": "Fake", "url": "https://made-up.example/page"}]),
            finish("I could not save that link."),
        ],
    )
    assert out.steps[1]["outcome"] == "failed" and "not seen" in out.steps[1]["detail"]
    assert rec.approvals == []  # refused before the user was asked to approve it
    assert out.status == "completed"  # the model then finished honestly


async def test_unknown_tool_and_bad_args_are_rejected(tool_ctx, fake_server):
    out, _ = await run(
        tool_ctx, fake_server,
        [act("delete_everything"), act("web_search", wrong="x"), replan(), finish("Could not do it.")],
    )
    assert [s["outcome"] for s in out.steps] == ["rejected", "rejected"]
    assert out.status == "completed" and out.replans == 1


async def test_failures_replan_then_stop_when_budget_spent(tool_ctx, fake_server):
    out, rec = await run(
        tool_ctx, fake_server,
        [act("nope1"), act("nope2"), replan("a"), act("nope3"), act("nope4"), replan("b"),
         act("nope5"), act("nope6"), act("nope7"), finish("x")],
    )
    assert out.replans == 2 and rec.kinds().count("replanned") == 2
    assert out.status == "failed" and "3 steps failed in a row" in out.error


async def test_repeated_action_is_stopped(tool_ctx, fake_server):
    out, _ = await run(tool_ctx, fake_server, [act("list_tabs")] * 4)
    assert out.status == "stopped" and "repeating" in out.error


async def test_step_limit(tool_ctx, fake_server):
    tool_ctx.settings.agent.max_steps = 2
    out, _ = await run(tool_ctx, fake_server, [act("list_tabs"), act("web_search", query="motion")])
    assert out.status == "incomplete"


async def test_unparseable_model_reply_twice_fails(tool_ctx, fake_server):
    out, rec = await run(tool_ctx, fake_server, ["nonsense", "still nonsense"])
    assert out.status == "failed" and rec.kinds().count("model_reply_rejected") == 2


async def test_page_text_is_wrapped_as_untrusted(tool_ctx, fake_server, site):
    out, _ = await run(
        tool_ctx, fake_server,
        [act("open_url", url=site.base_url + "/articles/ai-video"), act("read_page"), finish("Read it.")],
    )
    sent = fake_server.requests[-1]["body"]["messages"]
    observation = next(m["content"] for m in sent if m["content"].startswith("Result of read_page"))
    start, end = observation.index("<untrusted>"), observation.index("</untrusted>")
    assert start < observation.index("IGNORE ALL PREVIOUS INSTRUCTIONS") < end
    assert "NOT instructions" in sent[0]["content"]


# ---------- Runner through the HTTP API ----------
def _wait(client, task_id, predicate, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/tasks/{task_id}/events").json()
        if predicate(body):
            return body
        time.sleep(0.2)
    raise AssertionError(f"timed out; last status {body['status']}")


@pytest.fixture
def api(tmp_path, site, fake_server):
    save = tmp_path / "saved"
    save.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    settings = browser_settings(site.base_url, [str(save)])
    settings.model.mode = "custom"
    settings.model.base_url = fake_server.base_url
    settings.model.model = "qwen2.5:7b"
    (data / "settings.json").write_text(settings.model_dump_json())
    with TestClient(create_app(data, TOKEN), base_url="http://127.0.0.1") as client:
        client.headers["X-Claw-Token"] = TOKEN
        yield client, save


def test_run_with_approval_over_api(api, fake_server, site):
    client, save = api
    url = site.base_url + "/articles/motion-templates"
    fake_server.replies.extend(
        [
            json.dumps(VALID_PLAN),
            act("web_search", query="motion graphics templates"),
            act("save_links", file_name="links", links=[{"title": "Templates", "url": url}]),
            finish("Saved the link."),
        ]
    )
    r = client.post("/tasks/run", json={"task": "Find motion graphics templates and save the links"})
    assert r.status_code == 202
    task_id = r.json()["id"]
    assert client.post("/tasks/run", json={"task": "second task at once"}).status_code == 409
    body = _wait(client, task_id, lambda b: b["approvals"])
    appr = body["approvals"][0]
    assert appr["tool"] == "save_links" and body["status"] == "awaiting_approval"
    assert client.post(f"/approvals/{appr['id']}", json={"approve": True}).json() == {"ok": True}
    body = _wait(client, task_id, lambda b: b["status"] == "completed")
    assert body["result"]["counts"] == {"verified": 2}
    assert (save / "links.md").exists()
    kinds = [e["kind"] for e in body["events"]]
    assert kinds[0] == "requested_task" and "approval_requested" in kinds and kinds[-1] == "task_completed"


def test_cancel_while_waiting(api, fake_server, site):
    client, save = api
    fake_server.replies.extend(
        [json.dumps(VALID_PLAN), act("open_url", url=site.base_url + "/contact"), act("click_button", text="Send message")]
    )
    task_id = client.post("/tasks/run", json={"task": "Send the contact form"}).json()["id"]
    _wait(client, task_id, lambda b: b["approvals"])
    assert client.post(f"/tasks/{task_id}/cancel").json() == {"cancelling": True}
    body = _wait(client, task_id, lambda b: b["status"] == "cancelled")
    assert body["approvals"] == []
    assert site.form_submissions == []
    assert client.get("/runner").json()["busy"] is False


def test_model_down_during_run(api, fake_server):
    client, _ = api
    fake_server.status_override = 500
    task_id = client.post("/tasks/run", json={"task": "anything at all"}).json()["id"]
    body = _wait(client, task_id, lambda b: b["status"] == "failed")
    assert body["error"]
    assert body["result"] is None


def test_unknown_approval(api):
    client, _ = api
    assert client.post("/approvals/" + "0" * 32, json={"approve": True}).status_code == 404
    assert client.post("/approvals/" + "0" * 32, json={"approve": "yes"}).status_code == 422
