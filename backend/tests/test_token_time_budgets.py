"""The token budget and the time budget have to agree.

max_tokens is the guard against a model that will not stop. It only guards
anything if it can be REACHED before request_timeout_s cuts the request off.

It could not. max_tokens was 1536; a 2B Q4 on four CPU cores generates about
10 tokens a second, so 1536 tokens is ~154 seconds against a 120-second
default timeout. The guard never fired. The timeout fired instead, and a
timeout throws the whole reply away - where hitting the cap leaves a
truncated reply that jsonfix can often repair and the retry can correct.

Measured on the held-out tasks (research/performance-audit/):

    planner replies    min 96, median 208, one degenerate reply at the cap
    executor replies   min 41, median 59, max 72

So the cap is there for the degenerate case only, and it must be reachable.
"""

from claw.config import ModelSettings
from claw.models.openai_compat import OpenAICompatAdapter


def test_the_token_budget_fits_the_timeout():
    """The whole point: the cap must be reachable before the timeout."""
    seconds_to_reach_the_cap = OpenAICompatAdapter.max_tokens / OpenAICompatAdapter.SLOW_TOKENS_PER_SECOND
    default_timeout = ModelSettings().request_timeout_s
    assert seconds_to_reach_the_cap < default_timeout, (
        f"{OpenAICompatAdapter.max_tokens} tokens needs "
        f"{seconds_to_reach_the_cap:.0f}s at {OpenAICompatAdapter.SLOW_TOKENS_PER_SECOND} tok/s, "
        f"but the request is cut off at {default_timeout:.0f}s. The runaway guard can never fire."
    )


def test_there_is_headroom_rather_than_a_dead_heat():
    """Equal budgets would be a coin toss on a slightly slow machine."""
    needed = OpenAICompatAdapter.max_tokens / OpenAICompatAdapter.SLOW_TOKENS_PER_SECOND
    assert needed <= ModelSettings().request_timeout_s * 0.9


def test_the_cap_still_clears_a_real_reply():
    """Measured worst non-degenerate reply was 208 tokens for a plan and 72
    for an action. A cap that truncates ordinary work would be worse than no
    cap at all."""
    assert OpenAICompatAdapter.max_tokens >= 4 * 208


def test_the_lowest_allowed_timeout_is_not_silently_broken():
    """request_timeout_s can be set as low as 5s. That cannot reach the cap,
    and nothing pretends otherwise - this records the limit of the guard."""
    floor = ModelSettings.model_fields["request_timeout_s"].metadata
    lowest = next(m.ge for m in floor if hasattr(m, "ge"))
    reachable = lowest * OpenAICompatAdapter.SLOW_TOKENS_PER_SECOND
    assert reachable < OpenAICompatAdapter.max_tokens, (
        "If the lowest timeout could reach the cap, this test is measuring nothing"
    )
