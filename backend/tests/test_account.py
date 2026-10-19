"""One account's whole record, for weighing what an interviewee says.

The first two interviews produced two claims the corpus can be asked
about: one person said nothing of hers had ever been removed, and
one said everything about couples gets throttled. Both are claims
about particular videos.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.account import checks_of, find_account, posts_of, state_of
from app.db import SessionLocal
from app.models import AuthorPost, LinkCheck, WebAuthor, WebVideo
from app.recheck import (
    ALIVE,
    GONE,
    ID_CONFIRMED,
    NOTHING_READ,
    PAGE_SAYS_GONE,
    SERVED_ANOTHER,
)

_START = datetime(2026, 10, 1, 9, 0)


def _check(video_id: str, evidence: str, days: float) -> LinkCheck:
    return LinkCheck(
        video_id=video_id, platform="douyin",
        url=f"https://www.douyin.com/video/{video_id}",
        checked_at=_START + timedelta(days=days), evidence=evidence)


def test_found_by_the_number_a_person_actually_has(db: None) -> None:
    """The 抖音号 is what is in front of her after an interview; the
    sec_uid is what the database keys on."""
    with SessionLocal() as session:
        session.add(WebAuthor(sec_uid="MS4w-abc", author_handle="981373074",
                              author_name="someone"))
        session.commit()

        assert find_account(session, "981373074").sec_uid == "MS4w-abc"
        assert find_account(session, "MS4w-abc").author_handle == "981373074"
        assert find_account(session, "nobody") is None


def test_the_sequence_is_what_distinguishes_the_readings(db: None) -> None:
    """"gone" and "gone, back, gone again" are different objects, and
    the first word alone hides which one is in hand."""
    with SessionLocal() as session:
        session.add_all([
            _check("stayed", ID_CONFIRMED, 0),
            _check("stayed", PAGE_SAYS_GONE, 1),
            _check("stayed", PAGE_SAYS_GONE, 2),

            _check("flapped", ID_CONFIRMED, 0),
            _check("flapped", SERVED_ANOTHER, 1),
            _check("flapped", ID_CONFIRMED, 2),
        ])
        session.commit()

        now, shape = state_of(checks_of(session, "stayed"))
        assert now == GONE
        assert shape == f"{ALIVE} → {GONE}"

        now, shape = state_of(checks_of(session, "flapped"))
        assert now == ALIVE
        assert shape == f"{ALIVE} → {GONE} → {ALIVE}"


def test_an_unreadable_check_does_not_enter_the_sequence(db: None) -> None:
    """It says nothing. Letting it into the shape would invent a
    state change out of a day the instrument could not see."""
    with SessionLocal() as session:
        session.add_all([
            _check("v", ID_CONFIRMED, 0),
            _check("v", NOTHING_READ, 1),
            _check("v", ID_CONFIRMED, 2),
        ])
        session.commit()

        now, shape = state_of(checks_of(session, "v"))

    assert now == ALIVE
    assert shape == ALIVE


def test_posts_come_back_newest_first_with_their_file(db: None) -> None:
    """The point of the file path is that the video can be watched —
    an interviewee said couple videos get throttled, and that is a
    claim about what is in them."""
    with SessionLocal() as session:
        session.add(WebAuthor(sec_uid="acct", author_handle="663"))
        for n, day in (("old", 1), ("new", 9)):
            session.add(WebVideo(
                platform="douyin", video_id=n, sec_uid="acct",
                caption=f"{n} #情侣", posted_on=datetime(2026, 10, day),
                local_path=f"/videos/{n}.mp4"))
            session.add(AuthorPost(sec_uid="acct", video_id=n,
                                   platform="douyin"))
        session.commit()

        rows = posts_of(session, "acct")

    assert [r.video_id for r in rows] == ["new", "old"]
    assert rows[0].local_path == "/videos/new.mp4"


def test_an_account_with_nothing_in_the_corpus_is_not_an_error(db: None) -> None:
    with SessionLocal() as session:
        session.add(WebAuthor(sec_uid="empty", author_handle="000"))
        session.commit()
        assert posts_of(session, "empty") == []
