"""The survival curve, and the two ways it would otherwise lie.

A plain Kaplan-Meier call on this sample would be wrong twice over:
it would credit every video with surviving the days before anyone was
watching it, and it would date every removal to the check that found
it. Both are tested here, because both are invisible in the output.
"""

from datetime import datetime, timedelta

from app.recheck import ALIVE, GONE
from app.survival import Finding, kaplan_meier

POSTED = datetime(2026, 9, 1, 12, 0)
DAY = timedelta(days=1)


def _finding(
    video_id: str,
    collected_after: timedelta,
    *,
    last_alive_after: timedelta,
    gone_after: timedelta | None = None,
    watched_until: timedelta | None = None,
) -> Finding:
    gone = POSTED + gone_after if gone_after is not None else None
    last_checked = (
        POSTED + watched_until if watched_until is not None
        else (gone or POSTED + last_alive_after)
    )
    return Finding(
        video_id=video_id,
        platform="douyin",
        author_handle=None,
        url=None,
        checks=3,
        uninformative=0,
        first_checked_at=POSTED + collected_after,
        last_checked_at=last_checked,
        last_alive_at=POSTED + last_alive_after,
        first_gone_at=gone,
        current=GONE if gone else ALIVE,
        outcome=GONE if gone else None,
        published_at=POSTED,
        collected_at=POSTED + collected_after,
        first_gone_ever=gone,
    )


def test_a_removal_is_dated_to_the_middle_of_its_bracket() -> None:
    """Not to the check that found it, which is the schedule's time.

    Alive on day 2, gone on day 4: the curve steps at day 3. Dating
    it to day 4 would push every removal in the study later by about
    half a checking cycle and make the platform look slower than it
    is.
    """
    curve = kaplan_meier([
        _finding("a", timedelta(0), last_alive_after=2 * DAY, gone_after=4 * DAY)
    ])

    assert [step.age for step in curve.steps] == [3 * DAY]
    assert curve.resolution == 2 * DAY


def test_a_video_is_not_credited_with_days_nobody_watched() -> None:
    """Delayed entry, which is the whole argument about the TikTok sample.

    Two videos: one watched from birth and removed on day 2, one
    first seen at day 10. At day 2 the risk set is one video, not
    two. Counting the latecomer there would halve the hazard using a
    video whose survival to day 2 was never observed -- it is in the
    sample *because* it survived.
    """
    early = _finding("early", timedelta(0), last_alive_after=DAY,
                     gone_after=3 * DAY)
    late = _finding("late", 10 * DAY, last_alive_after=12 * DAY,
                    watched_until=12 * DAY)

    curve = kaplan_meier([early, late])

    assert len(curve.steps) == 1
    step = curve.steps[0]
    assert step.age == 2 * DAY
    assert step.at_risk == 1
    assert step.survival == 0.0


def test_the_latecomer_joins_the_risk_set_once_it_is_being_watched() -> None:
    """It is excluded before entry, not excluded altogether."""
    early = _finding("early", timedelta(0), last_alive_after=20 * DAY,
                     watched_until=20 * DAY)
    late = _finding("late", 10 * DAY, last_alive_after=11 * DAY,
                    gone_after=13 * DAY)

    curve = kaplan_meier([early, late])

    assert [step.age for step in curve.steps] == [12 * DAY]
    assert curve.steps[0].at_risk == 2


def test_a_median_that_has_not_been_reached_is_none() -> None:
    """The reason this module reports a curve instead of a number.

    One removal in five is not a short median or a long one. It is a
    curve that has not crossed a half, and the only honest reading is
    that the median is longer than the study has run.
    """
    items = [
        _finding("gone", timedelta(0), last_alive_after=DAY, gone_after=3 * DAY)
    ] + [
        _finding(f"alive{n}", timedelta(0), last_alive_after=20 * DAY,
                 watched_until=20 * DAY)
        for n in range(4)
    ]

    curve = kaplan_meier(items)

    assert curve.quantile(0.5) is None
    # A fifth is reached, though, and that one is a real measurement.
    assert curve.quantile(0.2) == 2 * DAY


def test_survival_past_the_last_observation_is_unknown_not_flat() -> None:
    """A curve drawn flat to the right edge claims nothing happened there.

    Nothing was watched there. The estimate ends where the data does.
    """
    curve = kaplan_meier([
        _finding("a", timedelta(0), last_alive_after=DAY, gone_after=3 * DAY),
        _finding("b", timedelta(0), last_alive_after=5 * DAY,
                 watched_until=5 * DAY),
    ])

    # Alive on day 1, gone on day 3: the step lands at the midpoint.
    assert curve.survival_at(DAY) == 1.0
    assert curve.survival_at(2 * DAY) == 0.5
    assert curve.survival_at(400 * DAY) is None


def test_a_video_with_no_publication_time_is_left_out() -> None:
    """There is no age to place it at, so it cannot enter the curve."""
    undated = _finding("x", timedelta(0), last_alive_after=DAY,
                       gone_after=2 * DAY)
    undated.published_at = None

    assert kaplan_meier([undated]).sample == 0
