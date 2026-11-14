"""How Claw starts its engine ON WINDOWS, checked from any platform.

Windows is the platform S-CLAW ships on and the one this development
workspace is not. These tests therefore do what can honestly be done from
elsewhere: they drive `LlamaServer._start` with `sys.platform` reporting
"win32", intercept the `subprocess.Popen` call, and assert on the command
line and the process options Claw would really have used. That verifies
Claw's own decisions. It does NOT verify that llama-server.exe then behaves
the way the Linux build does, and nothing here should be read as saying so.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from claw.runtime import engine as engine_mod
from claw.runtime.engine import LlamaServer


class Launched(Exception):
    """Raised instead of actually starting a process, carrying what was asked for."""

    def __init__(self, args, kwargs):
        super().__init__("launched")
        self.args = args
        self.kwargs = kwargs


def launch(monkeypatch, tmp_path, platform: str) -> Launched:
    """Take Claw right up to the moment it starts the engine, and stop there."""
    binary = tmp_path / ("llama-server.exe" if platform == "win32" else "llama-server")
    binary.write_bytes(b"not really an engine")
    model = tmp_path / "brain.gguf"
    model.write_bytes(b"0" * 1024)

    monkeypatch.setattr(engine_mod.sys, "platform", platform)
    # Plenty of memory and a known core count, so the test is about the command
    # line and not about the machine it happens to run on.
    monkeypatch.setattr(engine_mod, "detect",
                        lambda: SimpleNamespace(available_ram_gb=64.0, cpu_cores=8))

    def popen(args, **kwargs):
        raise Launched(args, kwargs)

    monkeypatch.setattr(subprocess, "Popen", popen)
    eng = LlamaServer(binary=binary)
    with pytest.raises(Launched) as caught:
        asyncio.run(eng._start("brain", model, None))
    return caught.value


# --------------------------------------------------------------- the one that matters

@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_the_engine_is_always_started_with_jinja(monkeypatch, tmp_path, platform):
    """`--jinja` is load-bearing and the dependency is invisible.

    Claw asks a thinking model not to think by sending
    `chat_template_kwargs: {"enable_thinking": false}`, and llama-server can
    only honour that by passing those arguments to the model's own Jinja chat
    template - which it only does under `--jinja`.

    Measured on a real llama-server with Qwen3-2B under exactly Claw's
    production flags: with thinking on, "What is the capital of France?" ran
    72.1s, finished on "length" and returned ZERO characters of content, all
    3866 of them in `reasoning_content`. With it off, 1.4s and a correct
    answer. So dropping `--jinja` would not look like a flag change; it would
    look like Claw's conversation lane silently going back to answering
    nothing at all.
    """
    args = launch(monkeypatch, tmp_path, platform).args
    assert "--jinja" in args, (
        "--jinja was removed from the engine's command line: the thinking "
        "switch depends on it, and without it a thinking model answers nothing")


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_the_engine_is_never_exposed_off_this_computer(monkeypatch, tmp_path, platform):
    args = launch(monkeypatch, tmp_path, platform).args
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert "--api-key" in args and args[args.index("--api-key") + 1]
    assert "--no-webui" in args


# ------------------------------------------------------------ windows specifics

def test_windows_gets_no_posix_process_tricks(monkeypatch, tmp_path):
    """`preexec_fn` is Linux-only and passing it on Windows raises."""
    got = launch(monkeypatch, tmp_path, "win32")
    assert got.kwargs["preexec_fn"] is None


def test_linux_still_gets_the_parent_death_signal(monkeypatch, tmp_path):
    got = launch(monkeypatch, tmp_path, "linux")
    assert got.kwargs["preexec_fn"] is engine_mod._die_with_parent


def test_windows_does_not_get_a_posix_library_path(monkeypatch, tmp_path):
    """On Windows the engine's DLLs are found through its own directory, and
    LD_LIBRARY_PATH means nothing - setting it would just be noise in the env."""
    got = launch(monkeypatch, tmp_path, "win32")
    assert "LD_LIBRARY_PATH" not in got.kwargs["env"]


def test_other_platforms_do_get_one_pointing_at_the_engine(monkeypatch, tmp_path):
    got = launch(monkeypatch, tmp_path, "linux")
    assert str(tmp_path) in got.kwargs["env"]["LD_LIBRARY_PATH"]


def test_the_engine_runs_from_its_own_directory(monkeypatch, tmp_path):
    """Windows resolves a .exe's DLLs relative to its working directory."""
    for platform in ("win32", "linux"):
        got = launch(monkeypatch, tmp_path, platform)
        assert got.kwargs["cwd"] == str(tmp_path)


def test_no_console_window_is_ever_flashed_at_the_person(monkeypatch, tmp_path):
    got = launch(monkeypatch, tmp_path, "win32")
    assert got.kwargs["creationflags"] == engine_mod._NO_WINDOW


def test_the_exe_name_is_the_windows_one_on_windows():
    """Read rather than driven, because the name is decided at import time."""
    import importlib

    assert engine_mod.EXE == ("llama-server.exe" if sys.platform == "win32" else "llama-server")
    src = Path(engine_mod.__file__).read_text()
    assert 'EXE = "llama-server.exe" if sys.platform == "win32" else "llama-server"' in src
