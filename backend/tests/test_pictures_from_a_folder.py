"""A design can be asked for with a folder, not a list of filenames.

"Make a flyer with the pictures in this folder" is how a person says it. It
used to need the brain to list the folder first and pass every name back, and a
small brain frequently does not: it passes the folder, the tool answers that
this is not a file, and the request fails although it was perfectly clear.

Listing a folder is deterministic. The playbook is explicit that deterministic
work belongs in code rather than in the model's judgement, and this is the
cheapest possible example: it removes a planning step and a failure mode from
every design task, on every brain.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claw.tools.base import ToolError
from tests.test_desktop import call
from tests.test_images import folder, make_photo  # noqa: F401 - fixtures


@pytest.fixture
def shots(folder: Path) -> Path:
    """A folder of pictures, plus a stray file that is not one."""
    d = folder / "Shoot"
    d.mkdir()
    for i in range(3):
        make_photo(d / f"img{i}.png", color=(60 + i * 40, 90, 150))
    (d / "notes.txt").write_text("not a picture")
    return d


@pytest.mark.asyncio
async def test_a_folder_name_is_enough_for_a_flyer(tool_ctx, shots):
    r = await call(tool_ctx, "make_flyer", title="Open Day", images=["Shoot"], file_name="f1")
    assert r.ok


@pytest.mark.asyncio
async def test_a_collage_takes_every_picture_in_the_folder(tool_ctx, shots):
    r = await call(tool_ctx, "make_collage", images=["Shoot"], file_name="c1")
    assert r.data["pictures"] == 3, "the folder's three pictures were not all used"


@pytest.mark.asyncio
async def test_the_file_that_is_not_a_picture_is_ignored(tool_ctx, shots):
    """A folder has other things in it. That is not an error."""
    r = await call(tool_ctx, "make_collage", images=["Shoot"], file_name="c2")
    assert r.ok and r.data["pictures"] == 3


@pytest.mark.asyncio
async def test_a_pattern_works_too(tool_ctx, folder, shots):
    make_photo(shots / "extra.jpg")
    r = await call(tool_ctx, "make_collage", images=["Shoot/*.png"], file_name="c3")
    assert r.data["pictures"] == 3, "the pattern picked up the .jpg as well"


@pytest.mark.asyncio
async def test_naming_a_file_and_its_folder_does_not_use_it_twice(tool_ctx, shots):
    r = await call(tool_ctx, "make_collage", images=["Shoot", "Shoot/img0.png"], file_name="c4")
    assert r.data["pictures"] == 3, "img0 was counted twice"


@pytest.mark.asyncio
async def test_filenames_still_work_exactly_as_before(tool_ctx, shots):
    r = await call(tool_ctx, "make_collage", images=["Shoot/img0.png", "Shoot/img1.png"], file_name="c5")
    assert r.data["pictures"] == 2


@pytest.mark.asyncio
async def test_an_empty_folder_says_so_rather_than_making_a_blank(tool_ctx, folder):
    (folder / "Empty").mkdir()
    with pytest.raises(ToolError, match="no pictures"):
        await call(tool_ctx, "make_collage", images=["Empty"], file_name="c6")


@pytest.mark.asyncio
async def test_a_folder_outside_the_authorized_ones_is_still_refused(tool_ctx):
    """Convenience must not become a way round the permission check."""
    with pytest.raises(ToolError):
        await call(tool_ctx, "make_collage", images=["C:\\Windows\\System32"], file_name="c7")


# ---------------------------------------------------------------------------
# The other half of the same problem: the shape a small brain sends.
#
# A 2B brain writes images: "a.png, b.png" or points: "fast, cheap" where a
# list was asked for, and pydantic refused the whole call. motion_tools had
# tolerated exactly this for its own points field since the first benchmark,
# and three tools away the same mistake was still fatal. Nothing about the
# request was ambiguous.

from claw.tools.image_tools import CollageArgs, FlyerArgs, PosterArgs


def test_a_comma_separated_string_is_a_list():
    assert FlyerArgs(title="Open Day", images="a.png, b.png").images == ["a.png", "b.png"]
    assert FlyerArgs(title="Open Day", points="fast, cheap, local").points == ["fast", "cheap", "local"]
    assert PosterArgs(title="Film", cover_lines="one, two").cover_lines == ["one", "two"]


def test_newlines_count_as_separators_too():
    assert FlyerArgs(title="Open Day", points="fast\ncheap").points == ["fast", "cheap"]


def test_one_folder_as_a_bare_string_is_accepted():
    """The exact shape of "make a flyer with the pictures in Shoot"."""
    assert CollageArgs(images="Shoot").images == ["Shoot"]
    assert PosterArgs(title="Film", images="Shoot").images == ["Shoot"]


def test_proper_lists_are_untouched():
    assert FlyerArgs(title="Open Day", images=["a.png", "b.png"]).images == ["a.png", "b.png"]


def test_empty_pieces_are_dropped_rather_than_passed_on():
    assert FlyerArgs(title="Open Day", points="fast,, ,cheap").points == ["fast", "cheap"]


def test_the_limits_still_hold():
    """Tolerance is not an excuse to let twenty pictures into a four-picture flyer."""
    assert len(FlyerArgs(title="Open Day", images=",".join(f"{i}.png" for i in range(20))).images) == 4
    assert len(CollageArgs(images=",".join(f"{i}.png" for i in range(40))).images) == 16


@pytest.mark.asyncio
async def test_end_to_end_a_bare_folder_string_makes_the_collage(tool_ctx, shots):
    """Both halves together: a string, naming a folder."""
    r = await call(tool_ctx, "make_collage", images="Shoot", file_name="c8")
    assert r.ok and r.data["pictures"] == 3


# ---------------------------------------------------------------------------
# "and do everything there".
#
# The pictures are in one folder, so that is where the result belongs. It used
# to go to the first authorized folder instead - the person said "there" and
# Claw put it somewhere else, which on a machine with several authorized
# folders means hunting for it. The single-picture tools already save beside
# their input; this is the same rule where several pictures agree.

@pytest.mark.asyncio
async def test_the_result_lands_where_the_pictures_came_from(tool_ctx, shots, folder):
    r = await call(tool_ctx, "make_collage", images=["Shoot"], file_name="made")
    assert Path(r.data["path"]).parent == shots, (
        f"saved to {Path(r.data['path']).parent}, not the folder the pictures came from")


@pytest.mark.asyncio
async def test_a_flyer_too(tool_ctx, shots):
    r = await call(tool_ctx, "make_flyer", title="Open Day", images=["Shoot"], file_name="f-here")
    assert Path(r.data["path"]).parent == shots


@pytest.mark.asyncio
async def test_a_poster_too(tool_ctx, shots):
    r = await call(tool_ctx, "make_poster", title="Show", images=["Shoot"], file_name="p-here")
    assert Path(r.data["path"]).parent == shots


@pytest.mark.asyncio
async def test_an_explicit_folder_still_wins(tool_ctx, shots, folder):
    """Saying where it goes must always beat the guess."""
    (folder / "Output").mkdir()
    r = await call(tool_ctx, "make_collage", images=["Shoot"], folder="Output", file_name="elsewhere")
    assert Path(r.data["path"]).parent == folder / "Output"


@pytest.mark.asyncio
async def test_pictures_from_two_folders_fall_back_to_the_default(tool_ctx, shots, folder):
    """No single answer, so do not invent one."""
    other = folder / "Other"
    other.mkdir()
    make_photo(other / "z.png")
    r = await call(tool_ctx, "make_collage", images=["Shoot/img0.png", "Other/z.png"], file_name="mixed")
    assert Path(r.data["path"]).parent == folder, "guessed a folder when the pictures disagreed"


@pytest.mark.asyncio
async def test_a_design_with_no_pictures_still_has_somewhere_to_go(tool_ctx, folder):
    r = await call(tool_ctx, "make_poster", title="Words only", images=[], file_name="bare-here")
    assert Path(r.data["path"]).parent == folder
