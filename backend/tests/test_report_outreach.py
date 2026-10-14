"""The two new panels: what Douyin said, and who to write to."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.db import SessionLocal
from app.fetch_videos import record_check
from app.recheck import API_FILTERED, SERVED_ANOTHER
from app.report import (
    REASON_GLOSS,
    WHY_CONTACT,
    hashtags_of,
    reasons_seen,
)


class _Page:
    http_status = 200
    error = None


def test_a_post_counts_once_however_often_it_was_checked(db: None) -> None:
    """One row per post, not per check.

    A post re-read on five days would otherwise count five times,
    and the commonest reason would be whichever posts were checked
    most rather than whichever reason Douyin gives most.
    """
    when = datetime(2026, 10, 14, 9, 0)
    with SessionLocal() as session:
        for day in range(5):
            check = record_check(
                session, "v1", _Page(), API_FILTERED,
                "https://www.douyin.com/video/v1", "douyin",
                filter_reason="status_self_see")
        record_check(session, "v2", _Page(), API_FILTERED,
                     "https://www.douyin.com/video/v2", "douyin",
                     filter_reason="status_deleted")

        counted = dict(reasons_seen(session))

    assert counted == {"status_self_see": 1, "status_deleted": 1}


def test_the_other_evidences_are_not_drawn_as_unknown(db: None) -> None:
    """They carry no reason, so a slice for them would be labelled
    "unknown" while really meaning "a different question was
    asked"."""
    with SessionLocal() as session:
        record_check(session, "v1", _Page(), SERVED_ANOTHER,
                     "https://www.douyin.com/video/v1", "douyin")
        assert reasons_seen(session) == []


def test_a_missing_reason_is_called_unstated(db: None) -> None:
    with SessionLocal() as session:
        record_check(session, "v1", _Page(), API_FILTERED,
                     "https://www.douyin.com/video/v1", "douyin",
                     filter_reason=None)
        assert reasons_seen(session) == [("unstated", 1)]
    assert "no reason given" in REASON_GLOSS["unstated"]


def test_every_cell_has_a_reason_to_contact() -> None:
    """The four cells of the sampling frame, each with a sentence
    for the researcher's own notes -- never for the message."""
    from app.outreach import stratum_of
    from app.interviews import Candidate, Post

    def person(gone: int, back: int) -> Candidate:
        posts = [
            Post(video_id=f"g{i}", platform="douyin", caption=None,
                 published_at=None, first_gone_at=datetime(2026, 9, 1),
                 came_back_at=None, lifetime=None, gone=True, ever_gone=True)
            for i in range(gone)
        ] + [
            Post(video_id=f"b{i}", platform="douyin", caption=None,
                 published_at=None, first_gone_at=datetime(2026, 9, 1),
                 came_back_at=datetime(2026, 9, 5), lifetime=None,
                 gone=False, ever_gone=True)
            for i in range(back)
        ]
        return Candidate(sec_uid="a", handle="h", name=None, posts=posts)

    for gone, back in ((1, 0), (3, 0), (0, 1), (0, 2)):
        assert stratum_of(person(gone, back)) in WHY_CONTACT


def test_hashtags_come_off_a_caption() -> None:
    """Used to spread the recruiting across subject matter, not to
    classify anything -- the content coding does that later."""
    assert hashtags_of("好久不见 #wlw #拉拉日常 #les") == [
        "wlw", "拉拉日常", "les"]
    assert hashtags_of("#攻击性穿搭 #1 #wlw") == ["攻击性穿搭", "1", "wlw"]
    assert hashtags_of(None) == []
    assert hashtags_of("no tags here") == []


def test_the_contact_panel_is_off_unless_asked(db: None) -> None:
    """The page is otherwise safe to leave on a desk; with the list
    it names real people and links to their profiles."""
    from app.report import build

    with SessionLocal() as session:
        assert "访谈名单" not in build(session)
