"""Switching back to the local brain must not be refused by a leftover address.

The first real Windows run could not leave online mode: choosing the local
brain and pressing Save silently put the setting back to online.

The cause was a validation rule, not the page. Someone who has tried an online
model has a base_url pointing at that provider. The settings page sends the
whole object back, so switching mode to "builtin" submits that address
alongside it - and the rule that keeps model servers on this computer ran for
every mode except "cloud", rejected the address, and failed the save.

The rule is right; its scope was wrong. Only "custom" talks to the address in
these settings. "builtin" asks the managed brain for an adapter and "service"
uses the address built into the edition, so for those two the field is dead
weight that could nonetheless veto the save. The effect was backwards: it
blocked the safest move a person can make, away from a remote model and onto
the one on their own machine.
"""

from __future__ import annotations

import pytest

from claw.config import ConfigError, SettingsStore

GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"


def _raw(mode: str, base_url: str = GEMINI, **model):
    return {"model": {"mode": mode, "provider": "openai_compatible",
                      "base_url": base_url, "allow_remote_server": False, **model}}


@pytest.mark.parametrize("mode", ["builtin", "service"])
def test_leaving_an_online_model_is_allowed(mode):
    """The bug itself: the address is irrelevant to these modes, so it cannot veto them."""
    settings = SettingsStore.validate(_raw(mode))
    assert settings.model.mode == mode


def test_the_address_is_kept_not_erased():
    """Someone who switches to local and back should not have to retype it."""
    settings = SettingsStore.validate(_raw("builtin"))
    assert settings.model.base_url == GEMINI


def test_custom_still_has_to_stay_on_this_computer():
    """The protection this rule exists for is untouched: custom talks to the address."""
    with pytest.raises(ConfigError) as exc:
        SettingsStore.validate(_raw("custom", model="x"))
    assert "not on this computer" in str(exc.value.problems)


def test_custom_may_be_remote_when_the_developer_switch_is_on():
    settings = SettingsStore.validate(
        {"model": {"mode": "custom", "provider": "openai_compatible", "base_url": GEMINI,
                   "model": "x", "allow_remote_server": True}})
    assert settings.model.mode == "custom"


def test_a_local_address_is_still_fine_everywhere():
    settings = SettingsStore.validate(_raw("custom", base_url="http://127.0.0.1:8080", model="x"))
    assert settings.model.base_url == "http://127.0.0.1:8080"


# ---------------------------------------------------------------------------
# The protection, at the place it actually matters.
#
# Narrowing the settings rule opened a hole, which is worth recording plainly:
# /models/probe built an adapter from whatever it was sent, whatever the mode.
# While the rule refused a remote address on a "builtin" save it also, by
# accident, kept such a configuration from ever reaching that endpoint. Scoping
# the rule removed the accident, so the endpoint now refuses on its own terms -
# which is where the refusal belongs, because dialling is what it does.
#
# The guard watches all three doors for the same reason test_editions does:
# socket.connect alone is enough on Linux and sees nothing on Windows, where
# the proactor loop connects through overlapped I/O.


@pytest.fixture
def reached(monkeypatch):
    """Records every non-loopback host anything tries to open, and refuses it."""
    import asyncio.proactor_events
    import asyncio.selector_events
    import socket

    seen: list[str] = []

    def blocked(address) -> bool:
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in ("127.0.0.1", "::1", "localhost"):
            return False
        seen.append(host)
        return True

    real_connect = socket.socket.connect

    def guard(self, address, *a, **kw):
        if blocked(address):
            raise OSError(101, "Network is unreachable")
        return real_connect(self, address, *a, **kw)

    monkeypatch.setattr(socket.socket, "connect", guard)
    for loop_cls in (asyncio.selector_events.BaseSelectorEventLoop,
                     asyncio.proactor_events.BaseProactorEventLoop):
        real_sock_connect = loop_cls.sock_connect

        def guard_async(self, sock, address, *a, _real=real_sock_connect, **kw):
            if blocked(address):
                raise OSError(101, "Network is unreachable")
            return _real(self, sock, address, *a, **kw)

        monkeypatch.setattr(loop_cls, "sock_connect", guard_async)
    return seen


REMOTE = "203.0.113.5"       # TEST-NET-3: reserved for documentation, routable nowhere


@pytest.mark.parametrize("mode", ["builtin", "service"])
def test_probe_does_not_dial_an_address_the_mode_never_uses(make_client, reached, mode):
    client = make_client({"model": {"mode": "builtin"}})
    r = client.post("/models/probe", json={
        "mode": mode, "provider": "openai_compatible",
        "base_url": f"http://{REMOTE}:11434", "allow_remote_server": False,
    })
    assert r.status_code == 200, r.text
    assert reached == [], f"probe contacted {reached}"


def test_probe_still_dials_for_the_modes_that_do_use_it(make_client, reached):
    """The endpoint is not simply dead: custom is what it is for, and custom is
    only reachable remotely once the developer switch is on."""
    client = make_client({"model": {"mode": "builtin"}})
    r = client.post("/models/probe", json={
        "mode": "custom", "provider": "openai_compatible", "model": "x",
        "base_url": f"http://{REMOTE}:11434", "allow_remote_server": True,
    })
    assert r.status_code == 200, r.text
    assert reached == [REMOTE], "custom mode should have tried the address it was given"


def test_saving_a_remote_address_under_custom_is_still_refused(make_client):
    """End to end, through the API rather than the validator."""
    client = make_client({"model": {"mode": "builtin"}})
    current = client.get("/settings").json()["settings"]
    current["model"].update({"mode": "custom", "model": "x",
                             "base_url": f"http://{REMOTE}:11434", "allow_remote_server": False})
    r = client.put("/settings", json=current)
    assert r.status_code == 422
    assert "not on this computer" in r.text


def test_saving_the_local_brain_succeeds_even_with_a_remote_address_left_over(make_client):
    """The bug the user hit, through the API: choose the local brain, press Save."""
    client = make_client({"model": {"mode": "cloud", "base_url": GEMINI,
                                    "model": "gemini-2.0-flash", "api_key": "x"}})
    current = client.get("/settings").json()["settings"]
    current["model"]["mode"] = "builtin"
    r = client.put("/settings", json=current)
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["model"]["mode"] == "builtin"
    assert client.get("/settings").json()["settings"]["model"]["mode"] == "builtin"
