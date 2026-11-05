"""A 2 GB brain over a library's wifi will not always arrive in one piece.

Reported from a real install: the download reached 2 GB and failed, twice, and
only finished on the third attempt - three attempts the person had to make
themselves, each time noticing the failure and pressing the button again.

download_file already resumed from the .part file, so each of those attempts
carried on rather than starting over. What was missing was doing it without the
person: nothing retried, so one dropped connection in a two-hour download ended
it and waited for a human.

The fake library drops the connection part-way through a response here, after
Content-Length has been sent, which is what a real network does and what the
client sees as a truncated body.
"""

import asyncio

import pytest

from claw.models.hardware import Hardware
from claw.runtime import catalog, engine as engine_mod, hub
from claw.runtime.brain import Brain
from claw.runtime.store import ModelStore
from tests.fake_hub import FakeHub
from tests.make_tiny_gguf import write as write_tiny


def hw(ram=16.0, avail=12.0, cores=4):
    return Hardware(total_ram_gb=ram, available_ram_gb=avail, cpu_cores=cores,
                    gpu_name=None, gpu_vram_gb=None)


@pytest.fixture
def lib(monkeypatch, tmp_path_factory):
    big = write_tiny(tmp_path_factory.mktemp("m") / "tiny-Q4_K_M.gguf")
    with FakeHub() as h:
        monkeypatch.setenv("CLAW_HF_BASE", h.base_url)
        # Comfortably larger than the client's 1 MB read chunk, so a cut
        # part-way through leaves real bytes in the .part file - which is what
        # happens on a 2 GB file and the whole point of resuming. A fixture
        # smaller than one chunk would show no progress at all and prove
        # nothing.
        data = big.read_bytes() + b"\0" * (4 << 20)
        h.repos["Qwen/Qwen3-VL-4B-Instruct-GGUF"] = {
            "license": "apache-2.0",
            "files": {"Qwen3VL-4B-Instruct-Q4_K_M.gguf": data,
                      "mmproj-Qwen3VL-4B-Instruct-F16.gguf": b"GGUF-not-really-a-projector"},
        }
        h.payload = data
        yield h


# ---------- which failures are worth another attempt ----------
def test_a_dropped_connection_is_transient_and_a_missing_repo_is_not():
    assert hub.DownloadError("x", transient=True).transient
    assert not hub.DownloadError("x").transient            # the default is "do not retry"
    assert 503 in hub.TRANSIENT_STATUS and 429 in hub.TRANSIENT_STATUS
    assert 404 not in hub.TRANSIENT_STATUS and 403 not in hub.TRANSIENT_STATUS


async def test_the_real_failures_are_marked(lib, tmp_path):
    r = await hub.resolve(catalog.get("qwen3-vl-4b"))
    lib.cuts_remaining, lib.cut_after = 1, 1_500_000
    with pytest.raises(hub.DownloadError) as exc:
        await hub.download_file(r.repo, r.model, tmp_path / r.model.name, lambda *a: None, asyncio.Event())
    assert exc.value.transient, "a dropped connection must be worth another go"


async def test_a_repository_that_does_not_exist_is_not_retried(lib, tmp_path):
    r = await hub.resolve(catalog.get("qwen3-vl-4b"))
    gone = hub.RemoteFile("no-such-file.gguf", 10, None)
    with pytest.raises(hub.DownloadError) as exc:
        await hub.download_file(r.repo, gone, tmp_path / "x.gguf", lambda *a: None, asyncio.Event())
    assert not exc.value.transient, "there is nothing to be gained by asking again"


# ---------- the retry itself ----------
async def test_two_dropped_connections_no_longer_need_a_person(lib, tmp_path, monkeypatch):
    """The reported failure, reproduced and then not failing."""
    monkeypatch.setattr(engine_mod, "detect", lambda: hw(ram=8))
    monkeypatch.setattr(Brain, "BACKOFF", (0, 0, 0, 0, 0))     # no waiting in a test
    brain = Brain(ModelStore(tmp_path), hardware=hw(ram=8))
    lib.cuts_remaining, lib.cut_after = 2, 1_500_000           # fails twice, like the real one

    brain.start_download("qwen3-vl-4b")
    for _ in range(400):
        if brain.download.status in ("done", "failed"):
            break
        await asyncio.sleep(0.05)
    assert brain.download.status == "done", brain.download.message

    model = brain.store.list()[0]
    assert model.model_path.read_bytes() == lib.payload, "the resumed file is not the file"
    # three attempts at the model file, which is what the person had to do by hand
    name = "/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/main/Qwen3VL-4B-Instruct-Q4_K_M.gguf"
    assert lib.requests.count(name) == 3, lib.requests


async def test_it_gives_up_rather_than_retrying_for_ever(lib, tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod, "detect", lambda: hw(ram=8))
    monkeypatch.setattr(Brain, "BACKOFF", (0,))
    monkeypatch.setattr(Brain, "MAX_ATTEMPTS", 3)
    brain = Brain(ModelStore(tmp_path), hardware=hw(ram=8))
    lib.cuts_remaining, lib.cut_after = 99, 1_500_000               # never succeeds

    brain.start_download("qwen3-vl-4b")
    for _ in range(400):
        if brain.download.status in ("done", "failed"):
            break
        await asyncio.sleep(0.05)
    assert brain.download.status == "failed"
    name = "/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/main/Qwen3VL-4B-Instruct-Q4_K_M.gguf"
    assert lib.requests.count(name) == 3, "MAX_ATTEMPTS is not being honoured"


async def test_the_part_file_survives_so_the_next_try_still_resumes(lib, tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod, "detect", lambda: hw(ram=8))
    monkeypatch.setattr(Brain, "BACKOFF", (0,))
    monkeypatch.setattr(Brain, "MAX_ATTEMPTS", 2)
    brain = Brain(ModelStore(tmp_path), hardware=hw(ram=8))
    lib.cuts_remaining, lib.cut_after = 99, 1_500_000
    brain.start_download("qwen3-vl-4b")
    for _ in range(400):
        if brain.download.status in ("done", "failed"):
            break
        await asyncio.sleep(0.05)
    assert brain.download.status == "failed"
    parts = list(tmp_path.rglob("*.part"))
    assert parts and parts[0].stat().st_size > 0, "giving up threw away what had been downloaded"


async def test_cancelling_during_the_wait_stops_at_once(lib, tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod, "detect", lambda: hw(ram=8))
    monkeypatch.setattr(Brain, "BACKOFF", (30,))               # long enough that only cancel ends it
    brain = Brain(ModelStore(tmp_path), hardware=hw(ram=8))
    lib.cuts_remaining, lib.cut_after = 99, 1_500_000

    brain.start_download("qwen3-vl-4b")
    for _ in range(200):                                       # wait until it is between attempts
        if "Trying again" in brain.download.message:
            break
        await asyncio.sleep(0.05)
    assert "Trying again" in brain.download.message, brain.download.message
    assert brain.cancel_download()
    for _ in range(100):
        if brain.download.status != "downloading":
            break
        await asyncio.sleep(0.05)
    assert brain.download.status == "cancelled", brain.download.message


async def test_the_person_is_told_it_is_retrying_rather_than_shown_a_dead_screen(lib, tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod, "detect", lambda: hw(ram=8))
    monkeypatch.setattr(Brain, "BACKOFF", (5,))
    brain = Brain(ModelStore(tmp_path), hardware=hw(ram=8))
    lib.cuts_remaining, lib.cut_after = 99, 1_500_000
    brain.start_download("qwen3-vl-4b")
    for _ in range(200):
        if "Trying again" in brain.download.message:
            break
        await asyncio.sleep(0.05)
    msg = brain.download.message
    brain.cancel_download()
    assert "Trying again" in msg and "attempt 2 of" in msg
    assert "carries on from where it stopped" in msg, msg
