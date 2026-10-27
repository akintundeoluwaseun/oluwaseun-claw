"""What Claw remembers has to reach the model.

Found by audit: `remember`, `recall` and `forget_this` all worked, the Settings
panel listed everything, and none of it ever influenced a task — because
nothing put it in front of the model, and a small model does not think to call
`recall` on its own. Storage without retrieval is a dead feature.

These tests cover the retrieval half: what is offered, in what order, how much,
and what happens when there is nothing or the store is broken.
"""

import pytest

from claw.agent.executor import MEMORY_CHARS, remembered
from claw.storage.db import Database


@pytest.fixture
def ctx_with(tool_ctx, tmp_path):
    def build(rows):
        db = Database(tmp_path / "claw.db")
        for kind, subject, fact in rows:
            db.remember(kind, subject, fact, "you told S-CLAW")
        tool_ctx.memory_store = db
        return tool_ctx
    return build


def test_what_the_person_said_is_put_in_front_of_the_model(ctx_with):
    ctx = ctx_with([("preference", "me", "prefers meetings after 10am")])
    block = remembered(ctx)
    assert "prefers meetings after 10am" in block
    assert "preference, me" in block


def test_it_is_labelled_as_a_record_not_as_instructions(ctx_with):
    """It is the person's own words, but it still sits in a system prompt."""
    block = remembered(ctx_with([("fact", "me", "the office is in Lekki")]))
    assert "not instructions to follow" in block


def test_preferences_come_before_contacts_when_the_budget_is_tight(ctx_with):
    ctx = ctx_with([
        ("contact", "Tunde", "site engineer, reachable on WhatsApp"),
        ("preference", "me", "prefers meetings after 10am"),
    ])
    block = remembered(ctx)
    assert block.index("prefers meetings") < block.index("site engineer"), \
        "a preference changes how a task is done; a contact usually does not"


def test_the_block_cannot_eat_the_context_window(ctx_with):
    """It shares a budget with the tool catalogue, against an 8192 window."""
    many = [("contact", f"Person {i}", "x" * 120) for i in range(40)]
    block = remembered(ctx_with(many))
    assert 0 < len(block) < MEMORY_CHARS + 300, f"block was {len(block)} chars"


def test_a_budget_of_nothing_yields_nothing(ctx_with):
    assert remembered(ctx_with([("fact", "me", "something")]), budget_chars=0) == ""


def test_nothing_remembered_adds_nothing_to_the_prompt(ctx_with):
    assert remembered(ctx_with([])) == ""


def test_no_memory_store_is_not_an_error(tool_ctx):
    tool_ctx.memory_store = None
    assert remembered(tool_ctx) == ""


def test_a_broken_memory_store_never_stops_a_task(tool_ctx):
    class Broken:
        def memories(self, **kw):
            raise RuntimeError("database is locked")
    tool_ctx.memory_store = Broken()
    assert remembered(tool_ctx) == ""


async def test_the_block_reaches_the_system_message_of_a_real_run(tool_ctx, fake_server, tmp_path):
    """End to end through run_agent, against the fake model server."""
    from tests.test_executor import act, finish, run        # the shared harness

    db = Database(tmp_path / "claw.db")
    db.remember("preference", "me", "prefers meetings after 10am", "you told S-CLAW")
    tool_ctx.memory_store = db
    await run(tool_ctx, fake_server, [act("list_tabs"), finish("Done.")])
    system = fake_server.requests[-1]["body"]["messages"][0]["content"]
    assert "prefers meetings after 10am" in system, "memory never reached the model"


# ---------- ranking ----------
def test_a_memory_about_the_person_in_the_task_is_offered_first(ctx_with):
    """Borrowed shape: tier + keyword overlap + recency (agentmem's README),
    without its embeddings stack."""
    ctx = ctx_with([
        ("contact", "Amaka", "accountant"),
        ("contact", "Tunde", "site engineer on the Lekki project"),
        ("preference", "me", "prefers meetings after 10am"),
    ])
    block = remembered(ctx, "message Tunde about the Lekki handover")
    assert block.index("Tunde") < block.index("Amaka"), "the named contact should come first"


def test_with_no_task_text_preferences_still_lead(ctx_with):
    ctx = ctx_with([("contact", "Amaka", "accountant"),
                    ("preference", "me", "prefers meetings after 10am")])
    block = remembered(ctx, "")
    assert block.index("prefers meetings") < block.index("Amaka")


def test_ranking_does_not_let_an_irrelevant_crowd_push_out_a_preference(ctx_with):
    ctx = ctx_with([("contact", f"Person {i}", "x" * 60) for i in range(30)]
                   + [("preference", "me", "prefers meetings after 10am")])
    block = remembered(ctx, "book something")
    assert "prefers meetings after 10am" in block, "a preference was crowded out by contacts"
