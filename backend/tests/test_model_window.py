"""What window the model server will actually accept.

llama.cpp clamps -c DOWN to the model's trained context. Starting the engine
with -c 8192 against a model trained at 2048 gives a 2048-token server, and
nothing announces it. Budgeting against the number that was asked for then
builds a prompt the server rejects with a 400, which reaches a person as the
task failing rather than as a long conversation being trimmed to fit.

The first real Windows build is what found this: a tiny imported model answered
`request (2158 tokens) exceeds the available context size (2048 tokens)`.
"""

import pytest

from claw.models.base import ChatMessage
from claw.models.openai_compat import OpenAICompatAdapter
from tests.fake_model_server import FakeModelServer


def adapter_for(base_url: str) -> OpenAICompatAdapter:
    a = OpenAICompatAdapter(base_url=base_url, model="tiny", timeout_s=10, temperature=0.2)
    a.api_key = "test-key"
    return a


async def test_the_server_is_asked_what_it_will_accept():
    with FakeModelServer(models=["tiny"]) as srv:
        srv.n_ctx = 2048  # trained smaller than the engine asked for
        assert await adapter_for(srv.base_url).context_window() == 2048


async def test_a_provider_without_that_route_says_nothing_rather_than_failing():
    with FakeModelServer(models=["tiny"]) as srv:
        srv.n_ctx = None  # 404, the way a hosted provider answers
        assert await adapter_for(srv.base_url).context_window() is None


async def test_a_server_that_is_not_there_is_not_an_error_either():
    # Nothing is listening on this port; a window probe must not raise, because
    # failing to learn the window is not a reason to fail the task.
    assert await adapter_for("http://127.0.0.1:9").context_window() is None


@pytest.mark.parametrize("reported", [2048, 4096, 32768])
async def test_whatever_it_reports_is_what_comes_back(reported):
    with FakeModelServer(models=["tiny"]) as srv:
        srv.n_ctx = reported
        assert await adapter_for(srv.base_url).context_window() == reported
