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


def test_a_post_can_go_down_come_back_and_go_down_again() -> None:
    """Coming back is an event in a post's past, not its state.

    The author's own account of this: Douyin asks you to edit the
    note, the edited post goes back up, and some of them come down
    again afterwards. The page counted "came back" and stopped
    there, so a reinstatement that did not hold looked exactly like
    one that did.
    """
    from datetime import datetime

    from app.report import reinstatement
    from app.survival import Finding

    def finding(**kw) -> Finding:
        base = dict(
            video_id="v", platform="douyin", author_handle=None, url="u",
            checks=4, uninformative=0, blind=0,
            first_checked_at=datetime(2026, 10, 1),
            last_checked_at=datetime(2026, 10, 8),
            last_alive_at=None, current=None, outcome=None,
        )
        base.update(kw)
        return Finding(**base)

    once_and_back = finding(
        disappearances=1,
        first_gone_ever=datetime(2026, 10, 2),
        came_back_at=datetime(2026, 10, 3),
        first_gone_at=None,
    )
    still_gone = finding(
        disappearances=1,
        first_gone_ever=datetime(2026, 10, 2),
        first_gone_at=datetime(2026, 10, 2),
    )
    down_again = finding(
        disappearances=2,
        first_gone_ever=datetime(2026, 10, 2),
        came_back_at=datetime(2026, 10, 3),
        first_gone_at=datetime(2026, 10, 6),
    )
    back_after_two = finding(
        disappearances=3,
        first_gone_ever=datetime(2026, 10, 2),
        came_back_at=datetime(2026, 10, 7),
        first_gone_at=None,
    )

    found = reinstatement(
        [once_and_back, still_gone, down_again, back_after_two])

    assert found.ever == 4
    # Up at the last check, whatever happened on the way.
    assert found.back == 2
    # Removed more than once, whether or not it is up now.
    assert found.repeats == 2
    assert found.most_cycles == 3
    # Of the two still gone, one had already been reinstated. That is
    # the number the page had no way of showing.
    assert found.gone_again == 1


def test_a_post_removed_once_is_not_a_repeat() -> None:
    """The ordinary case must not be inflated by the new counters."""
    from datetime import datetime

    from app.report import reinstatement
    from app.survival import Finding

    plain = Finding(
        video_id="v", platform="douyin", author_handle=None, url="u",
        checks=2, uninformative=0, blind=0,
        first_checked_at=datetime(2026, 10, 1),
        last_checked_at=datetime(2026, 10, 8),
        last_alive_at=None, current=None, outcome=None,
        disappearances=1,
        first_gone_ever=datetime(2026, 10, 2),
        first_gone_at=datetime(2026, 10, 2),
    )

    found = reinstatement([plain])

    assert (found.ever, found.back) == (1, 0)
    assert (found.repeats, found.gone_again, found.most_cycles) == (0, 0, 0)
