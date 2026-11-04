"""The brain is loaded before it is asked for, not while someone waits.

Reported from a laptop: the app "takes a million years" before an answer. Part
of that was a planning call on a greeting, fixed in test_conversation.py. The
rest is this: the engine starts lazily and is stopped again after a few quiet
minutes, so the first task of a session - and the first after a break - waits
for gigabytes to come off disk before a word is planned.

The warm-up has to be invisible when it cannot help, which is most of what is
tested here: not for a hosted model, not over a running task, not without a
brain installed, and never fatal. The real function is exercised by replacing
the Brain the app builds, rather than by re-implementing its conditions in a
fake and then asserting against the fake.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TOKEN


class FakeEngine:
    def __init__(self, available=True, running=False, ctx_size=8192):
        self.loaded: list[str] = []
        self._available, self._running, self.ctx_size = available, running, ctx_size
        self.base_url, self.api_key, self.last_used = "http://127.0.0.1:8080", "", 0.0
        self.status = type("S", (), {"state": "ready", "model_id": None, "message": ""})()

    def available(self):
        return (self._available, "" if self._available else "the engine is not installed")

    def running(self):
        return self._running

    async def ensure(self, model_id, model_path, mmproj_path=None):
        self.loaded.append(model_id)
        self._running = True

    async def stop_if_idle(self, seconds):
        return None

    async def stop(self):
        self._running = False


class FakeModel:
    id = "qwen3-vl-4b"
    model_path = "/tmp/not-real.gguf"
    mmproj_path = None


class FakeBrain:
    """Only what start-up and shutdown touch."""

    def __init__(self, engine, model=FakeModel()):
        self.engine, self._model = engine, model
        self.download = type("D", (), {"status": "idle"})()
        self.hardware = type("H", (), {"total_ram_gb": 16, "as_dict": lambda self: {}, "describe": lambda self: "16 GB"})()

    def active_model(self, selected=None):
        return self._model

    def touch(self):
        pass

    async def shutdown(self):
        pass


@pytest.fixture
def warmed(monkeypatch, data_dir):
    """Start the real app with a Brain we control, and hand back its engine."""
    from claw.api import app as app_mod

    made: dict = {}

    def build(engine=None, model=FakeModel(), settings_patch=None):
        eng = engine or FakeEngine()
        monkeypatch.setattr(app_mod, "Brain", lambda *a, **k: FakeBrain(eng, model))
        app = app_mod.create_app(data_dir, TOKEN)
        made["engine"] = eng
        return app, eng

    return build


def _run(app) -> None:
    """Enter the app's lifespan long enough for the warm-up to have its turn."""
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.get("/health").json()["status"] == "ok"
        # warm_brain sleeps ~1.5s so the window opens first.
        deadline = asyncio.get_event_loop_policy().new_event_loop()
        try:
            deadline.run_until_complete(asyncio.sleep(2.2))
        finally:
            deadline.close()


def test_the_builtin_brain_is_loaded_at_start_up(warmed, data_dir):
    app, engine = warmed()
    _run(app)
    assert engine.loaded == ["qwen3-vl-4b"], (
        "the brain was not warmed, so the first real task pays the load")


def test_an_engine_already_running_is_left_alone(warmed):
    app, engine = warmed(engine=FakeEngine(running=True))
    _run(app)
    assert engine.loaded == [], "a running engine was restarted"


def test_a_missing_engine_is_not_started(warmed):
    app, engine = warmed(engine=FakeEngine(available=False))
    _run(app)
    assert engine.loaded == []


def test_nothing_is_loaded_when_no_brain_is_installed(warmed):
    app, engine = warmed(model=None)
    _run(app)
    assert engine.loaded == []


def test_a_warm_up_that_throws_does_not_stop_the_app(warmed, monkeypatch):
    engine = FakeEngine()

    async def explode(*a, **k):
        raise RuntimeError("the model file is missing")

    engine.ensure = explode
    app, engine = warmed(engine=engine)
    _run(app)          # the assertion is that this returns at all
    assert engine.loaded == []


def test_warming_is_armed_before_the_unloader(data_dir):
    """Order matters: the idle watch is what would undo this."""
    import inspect

    from claw.api import app as app_mod

    src = inspect.getsource(app_mod.create_app)
    assert src.index("asyncio.create_task(warm_brain())") < src.index("asyncio.create_task(idle_watch())")
