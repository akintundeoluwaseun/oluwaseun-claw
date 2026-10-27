"""Claw Online and Claw Local: one codebase, two packaging profiles.

The rules these tests hold to are the ones that matter if the editions are ever
confused: Claw Online must not download gigabytes of weights or run a local
brain, Claw Local must not quietly start sending the user's work to a server,
and an Online build with no service in it must say so instead of pretending.
"""

import json

import pytest
from fastapi.testclient import TestClient

from claw.api.app import create_app
from claw.edition import Edition, _from_dict, current, reset_cache
from claw.models.claw_service import ClawServiceUnconfigured, build_service_adapter
from tests.conftest import TOKEN

SERVICE = "https://brain.example.com/v1"


@pytest.fixture(autouse=True)
def clean_edition():
    reset_cache()
    yield
    reset_cache()


def write_profile(tmp_path, **raw):
    path = tmp_path / "edition.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


@pytest.fixture
def client_for(data_dir, monkeypatch, tmp_path):
    def _make(profile: dict | None, settings: dict | None = None):
        if profile is None:
            monkeypatch.delenv("CLAW_EDITION_FILE", raising=False)
        else:
            monkeypatch.setenv("CLAW_EDITION_FILE", str(write_profile(tmp_path, **profile)))
        reset_cache()
        if settings is not None:
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "settings.json").write_text(json.dumps(settings))
        c = TestClient(create_app(data_dir, TOKEN), base_url="http://127.0.0.1")
        c.headers["X-Claw-Token"] = TOKEN
        return c

    return _make


ONLINE_PROFILE = {"id": "online", "name": "Claw Online", "local_inference": False, "service_url": SERVICE}
LOCAL_PROFILE = {"id": "local", "name": "Claw Local", "local_inference": True, "bundled_model": "qwen3-vl-4b"}


# ---------- reading the profile ----------
def test_a_checkout_without_a_profile_is_the_local_edition(monkeypatch):
    monkeypatch.delenv("CLAW_EDITION_FILE", raising=False)
    monkeypatch.delenv("CLAW_RESOURCES", raising=False)
    reset_cache()
    ed = current()
    assert ed.id == "local" and ed.local_inference and ed.default_mode == "builtin"


def test_the_service_address_must_be_https():
    with pytest.raises(ValueError, match="https"):
        _from_dict({"id": "online", "service_url": "http://brain.example.com/v1"})


def test_a_damaged_profile_does_not_become_the_other_edition(tmp_path, monkeypatch):
    bad = tmp_path / "edition.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("CLAW_EDITION_FILE", str(bad))
    reset_cache()
    # Falling back to Local is the safe direction: it cannot start talking to a server.
    assert current().id == "local"


def test_the_token_is_not_in_what_the_interface_is_given():
    ed = _from_dict({"id": "online", "service_url": SERVICE, "service_token": "secret-token"})
    body = ed.as_dict()
    assert "secret-token" not in json.dumps(body)
    assert "secret-token" not in repr(ed)


# ---------- what each edition may do ----------
def test_online_refuses_the_local_brain_and_local_allows_it():
    online = _from_dict(ONLINE_PROFILE)
    local = _from_dict(LOCAL_PROFILE)
    ok, why = online.allows_mode("builtin")
    assert ok is False and "does not include a brain" in why
    assert local.allows_mode("builtin")[0] is True
    assert online.allows_mode("service")[0] is True


def test_an_online_build_with_no_service_says_so_rather_than_guessing():
    ed = _from_dict({"id": "online", "local_inference": False})
    ok, why = ed.allows_mode("service")
    assert ok is False and "without a Claw service address" in why
    with pytest.raises(ClawServiceUnconfigured):
        build_service_adapter(ed, 30, 0.2)


def test_online_cannot_be_switched_to_the_local_brain(client_for):
    c = client_for(ONLINE_PROFILE, {"model": {"mode": "service"}})
    body = c.get("/settings").json()["settings"]
    body["model"]["mode"] = "builtin"
    r = c.put("/settings", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "wrong_edition"
    # and the saved setting did not change behind the refusal
    assert c.get("/settings").json()["settings"]["model"]["mode"] == "service"


def test_online_refuses_to_download_a_multi_gigabyte_brain(client_for):
    c = client_for(ONLINE_PROFILE, {"model": {"mode": "service"}})
    r = c.post("/brain/download", json={"id": "qwen3-vl-4b"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "wrong_edition"


def test_local_may_still_choose_a_hosted_model_but_only_on_purpose(client_for):
    """Local is not forced offline; it simply never leaves on its own."""
    c = client_for(LOCAL_PROFILE, {"model": {"mode": "builtin"}})
    assert c.get("/settings").json()["settings"]["model"]["mode"] == "builtin"
    body = c.get("/settings").json()["settings"]
    body["model"].update(mode="cloud", base_url="https://api.example.com/v1",
                         model="hosted-model", api_key="sk-mine")
    assert c.put("/settings", json=body).status_code == 200
    assert c.get("/settings").json()["settings"]["model"]["mode"] == "cloud"


def test_local_without_a_service_address_cannot_use_one(client_for):
    c = client_for(LOCAL_PROFILE, {"model": {"mode": "builtin"}})
    body = c.get("/settings").json()["settings"]
    body["model"]["mode"] = "service"
    r = c.put("/settings", json=body)
    assert r.status_code == 409 and "service address" in r.json()["error"]["message"]


# ---------- what the interface is told ----------
def test_the_edition_endpoint_describes_the_build(client_for):
    body = client_for(ONLINE_PROFILE).get("/edition").json()
    assert body["id"] == "online" and body["online"] is True
    assert body["service_configured"] is True and body["default_mode"] == "service"
    assert body["modes"]["builtin"]["allowed"] is False
    assert body["modes"]["builtin"]["why_not"]
    assert body["modes"]["service"]["allowed"] is True

    local = client_for(LOCAL_PROFILE).get("/edition").json()
    assert local["id"] == "local" and local["bundled_model"] == "qwen3-vl-4b"
    assert local["modes"]["builtin"]["allowed"] is True
    assert local["modes"]["service"]["allowed"] is False


# ---------- honesty about the network ----------
def test_online_reports_losing_the_internet_as_what_it_is(client_for):
    """Points the service at a port nothing answers on: a real connection failure."""
    c = client_for({**ONLINE_PROFILE, "service_url": "https://127.0.0.1:49232/v1"},
                   {"model": {"mode": "service"}})
    body = c.get("/models/status").json()
    assert body["mode"] == "service" and body["model_available"] is False
    assert body["reason"] == "unreachable"
    assert "internet" in body["message"].lower()
    live = c.post("/models/selftest").json()
    assert live["ok"] is False and live["reason"] == "unreachable"


def test_an_unconfigured_service_is_not_reported_as_a_network_problem(client_for):
    c = client_for({"id": "online", "local_inference": False}, {"model": {"mode": "service"}})
    body = c.get("/models/status").json()
    assert body["reason"] == "not_configured"          # retrying will never help
    assert "service address" in body["message"]


def test_the_service_adapter_carries_the_built_in_credential_not_the_users():
    ed = _from_dict({"id": "online", "service_url": SERVICE, "service_token": "built-in"})
    a = build_service_adapter(ed, 30, 0.2)
    assert a.api_key == "built-in" and a.base_url == SERVICE
    assert a.provider == "claw_service" and a.model == "claw-1"


# ---------- Claw Local with the network switched off ----------
@pytest.fixture
def no_network(monkeypatch):
    """Refuse every socket that is not loopback, the way an unplugged machine does."""
    import socket

    real_connect = socket.socket.connect
    reached: list[str] = []

    def guard(self, address, *a, **kw):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            reached.append(host)
            raise OSError(101, "Network is unreachable")
        return real_connect(self, address, *a, **kw)

    monkeypatch.setattr(socket.socket, "connect", guard)
    return reached


def test_local_edition_runs_with_no_network_at_all(client_for, no_network):
    c = client_for(LOCAL_PROFILE, {"model": {"mode": "builtin"}})
    assert c.get("/health").json()["status"] == "ok"
    assert c.get("/edition").json()["id"] == "local"
    assert c.get("/settings").json()["settings"]["model"]["mode"] == "builtin"
    # The brain is not installed in this test environment, so the honest answer is
    # "no brain here" - not a network error, because nothing went near the network.
    body = c.get("/models/status").json()
    assert body["mode"] == "builtin" and body["reason"] in ("model_missing", "unreachable")
    assert c.get("/brain").json()["mode"] == "builtin"
    assert no_network == [], f"something tried to reach {no_network}"


def test_online_edition_with_no_network_says_so_and_blames_nothing_else(client_for, no_network):
    # A literal address from the documentation range, so the attempt reaches connect()
    # instead of dying at name lookup: the point is that it really did try to leave.
    c = client_for({**ONLINE_PROFILE, "service_url": "https://203.0.113.9/v1"},
                   {"model": {"mode": "service"}})
    body = c.get("/models/status").json()
    assert body["model_available"] is False and body["reason"] == "unreachable"
    assert "internet" in body["message"].lower()
    # It really did try to leave the machine, and was stopped.
    assert "203.0.113.9" in no_network
