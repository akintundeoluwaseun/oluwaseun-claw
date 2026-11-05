"""Challenge 9.13: a business's contact details, from the business's own site.

The whole design question here is who does the extraction. Asking the brain
"what is the phone number on this page" is the obvious implementation and the
wrong one: a 2B model asked for a phone number produces a plausible phone
number whether or not the page has one, and a plausible phone number is worse
than none, because the person rings a stranger and believes they have the right
office. So the values come from matching the page's own text, and every one is
returned with the address of the page it was matched on.

These tests therefore spend most of their effort on what must NOT come back: a
year, a price, a quantity, and anything on somebody else's website.

Real Chromium against the local fixture site; no internet.
"""

from claw.tools.research_tools import _digits_plausible, _harvest
from tests.test_phase_a import call


# ---------- the matching, on its own ----------
def test_a_year_is_not_a_telephone_number():
    assert not _digits_plausible("2026") and not _digits_plausible("1999")
    assert _harvest("Printing since 2004. Banners from 3500 naira.")["phones"] == []


def test_a_price_or_a_quantity_is_not_a_telephone_number():
    assert _harvest("A3 poster 1200. Orders over 50000 get a discount.")["phones"] == []
    assert not _digits_plausible("3500") and not _digits_plausible("50000")


def test_the_shapes_a_telephone_number_really_comes_in():
    for text in ("0803 111 2233", "+234 805 444 5566", "(01) 271 0000", "555-0100", "08031112233"):
        assert _harvest(f"Call {text} today")["phones"], text


def test_an_address_needs_a_number_and_a_thoroughfare():
    assert _harvest("14 Taiwo Road, Ilorin, Kwara State")["addresses"]
    assert _harvest("Ilorin, Kwara State")["addresses"] == []        # no number, no street
    assert _harvest("Order 25000 copies")["addresses"] == []


def test_emails_and_social_links_are_taken_as_written():
    got = _harvest("hello@x.example or sales@x.example — https://www.instagram.com/shop")
    assert got["emails"] == ["hello@x.example", "sales@x.example"]
    assert got["social"] == ["https://www.instagram.com/shop"]


def test_the_same_detail_twice_is_listed_once():
    got = _harvest("hello@x.example ... write to Hello@X.example again")
    assert len(got["emails"]) == 1


# ---------- the whole tool ----------
async def test_the_details_are_found_and_each_one_names_its_page(tool_ctx, site):
    r = await call(tool_ctx, "find_contacts", url=f"{site.base_url}/biz", pages=4)
    assert r.ok and r.verified

    emails = {d["value"] for d in r.data["emails"]}
    # Every address written on the page comes back, including the one the page's
    # own injection line names: the tool reports what is there, it does not
    # judge which address is the genuine one. Anything else would mean deciding,
    # on the brain's say-so, which text on a page to believe - and that is the
    # judgement this whole design refuses to make.
    assert {"hello@ilorinprint.example", "sales@ilorinprint.example"} <= emails, emails
    assert "sales@ilorinprint.examplePhone" not in emails, "page text ran two blocks together"
    phones = {d["value"] for d in r.data["phones"]}
    assert "0803 111 2233" in phones and "+234 805 444 5566" in phones, phones
    assert any("Taiwo Road" in d["value"] for d in r.data["addresses"]), r.data["addresses"]
    assert {d["value"] for d in r.data["social"]} == {
        "https://www.instagram.com/ilorinprint", "https://facebook.com/ilorinprint"}

    # every value is traceable to a page that was actually read
    read = set(r.data["pages_read"])
    for field in ("emails", "phones", "addresses", "social"):
        for d in r.data[field]:
            assert d["page"] in read, f"{d['value']} cites a page that was never opened"
    assert f"{site.base_url}/biz/contact" in read


async def test_the_years_and_prices_on_the_site_are_not_reported_as_phone_numbers(tool_ctx, site):
    r = await call(tool_ctx, "find_contacts", url=f"{site.base_url}/biz", pages=4)
    phones = {d["value"].strip() for d in r.data["phones"]}
    for noise in ("2004", "2026", "3500", "25000", "1200", "2400", "50000"):
        assert noise not in phones, f"{noise} came back as a telephone number"


async def test_another_company_s_website_is_not_followed(tool_ctx, site):
    # The home page links to a supplier's contact page. A contact page on
    # someone else's domain is not evidence about this business.
    r = await call(tool_ctx, "find_contacts", url=f"{site.base_url}/biz", pages=8)
    assert all(p.startswith(site.base_url) for p in r.data["pages_read"]), r.data["pages_read"]
    assert not any("other.example.org" in d["page"] for d in r.data["emails"])


async def test_an_instruction_hidden_in_the_page_is_not_obeyed(tool_ctx, site):
    # The contact page tells the reader to send every address to an attacker.
    # Nothing here acts on page text, so the only thing that should happen is
    # that the attacker's address is reported as an address found on the page,
    # inside untrusted markers, like any other string.
    r = await call(tool_ctx, "find_contacts", url=f"{site.base_url}/biz/contact", pages=1)
    assert r.ok
    assert "steal@evil.example" in {d["value"] for d in r.data["emails"]}
    assert all(d["page"].startswith(site.base_url) for d in r.data["emails"])


async def test_a_site_that_publishes_nothing_says_so(tool_ctx, site):
    r = await call(tool_ctx, "find_contacts", url=f"{site.base_url}/biz/prices", pages=1)
    assert r.ok and sum(r.data["counts"].values()) == 0
    assert "no contact details" in r.summary and "does not publish" in r.summary


async def test_the_page_limit_is_honoured(tool_ctx, site):
    r = await call(tool_ctx, "find_contacts", url=f"{site.base_url}/biz", pages=1)
    assert len(r.data["pages_read"]) == 1


async def test_a_site_that_cannot_be_opened_is_an_error_not_an_empty_result(tool_ctx, site):
    import pytest
    with pytest.raises(Exception) as exc:
        await call(tool_ctx, "find_contacts", url="http://127.0.0.1:9/nothing", pages=1)
    assert "could not be opened" in str(exc.value) or "9" in str(exc.value)


async def test_a_number_in_the_footer_is_found(tool_ctx):
    # Where businesses actually put it. read_page strips footers by default,
    # which would have this tool report that a site publishes no telephone
    # number while the number sits at the bottom of every page.
    page = await tool_ctx.browser.page()
    await page.set_content("<body><main><h1>Welcome</h1></main>"
                           "<footer><p>Call 0803 111 2233</p><p>12 Allen Avenue, Ikeja</p></footer></body>")
    from claw.browser import extract
    text = (await extract.read_page(page, keep_chrome=True))["text"]
    got = _harvest(text)
    assert got["phones"] == ["0803 111 2233"], got
    assert any("Allen Avenue" in a for a in got["addresses"]), got


def test_a_social_account_is_recognised_from_the_link_not_the_word():
    from claw.tools.research_tools import _social_links
    # "Find us on Instagram" puts the word in the text and the address in the href.
    assert _social_links(["https://www.instagram.com/ilorinprint"]) == ["https://www.instagram.com/ilorinprint"]
    assert _social_links(["https://wa.me/2348031112233"]) == ["https://wa.me/2348031112233"]
    # a plain link to the site's own pages is not a social account
    assert _social_links(["https://ilorinprint.example/contact", "https://facebook.com/"]) == []
