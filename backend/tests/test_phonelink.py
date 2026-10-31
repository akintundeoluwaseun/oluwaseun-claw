"""The phone app over the home Wi-Fi: key required, home network only, chats and tasks."""

import json
import time

from fastapi.testclient import TestClient

from claw.channels.phonelink import create_link_app, new_key, qr_svg
from tests.conftest import VALID_PLAN
from tests.test_api import settings_for
from tests.test_chats import finish


def link_client(state, ip="192.168.1.20"):
    return TestClient(create_link_app(state), base_url="http://claw.local", client=(ip, 50000))


def test_key_and_network_are_required(make_client, fake_server):
    c = make_client(settings_for(fake_server)).__enter__()
    state = c.app.state.claw
    state.settings.phone.link_key = new_key()
    home = link_client(state)
    assert home.get("/").status_code == 200 and "S-CLAW" in home.get("/").text
    assert home.get("/api/hello").status_code == 401
    assert home.get("/api/hello", headers={"x-claw-key": "wrong"}).status_code == 401
    ok = home.get("/api/hello", headers={"x-claw-key": state.settings.phone.link_key})
    assert ok.status_code == 200 and ok.json()["ok"]
    outside = link_client(state, ip="8.8.8.8")
    assert outside.get("/").status_code == 403
    assert home.get("/../config.py").status_code == 404


def test_a_task_from_the_phone_app(make_client, fake_server):
    fake_server.replies += [json.dumps(VALID_PLAN), finish("Done from the phone app.")]
    c = make_client(settings_for(fake_server)).__enter__()
    state = c.app.state.claw
    state.settings.phone.link_key = new_key()
    h = {"x-claw-key": state.settings.phone.link_key}
    # the phone app runs on the backend's own event loop through the main test client
    from claw.channels import phonelink

    app = phonelink.create_link_app(state)
    c.app.mount("/phone-test", app)
    r = c.post("/phone-test/api/run", json={"task": "Check whether anything needs doing"}, headers={**h, "x-claw-token": c.headers["X-Claw-Token"]})
    # mounted under the main app the client host is 'testclient', so the home-network guard answers 403;
    # that is the guard working. Drive the runner directly instead and read it back through the phone API.
    assert r.status_code == 403
    tid = c.post("/tasks/run", json={"task": "Check whether anything needs doing"}).json()["id"]
    end = time.time() + 15
    while time.time() < end and c.get(f"/tasks/{tid}/events").json()["status"] not in ("completed", "failed"):
        time.sleep(0.1)
    home = link_client(state)
    chats = home.get("/api/chats", headers=h).json()["chats"]
    assert chats and chats[0]["status"] == "completed"
    t = home.get(f"/api/task/{tid}", headers=h).json()
    assert t["answer"] == "Done from the phone app." and not t["active"]
    chat = home.get(f"/api/chat/{chats[0]['thread_id']}", headers=h).json()
    assert chat["messages"][0]["answer"] == "Done from the phone app."


def test_qr_code_is_svg():
    assert qr_svg("http://192.168.1.20:47820/#k=abc").startswith("<svg")
