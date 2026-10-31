"""Nearly-right model JSON (repair() ported from OpenClaw's repairJson)."""

from claw.agent import jsonfix


def test_windows_paths_with_single_backslashes():
    raw = '{"action": "tool", "tool": "read_file", "args": {"path": "C:\\Users\\Ada\\Documents\\new notes.txt"}}'
    assert jsonfix.loads(raw)["args"]["path"] == "C:\\Users\\Ada\\Documents\\new notes.txt"


def test_chatter_fences_and_raw_newlines():
    raw = 'Sure! Here is my answer:\n```json\n{"thought": "line one\nline two", "action": "finish", "final_answer": "ok"}\n```'
    d = jsonfix.loads(raw)
    assert d["thought"] == "line one\nline two" and d["final_answer"] == "ok"
    assert jsonfix.loads('I think {"a": {"b": "}"}} trailing')["a"]["b"] == "}"


def test_valid_json_is_untouched():
    assert jsonfix.loads('{"text": "tab\\there"}') == {"text": "tab\there"}
