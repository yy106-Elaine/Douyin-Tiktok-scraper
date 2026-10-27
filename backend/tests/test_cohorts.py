"""The cohort table, which is what the faulty weeks can still carry."""
from datetime import datetime, timedelta

from app.cohorts import cohort_of, exposure
from app.survival import Finding


def _finding(collected: datetime | None, last: datetime | None) -> Finding:
    return Finding(
        video_id="1", platform="douyin_note", author_handle=None, url=None,
        checks=1, uninformative=0,
        first_checked_at=last, last_checked_at=last,
        last_alive_at=last, first_gone_at=None,
        current="alive", outcome=None,
        collected_at=collected,
    )


def test_a_cohort_is_labelled_by_the_monday_of_its_week() -> None:
    """A week number nobody can place in October is not a label."""
    # 2026-10-21 is a Wednesday; its Monday is 2026-10-19.
    item = _finding(datetime(2026, 10, 21, 9, 0), datetime(2026, 10, 27))
    assert cohort_of(item, "week") == "2026-10-19"
    assert cohort_of(item, "day") == "2026-10-21"


def test_a_post_with_no_collection_date_joins_no_cohort() -> None:
    """Rather than silently landing in the earliest one."""
    assert cohort_of(_finding(None, datetime(2026, 10, 27)), "week") is None


def test_exposure_is_the_median_not_the_mean() -> None:
    """One long-watched post must not stretch a week of fresh ones."""
    start = datetime(2026, 10, 20)
    items = [
        _finding(start, start + timedelta(days=1)),
        _finding(start, start + timedelta(days=1)),
        _finding(start, start + timedelta(days=40)),
    ]
    assert exposure(items) == timedelta(days=1)


def test_exposure_is_none_when_nothing_has_both_dates() -> None:
    assert exposure([_finding(None, None)]) is None


def test_the_command_runs(db: None, capsys) -> None:
    """The CLI path, which the helper tests above do not reach.

    The first version imported PLATFORMS from the wrong module and
    every test here still passed, because they all called the
    functions directly. It failed on the first real invocation. A
    thin wrapper is still a path, and an import error in it is
    indistinguishable from the tool not working at all.
    """
    import sys

    from app.cohorts import main

    argv = sys.argv
    sys.argv = ["app.cohorts"]
    try:
        main()
    finally:
        sys.argv = argv
    # Nothing collected in an empty database, which is a result, not
    # a crash.
    capsys.readouterr()
