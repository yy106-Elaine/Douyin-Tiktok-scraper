"""Telling a lost session apart from awkward posts, out of logs already written.

Five unreadable rates have been measured and four causes proposed
and withdrawn. None of them asked where in the run the failures sat,
and the two candidate stories put them in places that look nothing
alike.
"""
from __future__ import annotations

from app.logshape import shape_of


def _log(flags: list[bool]) -> str:
    total = len(flags)
    lines = []
    for index, bad in enumerate(flags, start=1):
        said = ("HTTP 200: nothing readable" if bad
                else "alive -- id confirmed")
        lines.append(f"[{index}/{total}] {said}")
    return "\n".join(lines)


def test_a_session_that_ended_mid_pass_leaves_a_tail() -> None:
    """Every page after the session goes is unreadable, to the end.

    The pass does not crash. It walks the rest of the list reading
    shells, and the result is reported as a rate -- which is really
    a position: 79% means it broke early, 20% means it broke late.
    """
    found = shape_of(_log([False] * 30 + [True] * 120))

    assert found.pages == 150
    assert found.unreadable == 120
    assert found.first_bad == 31
    assert found.tail == 120
    assert found.good_after_first_bad == 0
    assert "broke at page 31 and never recovered" in found.verdict


def test_awkward_posts_fall_all_over_the_list() -> None:
    """If it is the posts, the failures sit where those posts sit."""
    flags = [index % 3 == 0 for index in range(1, 151)]
    found = shape_of(_log(flags))

    assert found.unreadable == 50
    assert found.good_after_first_bad > 50
    assert found.verdict.startswith("scattered")


def test_a_clean_pass_says_so() -> None:
    found = shape_of(_log([False] * 18))
    assert found.unreadable == 0
    assert found.verdict == "no unreadable pages"
    assert found.first_bad is None


def test_one_bad_page_near_the_end_is_not_a_broken_session() -> None:
    """A tail of one is a page, not a pattern. The two 26-page samples
    that started all of this each had exactly one failure."""
    found = shape_of(_log([False] * 17 + [True]))
    assert found.tail == 1
    assert found.verdict.startswith("scattered")


def test_lines_that_are_not_progress_lines_are_ignored() -> None:
    """Logs carry the heartbeat, the estimate table, and the summary."""
    text = (
        "database copied to backups/scraper.db\n"
        "[1/3] alive -- id confirmed\n"
        "  still waiting for the sign-in (880s left)\n"
        "[2/3] HTTP 200: nothing readable  [1 payload(s), 120 JSON]\n"
        "[3/3] HTTP 200: nothing readable\n"
        "page reads: 3 in 1 min -- median 4.3s\n"
    )
    found = shape_of(text)
    assert found.pages == 3
    assert found.total == 3
    assert found.unreadable == 2
    assert found.tail == 2
