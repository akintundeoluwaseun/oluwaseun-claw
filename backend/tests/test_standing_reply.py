"""The time-limited standing reply.

"For the next two hours, anyone who messages me gets: come back in three
hours." This is the part that can be built honestly without an unofficial
WhatsApp library: S-CLAW prepares the replies and the person sends them.

Most of these tests are about the refusals, because every one of them is a
message that would otherwise go to a real person without anybody deciding.
"""

import time

import pytest

from claw.integrations.standing_reply import (COOLDOWN_SECONDS, MAX_DRAFTS, MAX_HOURS,
                                              Authorisation, NotAuthorised, StandingReply,
                                              eligible)

HOUR = 3600
MSG = "Thanks! I'm tied up — please come back in 3 hours."


@pytest.fixture
def standing(tmp_path):
    return StandingReply(tmp_path / "standing-reply.json")


# ---------- authorising ----------
def test_a_window_is_opened_and_reported(standing):
    auth = standing.authorise(MSG, hours=2, account_hint="WhatsApp — +234…1234")
    assert auth.live() and 115 <= auth.minutes_left() <= 120
    status = standing.status()
    assert status["authorised"] and status["message"] == MSG
    assert status["account_hint"], "the person must see which account this is for"


@pytest.mark.parametrize("hours", [0, -1, MAX_HOURS + 1, 48])
def test_an_unreasonable_window_is_refused(standing, hours):
    with pytest.raises(ValueError):
        standing.authorise(MSG, hours=hours)


@pytest.mark.parametrize("text", ["", "   ", "x" * 501])
def test_an_unusable_message_is_refused(standing, text):
    with pytest.raises(ValueError):
        standing.authorise(text, hours=1)


def test_nothing_is_drafted_without_authorisation(standing):
    with pytest.raises(NotAuthorised):
        standing.drafts_for([("Tunde", 1)])


# ---------- expiry ----------
def test_the_window_closes_on_time(standing):
    now = time.time()
    standing.authorise(MSG, hours=2, now=now)
    assert standing.drafts_for([("Tunde", 1)], now=now + HOUR)
    with pytest.raises(NotAuthorised):
        standing.drafts_for([("Amaka", 1)], now=now + 2 * HOUR + 1)


def test_expiry_survives_a_restart(tmp_path):
    """The expiry is on disk, so closing S-CLAW cannot extend the window."""
    now = time.time()
    StandingReply(tmp_path / "s.json").authorise(MSG, hours=1, now=now)
    after_restart = StandingReply(tmp_path / "s.json")          # a fresh object, same file
    assert after_restart.status(now=now + 30 * 60)["authorised"]
    assert not after_restart.status(now=now + 2 * HOUR)["authorised"]
    with pytest.raises(NotAuthorised):
        after_restart.drafts_for([("Tunde", 1)], now=now + 2 * HOUR)


def test_stopping_is_immediate(standing):
    standing.authorise(MSG, hours=2)
    assert standing.stop()
    assert not standing.status()["authorised"]
    with pytest.raises(NotAuthorised):
        standing.drafts_for([("Tunde", 1)])


# ---------- who is eligible ----------
@pytest.mark.parametrize("name,reason", [
    ("Site team (12)", "group"),
    ("Family group", "group"),
    ("Tunde, Amaka, +234 803", "group"),
    ("Status", "status"),
    ("My status", "status"),
    ("You", "own chat"),
    ("", "no name"),
])
def test_chats_that_must_never_get_an_automatic_reply(standing, name, reason):
    auth = Authorisation(message=MSG, expires_at=time.time() + HOUR)
    ok, why = eligible(name, auth)
    assert not ok, f"{reason}: {name!r} was treated as eligible"
    assert why


def test_an_ordinary_person_is_eligible(standing):
    auth = Authorisation(message=MSG, expires_at=time.time() + HOUR)
    assert eligible("Tunde", auth)[0]


def test_a_named_list_excludes_everyone_else(standing):
    standing.authorise(MSG, hours=1, only_chats=["Tunde"])
    drafts = standing.drafts_for([("Tunde", 1), ("Amaka", 2)])
    assert [d.chat for d in drafts] == ["Tunde"]


# ---------- not twice ----------
def test_one_reply_per_chat_in_a_window(standing):
    now = time.time()
    standing.authorise(MSG, hours=3, now=now)
    first = standing.drafts_for([("Tunde", 1)], now=now)
    again = standing.drafts_for([("Tunde", 4)], now=now + 10)
    later = standing.drafts_for([("Tunde", 9)], now=now + COOLDOWN_SECONDS + 60)
    assert len(first) == 1 and again == [] and later == [], \
        "a flapping unread count must not produce a pile of drafts"


def test_a_bad_read_cannot_become_fifty_drafts(standing):
    standing.authorise(MSG, hours=2)
    many = [(f"Person {i}", 1) for i in range(MAX_DRAFTS + 20)]
    assert len(standing.drafts_for(many)) <= MAX_DRAFTS


# ---------- what a draft is ----------
def test_a_draft_carries_the_message_and_why_it_was_prepared(standing):
    standing.authorise(MSG, hours=1)
    draft = standing.drafts_for([("Tunde", 3)])[0]
    assert draft.chat == "Tunde" and draft.message == MSG
    assert "3 unread" in draft.because


def test_no_message_text_is_ever_stored(standing, tmp_path):
    """Claw reads chat names and counts, never conversations — and keeps it that way."""
    standing.authorise(MSG, hours=1)
    standing.drafts_for([("Tunde", 2)])
    saved = (tmp_path / "standing-reply.json").read_text(encoding="utf-8")
    assert "Tunde" in saved, "the chat name is kept so it is not replied to twice"
    assert "unread" not in saved.lower(), "nothing about the conversation itself belongs on disk"


def test_a_corrupt_authorisation_file_is_treated_as_none(standing, tmp_path):
    (tmp_path / "standing-reply.json").write_text("{not json", encoding="utf-8")
    assert not standing.status()["authorised"]
    with pytest.raises(NotAuthorised):
        standing.drafts_for([("Tunde", 1)])
