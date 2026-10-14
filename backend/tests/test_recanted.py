"""Did the degraded instrument also manufacture removals?

The unreadable pages were the visible half of the 10-05 regression.
The question this answers is whether there was an invisible half:
`SERVED_ANOTHER` reads a removal off a record belonging to a
different post, which is also what a page that failed to load its
own content and fell through to a recommendation would produce.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.db import SessionLocal
from app.models import LinkCheck
from app.recanted import GONE_EVIDENCE, recanted_by_day
from app.recheck import (
    ID_CONFIRMED,
    NOTHING_READ,
    PAGE_SAYS_GONE,
    SERVED_ANOTHER,
)

_START = datetime(2026, 10, 9, 9, 0)


def _check(video_id: str, evidence: str, hours: float,
           platform: str = "douyin") -> LinkCheck:
    return LinkCheck(
        video_id=video_id,
        platform=platform,
        url=f"https://www.douyin.com/video/{video_id}",
        checked_at=_START + timedelta(hours=hours),
        evidence=evidence,
    )


def _since():
    return _START - timedelta(days=1)


def test_a_removal_a_later_check_undid_is_counted(db: None) -> None:
    with SessionLocal() as session:
        session.add_all([
            _check("a", SERVED_ANOTHER, 0),
            _check("a", ID_CONFIRMED, 50),      # three days later
            _check("b", SERVED_ANOTHER, 1),     # still gone
        ])
        session.commit()

        days = recanted_by_day(session, "douyin", _since())

    assert len(days) == 1
    assert days[0].said_gone == 2
    assert days[0].recanted == 1
    assert days[0].share == 0.5


def test_silence_is_not_a_correction(db: None) -> None:
    """A later unreadable check says nothing.

    Counting it as a recant would hide the very failure this looks
    for: the degraded instrument produced unreadable pages *and*
    (possibly) false removals, and letting one cancel the other
    would make the window look clean.
    """
    with SessionLocal() as session:
        session.add_all([
            _check("a", SERVED_ANOTHER, 0),
            _check("a", NOTHING_READ, 30),
        ])
        session.commit()

        days = recanted_by_day(session, "douyin", _since())

    assert days[0].said_gone == 1
    assert days[0].recanted == 0


def test_a_check_before_the_removal_does_not_undo_it(db: None) -> None:
    """Every post was alive before it went. Only a *later* sighting
    is a correction."""
    with SessionLocal() as session:
        session.add_all([
            _check("a", ID_CONFIRMED, -5),
            _check("a", SERVED_ANOTHER, 0),
        ])
        session.commit()

        days = recanted_by_day(session, "douyin", _since())

    assert days[0].said_gone == 1
    assert days[0].recanted == 0


def test_the_two_kinds_of_removal_are_kept_apart(db: None) -> None:
    """They are different claims and only one is easy to fake.

    Douyin's own wording is hard to produce by accident. A record
    belonging to another post is what a broken page also produces.
    """
    with SessionLocal() as session:
        session.add_all([
            _check("a", SERVED_ANOTHER, 0),
            _check("a", ID_CONFIRMED, 50),
            _check("b", PAGE_SAYS_GONE, 1),
            _check("c", PAGE_SAYS_GONE, 2),
        ])
        session.commit()

        day = recanted_by_day(session, "douyin", _since())[0]

    assert day.by_evidence == {SERVED_ANOTHER: 1, PAGE_SAYS_GONE: 2}
    assert day.recanted_by_evidence == {SERVED_ANOTHER: 1}
    assert set(GONE_EVIDENCE) == {SERVED_ANOTHER, PAGE_SAYS_GONE}


def test_platforms_do_not_mix(db: None) -> None:
    """The video pass and the 图文 pass failed at very different
    rates, and averaging them would hide whichever is worse."""
    with SessionLocal() as session:
        session.add(_check("v", SERVED_ANOTHER, 0))
        session.add(_check("n", SERVED_ANOTHER, 0, platform="douyin_note"))
        session.commit()

        assert recanted_by_day(session, "douyin", _since())[0].said_gone == 1
        assert recanted_by_day(
            session, "douyin_note", _since())[0].said_gone == 1
