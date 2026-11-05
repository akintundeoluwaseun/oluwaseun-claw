"""A chat is answered at once; a job is still a job.

The first Windows user put it plainly: saying "hi" took "a million years". It
did. Every message, including hello, woke the brain, handed it eighty-six tool
descriptions and asked it to plan - so the brain's first job was to work out
that a greeting needs no tools.

This module decides that without asking. The risk is one-sided and these tests
are weighted accordingly: answering a real job with a cheerful line and doing
nothing is the false completion this project measures and hates, while sending
a greeting the long way round only costs the slowness we already had. So the
first test is the one that matters - everything below is a job, and must stay
one.
"""

from __future__ import annotations

import pytest

from claw.agent.conversation import is_conversation, quick_reply, smells_like_work

# Real requests, including short and polite ones. None of these may be taken as chat.
JOBS = [
    "Make a promotional flyer for my business and save it in Documents",
    "make a flyer",
    "open notepad",
    "Open Notepad",
    "find every PDF in Documents",
    "hi, can you open my calendar?",
    "hello - please read invoice 2041",
    "thanks, now save it as a PDF",
    "ok save that to Downloads",
    "yes, send it",
    "C:\\Users\\Me\\Documents\\report.docx",
    "summarise this",
    "what is in my downloads folder",
    "how do I save this as a PDF",
    "remind me about Friday",
    "put Friday's call in my calendar",
    "read it",
    "check the total",
    "sort it",
    "delete that",
]

# Plain talk, no work in it.
CHAT = [
    "hi", "Hi!", "hello", "Hello there", "hey", "yo", "good morning",
    "thanks", "thank you", "thx", "cheers",
    "ok", "okay", "cool", "nice", "great", "yes", "no",
    "bye", "goodbye", "see you", "good night",
    "how are you", "how's it going", "you there?",
    "what can you do", "help",
]


@pytest.mark.parametrize("text", JOBS)
def test_a_job_is_never_answered_as_chat(text):
    assert quick_reply(text) is None, f"{text!r} would have been answered with a canned line"
    assert not is_conversation(text), f"{text!r} would have skipped the planner"


@pytest.mark.parametrize("text", CHAT)
def test_plain_talk_is_answered_without_the_brain(text):
    reply = quick_reply(text)
    assert reply, f"{text!r} still goes the long way round"
    assert len(reply) < 400


def test_a_greeting_with_a_job_attached_is_a_job():
    """The dangerous case: it starts like chat and ends like work."""
    assert quick_reply("hey, make me a flyer") is None
    assert smells_like_work("hey, make me a flyer")


def test_long_messages_are_never_chat():
    long_but_harmless = " ".join(["really"] * 30)
    assert not is_conversation(long_but_harmless)


def test_something_unclassifiable_falls_through_to_the_planner():
    """No canned answer and no work smell: the one-call path, not a guess."""
    text = "i wonder about that"
    assert quick_reply(text) is None
    assert is_conversation(text)


def test_being_asked_to_ask(real_message="ask for details to input"):
    """The message from the screenshot that started this.

    It names no file, no app and no action on the computer: it is the person
    telling Claw to ask them something. Through the planner it became a false
    completion - Claw replied that it had made the flyer and saved it, while
    the step list beside it read "No steps were carried out". One short model
    call can answer it properly, by asking.
    """
    assert quick_reply(real_message) is None, "no canned line fits this; it needs a real answer"
    assert is_conversation(real_message), "it must not go to the planner"


def test_empty_is_not_chat():
    assert quick_reply("") is None
    assert not is_conversation("")
    assert not is_conversation("   ")


# ---------------------------------------------------------------------------
# End to end, through the API, with a model server that records every request.
#
# The unit tests above say the classifier is right. These say the fast path is
# actually wired in front of the planner: a greeting must finish without the
# model being contacted once. If someone later moves the check below
# make_plan, the classifier still passes and the slowness quietly returns, so
# the assertion that matters is the empty request list.

import json

from tests.conftest import VALID_PLAN
from tests.test_api import settings_for
from tests.test_chats import finish, wait_done


def test_a_greeting_finishes_without_asking_the_brain(make_client, fake_server):
    c = make_client()
    c.put("/settings", json=settings_for(fake_server))
    fake_server.replies.clear()
    fake_server.requests.clear()

    tid = c.post("/tasks/run", json={"task": "hi"}).json()["id"]
    assert wait_done(c, tid) == "completed"

    assert fake_server.requests == [], (
        f"a greeting still cost {len(fake_server.requests)} model call(s); "
        "the fast path is not in front of the planner"
    )
    body = c.get(f"/tasks/{tid}/events").json()
    answer = [e for e in body["events"] if e["kind"] == "finished"][-1]["data"]["final_answer"]
    assert "What would you like done" in answer
    assert any(e["kind"] == "chat_reply" for e in body["events"])


def test_a_real_job_still_goes_through_the_planner(make_client, fake_server):
    """The other side of the guard: work must not be short-circuited."""
    c = make_client()
    c.put("/settings", json=settings_for(fake_server))
    # Clear rather than append: a reply left in the queue by an earlier test
    # would be served to the planner instead of the plan, and this test would
    # fail for a reason that has nothing to do with what it is checking.
    fake_server.replies.clear()
    fake_server.replies += [json.dumps(VALID_PLAN), finish("Done.")]
    fake_server.requests.clear()

    tid = c.post("/tasks/run", json={"task": "Find the latest PDF in Downloads and summarise it"}).json()["id"]
    wait_done(c, tid)

    assert fake_server.requests, "a real job skipped the brain entirely"
    kinds = [e["kind"] for e in c.get(f"/tasks/{tid}/events").json()["events"]]
    assert "planned" in kinds, "the job did not reach the planner"
    assert "chat_reply" not in kinds


# ---------------------------------------------------------------------------
# Inside a chat, the short words change meaning.
#
# Found by an existing test breaking: "Now tell me how long it was" is short
# and names no file, so the first version of this module answered it from a
# chat prompt - with no access to the document it was asking about. Short
# messages mid-thread usually refer to the work that just happened, and a
# model asked to be conversational about work it cannot see will invent.

@pytest.mark.parametrize("text", [
    "Now tell me how long it was",
    "ok",            # after Claw asked something, this means do it
    "yes",
    "no",
    "sure",
])
def test_short_replies_inside_a_chat_are_not_small_talk(text):
    assert quick_reply(text, standalone=False) is None, f"{text!r} was answered as chat mid-thread"
    assert not is_conversation(text, standalone=False)


@pytest.mark.parametrize("text", ["thanks", "hi", "bye"])
def test_the_purely_social_ones_still_work_inside_a_chat(text):
    """Thanking Claw halfway through is not an instruction, whatever else is going on."""
    assert quick_reply(text, standalone=False)


def test_a_follow_up_about_earlier_work_reaches_the_planner():
    for text in ["tell me the total", "how long was it", "what was the answer", "give me the list"]:
        assert not is_conversation(text), f"{text!r} would have been answered without the work"
        assert quick_reply(text) is None


# ---------- "Hi, what can you do?" ----------
# Reported from a real install on a light brain: the tester's first message was
# "Hi, what can you do?" and the app could not complete it. Reproduced exactly.
# "What can you do?" had a canned answer; the same question with a greeting in
# front of it had none, because the greeting pattern is anchored to the whole
# message and the comma defeated it, while the capability pattern never saw a
# string starting with "what". So the first thing anyone types to a new
# assistant fell through to a model call - the one path the fast path exists to
# avoid, and on a 2B the one that looks like the app has frozen.

def test_the_exact_message_that_failed_on_a_real_install():
    answer = quick_reply("Hi, what can you do?")
    assert answer is not None, "the message that started this is still unanswered"
    assert "files and folders" in answer


def test_a_greeting_in_front_of_plain_talk_does_not_hide_it():
    for text in ("Hi, what can you do?", "Hello! What can you do?", "hey - what can you do",
                 "Good morning, what can you do?", "hi there, what can you do",
                 "hiya: what can you do?", "hi claw, what can you do?"):
        assert quick_reply(text) is not None, text


def test_a_greeting_in_front_of_other_small_talk_too():
    assert "Running" in quick_reply("good morning, how are you?")
    assert quick_reply("hello, thanks") == "Any time."
    assert quick_reply("hi, are you there?") is not None


def test_a_greeting_in_front_of_WORK_is_still_work():
    # The whole guard. Stripping a greeting must never turn a job into chat.
    for text in ("hi, open notepad", "Hello, can you make me a flyer",
                 "good morning, find my invoice.pdf", "hey, search the web for a laptop",
                 "hi claw, put the meeting in my calendar"):
        assert quick_reply(text) is None, text
        assert smells_like_work(text), text


def test_the_question_in_the_shapes_people_type_it():
    for text in ("what can you do", "What can you do?", "what are you able to do",
                 "what can claw do", "what do you do", "what does claw do",
                 "what else can you do", "what can you help me with",
                 "who are you", "what are you for", "how does this work", "help"):
        assert quick_reply(text) is not None, text


def test_things_that_only_look_like_the_question():
    # "what can you do with my files" is a job: it names files.
    assert quick_reply("what can you do with my downloads folder") is None
    assert quick_reply("what can you do to make this spreadsheet smaller") is None


def test_a_greeting_on_its_own_is_still_a_greeting():
    assert quick_reply("hi") == "Hi. What would you like done?"
    assert quick_reply("Good morning") == "Hi. What would you like done?"


def test_none_of_this_costs_a_model_call():
    # The point of the whole module, stated as an assertion: the answer comes
    # back from a function, so there is nothing to wait for.
    import time
    start = time.perf_counter()
    for _ in range(2000):
        quick_reply("Hi, what can you do?")
    assert time.perf_counter() - start < 1.0


# ---------- thanking Claw ----------
# Reported: "I just told it thank you and it's taking a year to reply."
# Bare "thank you" already had a canned answer. Nobody types the bare word.

def test_thanks_in_the_shapes_people_type_it():
    for text in ("thank you", "thanks", "thank you so much", "thanks a lot",
                 "thanks very much", "thank u", "tysm", "thanks o", "thanks claw",
                 "thank you sir", "thanks for the help", "thank you for everything",
                 "ok thanks", "ok thank you", "alright, thanks", "well done", "great job",
                 "thanks 🙏"):
        assert quick_reply(text) == "Any time.", text


def test_being_thanked_for_a_job_does_not_do_the_job_again():
    # The one that could actually hurt. "Thanks for opening Notepad" names a
    # job, smells exactly like a job, and went to the planner - which would
    # open Notepad a second time. Being thanked is not an instruction.
    for text in ("thank you for opening notepad", "thanks for finding the pdf",
                 "thanks for the flyer", "thanks for sending the message",
                 "thanks for deleting them"):
        assert quick_reply(text) == "Any time.", text


def test_gratitude_with_a_new_request_in_it_is_still_a_request():
    # The guard on the rule above. A clause break or a word that starts a new
    # ask puts the message back in front of the planner, where it belongs.
    for text in ("thanks, now open notepad", "thanks for opening notepad, now close it",
                 "thanks for opening notepad then close it",
                 "thanks for that, can you also print it",
                 "thanks for opening it please do the next one"):
        assert quick_reply(text) is None, text


def test_an_acknowledgement_in_front_of_talk_is_stripped_like_a_greeting():
    assert quick_reply("so what can you do") is not None
    assert quick_reply("ok what now") is not None
    assert quick_reply("ok open notepad") is None          # still a job
    assert quick_reply("nice, make me a flyer") is None    # still a job


def test_calling_it_off_is_not_a_job():
    # "forget it" read as work only because "forget" is a verb Claw has a tool
    # for, so it reached the planner, which then had to plan how to forget
    # something.
    for text in ("forget it", "never mind", "nevermind", "don't bother", "skip it",
                 "leave it", "cancel that"):
        assert quick_reply(text) == "Right - nothing done.", text


def test_forgetting_a_real_thing_is_still_a_job():
    for text in ("forget the invoice I asked you to remember", "forget my password",
                 "never mind, open notepad instead"):
        assert quick_reply(text) is None, text
