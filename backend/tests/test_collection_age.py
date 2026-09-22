"""Left truncation: a removal before the first sighting is unobservable."""

from datetime import datetime, timedelta

from app.recheck import ALIVE, GONE
from app.survival import (
    Finding,
    age_at_collection,
    band_for,
    by_collection_age,
    horizon,
)

POSTED = datetime(2026, 9, 1, 12, 0)


def _finding(
    video_id: str,
    collected_after: timedelta,
    gone_after: timedelta | None = None,
    last_alive_after: timedelta | None = None,
    watched_until: timedelta | None = None,
) -> Finding:
    collected = POSTED + collected_after
    last_alive = POSTED + last_alive_after if last_alive_after else collected
    gone = POSTED + gone_after if gone_after else None
    last_checked = POSTED + watched_until if watched_until else (gone or last_alive)
    return Finding(
        video_id=video_id,
        platform="tiktok",
        author_handle=None,
        url=None,
        checks=2,
        uninformative=0,
        first_checked_at=collected,
        last_checked_at=last_checked,
        last_alive_at=last_alive,
        first_gone_at=gone,
        current=GONE if gone else ALIVE,
        outcome=GONE if gone else None,
        published_at=POSTED,
        collected_at=collected,
    )


def test_a_month_old_video_is_not_a_survivor_of_its_first_three_days():
    """It is absent from the question, not present and alive.

    A TikTok search for a month-old phrase returns what lasted a
    month. Counting those as survivors of day three would put the
    search's own selection into the numerator's denominator and drag
    every early-removal rate towards zero.
    """
    old = _finding("old", collected_after=timedelta(days=30),
                   watched_until=timedelta(days=40))
    window = horizon([old], timedelta(days=3))
    assert (window.eligible, window.removed, window.survived) == (0, 0, 0)
    assert window.rate is None


def test_a_video_watched_from_the_first_hour_answers_the_question():
    fresh = _finding("fresh", collected_after=timedelta(hours=1),
                     gone_after=timedelta(days=2))
    stayed = _finding("stayed", collected_after=timedelta(hours=2),
                      watched_until=timedelta(days=5))
    window = horizon([fresh, stayed], timedelta(days=3))
    assert (window.eligible, window.removed, window.survived) == (2, 1, 1)
    assert window.rate == 0.5


def test_removal_after_the_window_is_a_survival_of_that_window():
    late = _finding("late", collected_after=timedelta(hours=1),
                    last_alive_after=timedelta(days=5),
                    gone_after=timedelta(days=9))
    window = horizon([late], timedelta(days=3))
    assert (window.removed, window.survived) == (0, 1)


def test_a_removal_bracket_straddling_the_window_counts_and_is_flagged():
    """Seen alive on day 2, gone on day 6, window is 3 days.

    The removal may have happened on either side. Dropping it would
    drop the events being measured; counting it silently would hide
    that the schedule, not the platform, decided the answer.
    """
    straddling = _finding("straddle", collected_after=timedelta(hours=1),
                          last_alive_after=timedelta(days=2),
                          gone_after=timedelta(days=6))
    window = horizon([straddling], timedelta(days=3))
    assert (window.removed, window.bracketed) == (1, 1)


def test_still_up_but_not_watched_long_enough_is_neither():
    young = _finding("young", collected_after=timedelta(hours=1),
                     watched_until=timedelta(days=1))
    window = horizon([young], timedelta(days=3))
    assert (window.eligible, window.removed, window.survived, window.censored) == (
        1, 0, 0, 1,
    )
    assert window.rate is None


def test_bands_describe_how_stale_the_sample_was():
    assert band_for(timedelta(hours=3)) == "under a day old"
    assert band_for(timedelta(days=2)) == "1-3 days old"
    assert band_for(timedelta(days=5)) == "3-7 days old"
    assert band_for(timedelta(days=20)) == "1-4 weeks old"
    assert band_for(timedelta(days=60)) == "over a month old"
    assert band_for(None) == "publication time unknown"


def test_the_two_populations_are_reported_apart():
    rows = by_collection_age([
        _finding("a", collected_after=timedelta(hours=1), gone_after=timedelta(days=1)),
        _finding("b", collected_after=timedelta(days=30),
                 watched_until=timedelta(days=40)),
    ])
    assert [label for label, _ in rows] == ["under a day old", "over a month old"]
    assert rows[0][1].gone == 1
    assert rows[1][1].gone == 0


def test_age_is_never_negative():
    early = _finding("early", collected_after=timedelta(seconds=-60))
    assert age_at_collection(early) == timedelta(0)
