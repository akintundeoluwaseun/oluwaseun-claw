import json

import pytest
from fastapi.testclient import TestClient

from claw.api.app import create_app
from tests.fake_model_server import FakeModelServer

TOKEN = "t" * 40
VALID_PLAN = {
    "goal": "Find the newest PDF in Downloads and summarize it",
    "steps": [
        {"description": "List PDF files in Downloads", "capability": "files", "risk": "read_only", "expected_result": "A list of PDFs"},
        {"description": "Read the newest PDF", "capability": "files", "risk": "read_only", "expected_result": "Its text"},
        {"description": "Write a summary", "capability": "reasoning", "risk": "read_only", "expected_result": "A short summary"},
    ],
    "questions": [],
}


@pytest.fixture
def fake_server():
    with FakeModelServer() as srv:
        yield srv


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def make_client(data_dir):
    def _make(settings: dict | None = None):
        if settings is not None:
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "settings.json").write_text(json.dumps(settings))
        client = TestClient(create_app(data_dir, TOKEN), base_url="http://127.0.0.1")
        client.headers["X-Claw-Token"] = TOKEN
        return client

    return _make
