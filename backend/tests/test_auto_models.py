"""Automatic model choice and setup. Ollama is the labelled TEST DOUBLE."""

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from claw.api.app import create_app
from claw.models.auto import ModelManager, candidates
from claw.models.hardware import Hardware, worker_threads
from tests.conftest import TOKEN, VALID_PLAN


def hw(ram=None, vram=None, cores=8):
    return Hardware(total_ram_gb=ram, available_ram_gb=ram, cpu_cores=cores, gpu_name="GPU" if vram else None, gpu_vram_gb=vram)


def test_picks_scale_with_hardware():
    assert candidates("think", hw(32))[0].tag == "qwen2.5:14b"
    assert candidates("think", hw(16))[0].tag == "qwen2.5:7b"
    assert candidates("think", hw(8))[0].tag == "qwen2.5:3b"
    assert candidates("think", hw(4))[0].tag == "qwen2.5:1.5b"
    assert candidates("think", hw(8, vram=8))[0].tag == "qwen2.5:7b"  # a GPU lifts the choice
    assert candidates("see", hw(8)) == []  # no screen-reading model on small machines
    assert candidates("see", hw(16))[0].tag == "qwen2.5vl:3b"
    assert candidates("think", hw(None))[0].tag == "qwen2.5:3b"  # unknown memory: stay modest


def test_leaves_cores_free():
    assert worker_threads(2) == 1 and worker_threads(4) == 3 and worker_threads(8) == 6


async def wait_for(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met")


async def test_downloads_think_then_see(fake_server):
    fake_server.models = []
    mgr = ModelManager(fake_server.base_url, hardware=hw(16))
    mgr.start()
    await wait_for(lambda: mgr.roles["see"].status == "installed")
    assert fake_server.pulls == ["qwen2.5:7b", "qwen2.5vl:3b"]
    assert mgr.ready() and mgr.model_for("think") == "qwen2.5:7b"
    await mgr.stop()


async def test_falls_back_when_model_not_in_library(fake_server):
    fake_server.models = []
    fake_server.library = {"qwen2.5:3b"}
    mgr = ModelManager(fake_server.base_url, hardware=hw(16))
    mgr.start()
    await wait_for(lambda: mgr.roles["think"].status == "installed")
    assert mgr.model_for("think") == "qwen2.5:3b"
    assert fake_server.pulls[:2] == ["qwen2.5:7b", "qwen2.5:3b"]
    await mgr.stop()


async def test_already_installed_is_not_downloaded_again(fake_server):
    fake_server.models = ["qwen2.5:7b"]
    mgr = ModelManager(fake_server.base_url, hardware=hw(14))
    await mgr.refresh()
    assert mgr.ready() and fake_server.pulls == []


async def test_ollama_missing_is_explained():
    mgr = ModelManager("http://127.0.0.1:9", hardware=hw(16))
    await mgr.refresh()
    assert mgr.ollama_reachable is False and not mgr.ready()
    assert "Ollama" in mgr.not_ready_message()[0]


async def test_progress_reported_while_downloading(fake_server):
    fake_server.models = []
    fake_server.pull_steps, fake_server.pull_delay = 5, 0.15
    mgr = ModelManager(fake_server.base_url, hardware=hw(8))
    mgr.start()
    await wait_for(lambda: 0 < mgr.roles["think"].as_dict()["progress"] < 1)
    assert "downloading" in mgr.not_ready_message()[0]
    await wait_for(lambda: mgr.ready())
    await mgr.stop()


async def test_unload_frees_memory(fake_server):
    mgr = ModelManager(fake_server.base_url, hardware=hw(14))
    await mgr.refresh()
    await mgr.unload_all()
    assert fake_server.unloads == ["qwen2.5:7b"]


def test_api_auto_mode_end_to_end(tmp_path, fake_server, monkeypatch):
    """Fresh install: no model chosen by the user; Claw downloads one, then plans with it."""
    import claw.models.auto as auto

    monkeypatch.setattr(auto, "detect", lambda: hw(16, cores=8))
    fake_server.models = []
    data = tmp_path / "data"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({"model": {"base_url": fake_server.base_url}}))
    with TestClient(create_app(data, TOKEN), base_url="http://127.0.0.1") as c:
        c.headers["X-Claw-Token"] = TOKEN
        end = time.time() + 10
        while time.time() < end and not c.get("/models/auto").json()["ready"]:
            time.sleep(0.05)
        info = c.get("/models/auto").json()
        assert info["ready"] and info["roles"]["think"]["model"] == "qwen2.5:7b"
        status = c.get("/models/status").json()
        assert status["auto"] and status["model_available"] and status["model"] == "qwen2.5:7b"
        fake_server.replies.append(json.dumps(VALID_PLAN))
        r = c.post("/tasks/plan", json={"task": "Plan something useful"})
        assert r.status_code == 200, r.text
        sent = fake_server.requests[-1]["body"]
        assert sent["model"] == "qwen2.5:7b"
        assert sent["options"]["num_thread"] == 6 and sent["keep_alive"] == "2m"


def test_api_task_before_model_ready_is_explained(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({"model": {"base_url": "http://127.0.0.1:9"}}))
    c = TestClient(create_app(data, TOKEN), base_url="http://127.0.0.1")
    c.headers["X-Claw-Token"] = TOKEN
    c.get("/models/status")
    r = c.post("/tasks/plan", json={"task": "Plan something useful"})
    assert r.status_code == 502 and "Ollama" in r.json()["error"]["message"]
