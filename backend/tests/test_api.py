import json

from fastapi.testclient import TestClient

from claw.api.app import create_app
from claw.logging_setup import redact, register_secret
from tests.conftest import TOKEN, VALID_PLAN


def settings_for(server, model="qwen2.5:7b"):
    return {"model": {"mode": "custom", "provider": "ollama", "base_url": server.base_url, "model": model}}


def test_health_needs_no_token(data_dir):
    c = TestClient(create_app(data_dir, TOKEN), base_url="http://127.0.0.1")
    r = c.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_token_required(data_dir):
    c = TestClient(create_app(data_dir, TOKEN), base_url="http://127.0.0.1")
    assert c.get("/settings").status_code == 401
    assert c.get("/settings", headers={"X-Claw-Token": "wrong" * 10}).status_code == 401


def test_non_loopback_host_rejected(data_dir):
    c = TestClient(create_app(data_dir, TOKEN), base_url="http://evil.example")
    assert c.get("/health").status_code == 403


def test_short_token_refused(data_dir):
    import pytest

    with pytest.raises(ValueError):
        create_app(data_dir, "short")


def test_settings_roundtrip(make_client, fake_server):
    c = make_client()
    r = c.put("/settings", json=settings_for(fake_server))
    assert r.status_code == 200
    assert c.get("/settings").json()["settings"]["model"]["model"] == "qwen2.5:7b"


def test_invalid_settings_explained(make_client):
    r = make_client().put("/settings", json={"model": {"base_url": "ftp://x"}})
    assert r.status_code == 422
    assert r.json()["error"]["details"]


def test_damaged_settings_file_reported_not_crash(make_client, data_dir):
    data_dir.mkdir(parents=True)
    (data_dir / "settings.json").write_text("{oops")
    c = make_client()
    body = c.get("/settings").json()
    assert body["error"]["message"]
    assert c.get("/health").json()["settings_ok"] is False
    r = c.post("/tasks/plan", json={"task": "do something"})
    assert r.status_code == 409


def test_probe_unsaved_config(make_client, fake_server):
    r = make_client().post("/models/probe", json={"base_url": fake_server.base_url, "model": "qwen2.5:7b"})
    assert r.status_code == 200 and r.json()["model_available"] is True


def test_model_status_when_server_down(make_client):
    c = make_client({"model": {"mode": "custom", "base_url": "http://127.0.0.1:9", "model": "x"}})
    body = c.get("/models/status").json()
    assert body["server_reachable"] is False and "Could not connect" in body["message"]


def test_plan_end_to_end_and_history(make_client, fake_server):
    fake_server.replies.append(json.dumps(VALID_PLAN))
    c = make_client(settings_for(fake_server))
    r = c.post("/tasks/plan", json={"task": "Find the latest PDF in Downloads and summarize it"})
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["status"] == "planned"
    assert len(task["plan"]["steps"]) == 3
    assert [e["kind"] for e in task["events"]] == ["requested", "model_call", "planned"]
    hist = c.get("/tasks", params={"q": "PDF"}).json()["tasks"]
    assert hist and hist[0]["id"] == task["id"]
    assert c.get("/tasks", params={"q": "nothing-like-this"}).json()["tasks"] == []


def test_plan_failure_recorded_truthfully(make_client, fake_server):
    fake_server.status_override = 500
    c = make_client(settings_for(fake_server))
    r = c.post("/tasks/plan", json={"task": "do something"})
    assert r.status_code == 502
    task_id = r.headers["x-claw-task-id"]
    task = c.get(f"/tasks/{task_id}").json()
    assert task["status"] == "failed" and task["error"]
    assert task["plan"] is None


def test_plan_with_no_model_selected(make_client, fake_server):
    c = make_client({"model": {"mode": "custom", "base_url": fake_server.base_url, "model": ""}})
    r = c.post("/tasks/plan", json={"task": "do something"})
    assert r.status_code == 502
    assert "No model" in r.json()["error"]["message"]


def test_task_too_short_rejected(make_client):
    assert make_client().post("/tasks/plan", json={"task": "x"}).status_code == 422


def test_like_wildcards_escaped(make_client, fake_server):
    fake_server.replies.append(json.dumps(VALID_PLAN))
    c = make_client(settings_for(fake_server))
    c.post("/tasks/plan", json={"task": "plain task text"})
    assert c.get("/tasks", params={"q": "%"}).json()["tasks"] == []


def test_redaction():
    register_secret("supersecretvalue123")
    out = redact("token=abc123 Authorization: Bearer xyz supersecretvalue123 api_key: k-1")
    assert "abc123" not in out and "xyz" not in out and "supersecretvalue123" not in out and "k-1" not in out


def test_history_search_covers_answers_and_errors(make_client, data_dir):
    c = make_client()
    db = c.app.state.claw.db
    t1 = db.create_task("Research hotels", None)
    db.update_task(t1, status="completed", result={"final_answer": "Saved Ekiti Grand Hotel contacts"})
    t2 = db.create_task("Open the app", None)
    db.update_task(t2, status="failed", error="Windows is locked")
    assert [t["id"] for t in c.get("/tasks", params={"q": "ekiti grand"}).json()["tasks"]] == [t1]
    assert [t["id"] for t in c.get("/tasks", params={"q": "locked"}).json()["tasks"]] == [t2]


# ---------- cloud mode over the API ----------
CLOUD = {"model": {"mode": "cloud", "base_url": "https://api.example.com/v1",
                   "model": "hosted-model", "api_key": "sk-secret-value-123"}}


def test_api_key_is_never_sent_to_the_page(make_client):
    c = make_client(CLOUD)
    body = c.get("/settings").json()["settings"]
    assert body["model"]["api_key"] != "sk-secret-value-123"
    assert body["model"]["api_key_set"] is True
    assert "sk-secret-value-123" not in json.dumps(body)


def test_saving_settings_without_touching_the_key_keeps_it(make_client):
    c = make_client(CLOUD)
    body = c.get("/settings").json()["settings"]
    body["model"]["temperature"] = 0.5  # change something else and send it back verbatim
    r = c.put("/settings", json=body)
    assert r.status_code == 200
    assert r.json()["settings"]["model"]["api_key_set"] is True
    # The stored key is unchanged: the page never saw it, so it cannot have overwritten it.
    again = c.get("/settings").json()["settings"]
    assert again["model"]["api_key_set"] is True and again["model"]["temperature"] == 0.5


def test_the_key_can_be_replaced_and_cleared(make_client):
    c = make_client(CLOUD)
    body = c.get("/settings").json()["settings"]
    body["model"]["api_key"] = "sk-a-new-one"
    assert c.put("/settings", json=body).status_code == 200
    body = c.get("/settings").json()["settings"]
    assert body["model"]["api_key_set"] is True
    body["model"]["api_key"] = ""
    assert c.put("/settings", json=body).status_code == 200
    assert c.get("/settings").json()["settings"]["model"]["api_key_set"] is False


def test_cloud_mode_reports_its_model_without_a_brain(make_client):
    c = make_client(CLOUD)
    assert c.get("/health").json()["status"] == "ok"
    brain = c.get("/brain").json()
    assert brain["mode"] == "cloud"  # no brain is installed, and none is needed


def test_testing_a_connection_does_not_need_the_key_retyped(make_client, monkeypatch):
    """The page never has the key, so 'Test connection' sends the placeholder back."""
    seen = {}

    class Probe:
        provider = "openai_compatible"
        api_key = ""

        def __init__(self, **kw):
            pass

        async def status(self):
            from claw.models.base import ModelStatus

            seen["key"] = self.api_key
            return ModelStatus(server_reachable=True, model_available=True, provider="openai_compatible",
                               base_url="https://api.example.com/v1", model="hosted-model",
                               message="", available_models=["m"])

    monkeypatch.setitem(__import__("claw.models.registry", fromlist=["_ADAPTERS"])._ADAPTERS,
                        "openai_compatible", Probe)
    c = make_client(CLOUD)
    body = dict(CLOUD["model"], api_key="__keep__")
    r = c.post("/models/probe", json=body)
    assert r.status_code == 200
    assert seen["key"] == "sk-secret-value-123"  # resolved, not sent as the placeholder
