"""Windows exit codes from llama-server are explained, not shown as "no output"."""

from types import SimpleNamespace

from claw.runtime.engine import LlamaServer


def reason(code):
    eng = LlamaServer(binary=None)
    eng._proc = SimpleNamespace(returncode=code)
    return eng._crash_reason()


def test_missing_runtime_and_unsupported_cpu_are_named():
    assert "Visual C++" in reason(-1073741515) and "Visual C++" in reason(3221225781)
    assert "processor" in reason(-1073741795)
    assert reason(1).startswith("The AI engine stopped")
