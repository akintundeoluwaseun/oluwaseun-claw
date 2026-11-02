"""Milestone 6: web pages into a comparison sheet, every value checked against its own page (real Chromium, local site)."""

import json
from pathlib import Path

import openpyxl

from claw.tools.research_tools import NOT_FOUND, grounded
from tests.test_phase_a import call


class FakeBrain:
    """TEST DOUBLE: answers like a small brain - one true value, one invented, one ignored instruction."""

    def __init__(self):
        self.prompts = []

    async def chat(self, messages, json_schema=None):
        self.prompts.append(messages[-1].content)
        return json.dumps({"licence": "free for commercial use", "price": "$49 per month"})


def test_grounding_rules():
    page = "Plans: Basic costs $12 per month. Licence: free for commercial use."
    assert grounded("$12 per month", page) and grounded("12", page) and grounded("Free for commercial use", page)
    assert not grounded("$49", page) and not grounded("not found on the page", page) and not grounded("", page)


async def test_comparison_keeps_only_values_the_page_states(tool_ctx, site):
    tool_ctx.llm = FakeBrain()
    urls = [f"{site.base_url}/articles/motion-templates", f"{site.base_url}/articles/ai-video"]
    r = await call(tool_ctx, "compare_pages", fields=["licence", "price"], urls=urls, file_name="templates")
    assert r.verified and r.data["rows"] == 2 and r.data["dropped"] >= 2      # "$49 per month" is on neither page
    rows = list(openpyxl.load_workbook(Path(tool_ctx.settings.permissions.authorized_folders[0]) / "templates.xlsx")["Comparison"].values)
    assert rows[0] == ("Page", "Licence", "Price", "Source")
    first = rows[1]
    assert first[1] == "free for commercial use" and first[2] == NOT_FOUND and first[3].endswith("/articles/motion-templates")
    assert rows[2][1] == NOT_FOUND                                            # the injection page states no licence
    assert all("<untrusted>" in p for p in tool_ctx.llm.prompts)


async def test_broken_links_and_page_changes(tool_ctx, site):
    r = await call(tool_ctx, "check_links", urls=[f"{site.base_url}/search?q=motion"])
    assert r.data["checked"] >= 1 and isinstance(r.data["broken"], list)
    url = f"{site.base_url}/articles/cooking"
    r = await call(tool_ctx, "page_changes", url=url)
    assert r.data["changed"] is None and "Started watching" in r.summary
    r = await call(tool_ctx, "page_changes", url=url)
    assert r.data["changed"] is False
