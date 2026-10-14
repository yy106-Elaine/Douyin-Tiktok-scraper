"""The word Douyin used, kept rather than printed and lost.

The re-read of 10-14 turned up six of them. They separate the two
things this study has to keep apart:

    status_deleted         the platform acting
    status_audit_self_see  the platform acting, after a review
    author_secret          the author acting
    status_friend_see      the author acting
    status_self_see        either, and much the commonest
    (empty)                Douyin would not say

Section 8 says this instrument measures unwatchability rather than
moderation. That stays true -- status_self_see, the bulk of them,
is genuinely ambiguous -- but these words are the first thing that
narrows it, and they existed only in a log line until this.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.db import SessionLocal
from app.fetch_videos import record_check
from app.models import LinkCheck
from app.recheck import API_FILTERED, GONE, _BY_EVIDENCE


class _Page:
    http_status = 200
    error = None


def test_the_reason_reaches_the_database(db: None) -> None:
    with SessionLocal() as session:
        record_check(session, "v1", _Page(), API_FILTERED,
                     "https://www.douyin.com/video/v1", "douyin",
                     filter_reason="status_deleted")
        row = session.scalar(select(LinkCheck).where(LinkCheck.video_id == "v1"))

    assert row.evidence == API_FILTERED
    assert row.filter_reason == "status_deleted"
    assert _BY_EVIDENCE[API_FILTERED] == GONE


def test_the_other_evidences_leave_it_empty(db: None) -> None:
    """It describes one kind of removal and must not be guessed at
    for the others."""
    from app.recheck import SERVED_ANOTHER

    with SessionLocal() as session:
        record_check(session, "v2", _Page(), SERVED_ANOTHER,
                     "https://www.douyin.com/video/v2", "douyin")
        row = session.scalar(select(LinkCheck).where(LinkCheck.video_id == "v2"))

    assert row.filter_reason is None


def test_an_unfamiliar_word_is_stored_as_it_came(db: None) -> None:
    """Douyin may use words nobody here has seen. Mapping them to a
    conclusion is a judgement that belongs in the analysis, where it
    can be argued with; this column holds what was said."""
    with SessionLocal() as session:
        record_check(session, "v3", _Page(), API_FILTERED,
                     "https://www.douyin.com/video/v3", "douyin",
                     filter_reason="status_something_new")
        row = session.scalar(select(LinkCheck).where(LinkCheck.video_id == "v3"))

    assert row.filter_reason == "status_something_new"
