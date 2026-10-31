"""DuckDuckGo HTML results parsing (approach ported from OpenClaw's ddg-client.ts)."""

import pytest

from claw.browser import ddg_html

PAGE = """
<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.openshot.org%2F&amp;rut=x">
<b>OpenShot</b> Video Editor | Free &amp; Open</a>
<a class="result__snippet" href="#">A free, <b>open</b>-source video editor for Linux, Mac and Windows.</a></div>
<div class="result"><a class="result__a" href="https://kdenlive.org/">Kdenlive</a></div>
"""


def test_results_titles_real_links_and_snippets():
    r = ddg_html.parse(PAGE)
    assert r[0] == {"title": "OpenShot Video Editor | Free & Open", "url": "https://www.openshot.org/",
                    "snippet": "A free, open-source video editor for Linux, Mac and Windows."}
    assert r[1]["url"] == "https://kdenlive.org/" and r[1]["snippet"] == ""
    assert len(ddg_html.parse(PAGE, count=1)) == 1


def test_a_challenge_page_is_reported_not_read_as_empty():
    with pytest.raises(ddg_html.SearchChallenge):
        ddg_html.parse('<form id="challenge-form">are you a human?</form>')
    assert ddg_html.parse("<html>nothing</html>") == []
