"""Where an OpenAI-shaped address points.

The chat route used to be hardcoded as "/v1/chat/completions" and appended to
whatever address was configured. That silently required the address to be given
WITHOUT its version, while every provider documents it WITH one, so pasting the
documented address produced a doubled "/v1/v1/" and a 404 that reads like a
rejected key. Google's OpenAI-compatible routes sit under "/v1beta/openai" and
could not be reached at all.
"""

import pytest

from claw.models.openai_compat import api_root, route


@pytest.mark.parametrize(
    "base_url, expected",
    [
        # llama.cpp's llama-server: no version in the address, so one is added.
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080/v1/chat/completions"),
        # x.ai documents https://api.x.ai/v1 - pasting it must not double up.
        ("https://api.x.ai/v1", "https://api.x.ai/v1/chat/completions"),
        ("https://api.x.ai/v1/", "https://api.x.ai/v1/chat/completions"),
        # ...and leaving the version off must still work.
        ("https://api.x.ai", "https://api.x.ai/v1/chat/completions"),
        # Google's OpenAI-compatible surface is not under /v1 at all.
        ("https://generativelanguage.googleapis.com/v1beta/openai",
         "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
        ("https://generativelanguage.googleapis.com/v1beta/openai/",
         "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
        ("https://api.openai.com/v1", "https://api.openai.com/v1/chat/completions"),
    ],
)
def test_chat_route(base_url: str, expected: str) -> None:
    assert api_root(base_url) + route(base_url, "chat/completions") == expected


def test_the_model_list_follows_the_same_rule() -> None:
    assert api_root("https://api.x.ai/v1") + route("https://api.x.ai/v1", "models") \
        == "https://api.x.ai/v1/models"
    assert api_root("http://127.0.0.1:8080") + route("http://127.0.0.1:8080", "models") \
        == "http://127.0.0.1:8080/v1/models"


def test_no_address_ever_doubles_its_version() -> None:
    for base in ("https://api.x.ai/v1", "https://api.openai.com/v1",
                 "https://generativelanguage.googleapis.com/v1beta/openai"):
        url = api_root(base) + route(base, "chat/completions")
        assert "/v1/v1/" not in url and "//chat" not in url, url
