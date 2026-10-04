"""Reinstatement is counted against removals, not against posts watched.

"How many removals were reversed" is a question about removals. And
the removal share elsewhere on the page reads each post at its last
check, so a post taken down and reinstated is counted there as still
up -- true of its state, and the reason the removal it survived has
to be counted here.
"""
from datetime import datetime, timedelta, timezone

from app.report import reinstatement
from app.survival import Finding

DAY = timedelta(days=1)
WHEN = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _post(gone_now: bool, back_after: timedelta | None = None) -> Finding:
    found = Finding(
        video_id="1", platform="douyin", author_handle=None, url=None,
        checks=3, uninformative=0, first_checked_at=WHEN,
        last_checked_at=WHEN + 10 * DAY, last_alive_at=WHEN,
        first_gone_at=None, current="ok", outcome=None,
    )
    if back_after is not None:
        found.disappearances = 1
        found.first_gone_ever = WHEN
        found.came_back_at = WHEN + back_after
        found.first_gone_at = None          # up at the last check
    elif gone_now:
        found.disappearances = 1
        found.first_gone_ever = WHEN
        found.first_gone_at = WHEN
    return found


def test_the_denominator_is_every_post_ever_found_gone():
    items = [
        _post(gone_now=True),
        _post(gone_now=True),
        _post(gone_now=False, back_after=DAY),
        _post(gone_now=False),            # never gone: not in either count
        _post(gone_now=False),
    ]

    found = reinstatement(items)

    assert found.ever == 3
    assert found.back == 1
    assert abs(found.share - 1 / 3) < 1e-9


def test_a_post_that_was_never_removed_is_not_in_the_denominator():
    found = reinstatement([_post(gone_now=False) for _ in range(5)])

    assert found.ever == 0
    assert found.share is None
    assert found.median_down is None


def test_the_median_time_down_is_the_middle_bracket():
    items = [
        _post(gone_now=False, back_after=timedelta(hours=6)),
        _post(gone_now=False, back_after=timedelta(days=2)),
        _post(gone_now=False, back_after=timedelta(days=9)),
    ]

    assert reinstatement(items).median_down == timedelta(days=2)
