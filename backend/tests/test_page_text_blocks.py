"""read_page must not run one block of a page into the next.

The old implementation cloned the page root, stripped script/style/nav/footer
from the clone, and read `innerText` off it. A detached node has no layout, and
innerText needs layout, so Chromium fell through to `textContent` - which has
no block boundaries at all. Measured:

    detached clone .innerText -> 'Email: hello@x.examplePhone: 0803 111 223314 Taiwo Road'
    live element   .innerText -> 'Email: hello@x.example\\n\\nPhone: 0803 111 2233\\n\\n14 Taiwo Road'

The readability cost is obvious. The correctness cost was not: compare_pages
keeps only values that appear in the page's own text, so a price sitting at the
end of a paragraph became "$12Licence" and a true value came back as "not found
on the page" - indistinguishable, to the person reading it, from the brain
having invented the number.

These run against real Chromium, because the bug was in what the browser does,
not in what the code says.
"""

from claw.browser import extract


async def _text(ctx, html: str) -> str:
    page = await ctx.browser.page()
    await page.set_content(html)
    return (await extract.read_page(page))["text"]


async def test_adjacent_blocks_do_not_run_together(tool_ctx):
    text = await _text(tool_ctx, "<main><p>Email: hello@x.example</p><p>Phone: 0803 111 2233</p></main>")
    assert "examplePhone" not in text, "the old bug is back"
    assert "hello@x.example" in text and "Phone: 0803 111 2233" in text
    assert text.splitlines()[:2] == ["Email: hello@x.example", "Phone: 0803 111 2233"]


async def test_table_cells_and_list_items_are_separate_lines(tool_ctx):
    text = await _text(tool_ctx, "<main><table><tr><td>Charger</td><td>3500</td></tr>"
                                 "<tr><td>Cable</td><td>1500</td></tr></table>"
                                 "<ul><li>First</li><li>Second</li></ul></main>")
    lines = text.splitlines()
    assert "Charger" in lines and "3500" in lines and "Cable" in lines
    assert "First" in lines and "Second" in lines
    assert "FirstSecond" not in text and "35001500" not in text


async def test_inline_markup_does_not_break_a_sentence(tool_ctx):
    # The counterpart risk: a newline after every element would split "costs
    # $12 per month" into three lines and break the grounding check instead.
    text = await _text(tool_ctx, "<main><p>It <b>costs</b> <em>$12</em> per month.</p></main>")
    assert "It costs $12 per month." in text


async def test_a_line_break_is_a_line_break(tool_ctx):
    text = await _text(tool_ctx, "<main><p>Line one<br>Line two</p></main>")
    assert text.splitlines() == ["Line one", "Line two"]


async def test_scripts_styles_navigation_and_footers_are_still_left_out(tool_ctx):
    text = await _text(tool_ctx, "<body><nav>Home Contact</nav><main><p>The real text.</p>"
                                 "<script>var secret='scripttext';</script>"
                                 "<style>.x{color:red}</style></main><footer>Site footer</footer></body>")
    assert "The real text." in text
    for gone in ("scripttext", "color:red", "Site footer"):
        assert gone not in text, gone


async def test_hidden_elements_are_still_left_out(tool_ctx):
    text = await _text(tool_ctx, "<main><p>Shown</p><p hidden>Concealed</p>"
                                 "<p aria-hidden='true'>Decorative</p></main>")
    assert "Shown" in text and "Concealed" not in text and "Decorative" not in text


async def test_a_value_at_the_end_of_a_block_is_still_groundable(tool_ctx):
    # The defect that mattered, stated as the property it broke.
    from claw.tools.research_tools import grounded
    text = await _text(tool_ctx, "<main><p>Basic costs $12 per month</p>"
                                 "<p>Licence: free for commercial use</p></main>")
    assert grounded("$12 per month", text), text
    assert grounded("free for commercial use", text)


async def test_a_page_with_no_main_element_still_reads(tool_ctx):
    text = await _text(tool_ctx, "<body><h1>Title</h1><p>Body text.</p></body>")
    assert "Title" in text and "Body text." in text


async def test_the_fixture_site_reads_as_separate_lines(tool_ctx, site):
    await tool_ctx.browser.goto(f"{site.base_url}/biz/contact")
    text = (await extract.read_page(await tool_ctx.browser.page()))["text"]
    assert "sales@ilorinprint.example" in text
    assert "sales@ilorinprint.examplePhone" not in text
    assert "14 Taiwo Road, Ilorin, Kwara State" in text.splitlines()
