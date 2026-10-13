"""Handing the failed pages back to another arm, which is the only
comparison of the arms that holds the posts constant."""
from __future__ import annotations

from datetime import timedelta

from app.clock import now as utc_now
from app.db import SessionLocal
from app.models import LinkCheck
from app.unreadable import unreadable_since


def _check(video_id: str, evidence: str, hours_ago: float) -> LinkCheck:
    return LinkCheck(
        video_id=video_id,
        platform="douyin_note",
        url=f"https://www.douyin.com/note/{video_id}",
        checked_at=utc_now() - timedelta(hours=hours_ago),
        evidence=evidence,
    )


def test_only_the_pages_whose_latest_word_was_nothing(db: None) -> None:
    """A post unreadable at ten and read at noon is a post that was read.

    Asking for "any unreadable check today" would hand back pages
    that are already answered, and make the retry arm look worse than
    it is on pages it never had to do.
    """
    with SessionLocal() as session:
        session.add_all([
            _check("still-blank", "NOTHING_READ", 2),
            _check("answered-later", "NOTHING_READ", 3),
            _check("answered-later", "ID_CONFIRMED", 1),
            _check("gone", "SERVED_ANOTHER", 2),
            _check("yesterday", "NOTHING_READ", 30),
        ])
        session.commit()

        found = unreadable_since(session, "douyin_note",
                                 utc_now() - timedelta(hours=12))

    assert found == ["still-blank"]


def test_a_different_platform_is_a_different_run(db: None) -> None:
    """The 图文 pass and the video pass fail at different rates, and
    mixing their ids would compare an arm against both at once."""
    with SessionLocal() as session:
        session.add_all([
            _check("note", "NOTHING_READ", 1),
        ])
        video = _check("video", "NOTHING_READ", 1)
        video.platform = "douyin"
        session.add(video)
        session.commit()

        assert unreadable_since(session, "douyin_note",
                                utc_now() - timedelta(hours=12)) == ["note"]
        assert unreadable_since(session, "douyin",
                                utc_now() - timedelta(hours=12)) == ["video"]
