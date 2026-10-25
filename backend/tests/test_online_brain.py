"""Online brain (Google Gemini with the user's key). Google is the TEST DOUBLE."""

import json

import pytest
from fastapi.testclient import TestClient

from claw.api.app import create_app
from claw.models.base import ChatMessage, ModelError
from claw.models.gemini import GeminiAdapter, QuotaExhausted, gemini_base
from claw.secrets import SecretStore, hint
from tests.conftest import TOKEN, VALID_PLAN
from tests.fake_gemini_server import VALID_KEY, FakeGemini


@pytest.fixture
def gemini(monkeypatch):
    with FakeGemini() as g:
        monkeypatch.setenv("CLAW_GEMINI_BASE", g.base_url)
        GeminiAdapter._exhausted.clear()
        GeminiAdapter._schema_style = "responseFormat"
        yield g


def test_override_only_for_local_test_servers(monkeypatch):
    monkeypatch.setenv("CLAW_GEMINI_BASE", "https://evil.example")
    assert gemini_base() == "https://generativelanguage.googleapis.com"


async def test_picks_flash_lite_and_sends_schema(gemini):
    a = GeminiAdapter(VALID_KEY)
    gemini.replies.append('{"ok": true}')
    out = await a.chat([ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="hi")], json_schema={"type": "object"})
    assert out == '{"ok": true}'
    req = gemini.requests[-1]
    assert req["model"] == "gemini-3.5-flash-lite"
    assert req["body"]["systemInstruction"]["parts"][0]["text"] == "sys"
    assert req["body"]["generationConfig"]["responseFormat"]["text"]["schema"] == {"type": "object"}


async def test_falls_back_to_legacy_schema_field(gemini):
    gemini.reject_response_format = True
    gemini.replies.append("{}")
    await GeminiAdapter(VALID_KEY).chat([ChatMessage(role="user", content="hi")], json_schema={"type": "object"})
    cfg = gemini.requests[-1]["body"]["generationConfig"]
    assert cfg["responseMimeType"] == "application/json" and cfg["responseJsonSchema"] == {"type": "object"}


async def test_moves_to_next_model_when_daily_limit_hit(gemini):
    gemini.exhausted = {"gemini-3.5-flash-lite"}
    gemini.replies.append("{}")
    a = GeminiAdapter(VALID_KEY)
    await a.chat([ChatMessage(role="user", content="hi")])
    assert a.model == "gemini-3.8-flash"


async def test_all_models_exhausted_is_explained(gemini):
    gemini.exhausted = {"gemini-3.5-flash-lite", "gemini-3.8-flash"}
    with pytest.raises(QuotaExhausted) as exc:
        await GeminiAdapter(VALID_KEY).chat([ChatMessage(role="user", content="hi")])
    assert "free" in exc.value.message and "Lagos" in exc.value.hint


async def test_bad_key_is_explained(gemini):
    with pytest.raises(ModelError) as exc:
        await GeminiAdapter("AIza-wrong-key-000000000000000").list_models()
    assert "did not accept" in exc.value.message


def test_secret_store_roundtrip_and_hint(tmp_path):
    s = SecretStore(tmp_path)
    s.set("k", "AIzaSECRETVALUE1234")
    assert SecretStore(tmp_path).get("k") == "AIzaSECRETVALUE1234"
    assert "AIzaSECRETVALUE1234" not in (tmp_path / "secrets.bin").read_text()
    assert hint("AIzaSECRETVALUE1234") == "••••1234"
    s.set("k", None)
    assert SecretStore(tmp_path).get("k") is None


def test_onboarding_online_flow(tmp_path, gemini):
    data = tmp_path / "data"
    with TestClient(create_app(data, TOKEN), base_url="http://127.0.0.1") as c:
        c.headers["X-Claw-Token"] = TOKEN
        brain = c.get("/brain").json()
        assert brain["mode"] == "unset" and not brain["online"]["connected"]
        r = c.post("/tasks/plan", json={"task": "Plan something useful"})
        assert r.status_code == 502 and "Choose how Claw thinks" in r.json()["error"]["message"]
        bad = c.post("/brain/online", json={"api_key": "AIza-wrong-key-000000000000000"})
        assert bad.status_code == 422 and "did not accept" in bad.json()["error"]["message"]
        assert c.post("/brain/online", json={"api_key": "short"}).status_code == 422
        ok = c.post("/brain/online", json={"api_key": "  " + VALID_KEY + "  "})
        assert ok.status_code == 200 and ok.json()["mode"] == "online"
        assert ok.json()["online"]["key_hint"] == "••••" + VALID_KEY[-4:]
        settings_text = (data / "settings.json").read_text()
        assert VALID_KEY not in settings_text  # key kept out of the settings file
        assert VALID_KEY not in json.dumps(c.get("/settings").json())  # and never sent back
        status = c.get("/models/status").json()
        assert status["mode"] == "online" and status["model_available"] and status["model"] == "gemini-3.5-flash-lite"
        gemini.replies.append(json.dumps(VALID_PLAN))
        r = c.post("/tasks/plan", json={"task": "Find the latest PDF and summarize it"})
        assert r.status_code == 200 and r.json()["model"] == "Google AI"
        assert c.post("/brain/disconnect").json()["mode"] == "unset"
    log = (data / "logs").glob("*.log")
    for f in log:
        assert VALID_KEY not in f.read_text()


def test_choose_offline(tmp_path):
    with TestClient(create_app(tmp_path / "d", TOKEN), base_url="http://127.0.0.1") as c:
        c.headers["X-Claw-Token"] = TOKEN
        b = c.post("/brain/offline").json()
        assert b["mode"] == "offline" and "roles" in b["offline"]
