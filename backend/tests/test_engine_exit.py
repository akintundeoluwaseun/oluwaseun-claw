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


def test_an_installed_brain_whose_start_failed_is_not_reported_ready(make_client, monkeypatch):
    from claw.runtime.brain import Brain

    def summary(self, selected):
        return {"ready": True, "active": {"name": "Light brain"},
                "engine": {"state": "failed", "available": True, "message": "a Windows file it needs is missing"}}

    monkeypatch.setattr(Brain, "summary", summary)
    body = make_client({"model": {"mode": "builtin"}}).get("/models/status").json()
    assert body["model_available"] is False and body["reason"] == "engine_failed"
    assert "did not start" in body["message"] and "missing" in body["message"]
