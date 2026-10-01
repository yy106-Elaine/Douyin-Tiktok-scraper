"""Getting back the authors of posts that went before the fix.

The account behind a removed post was cleared along with the rest of
the row. These are the authors this study's interviews are for, so
"it is gone from the live database" is not where this ends: the daily
backup from the day before carries the row as it was.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from app.db import SessionLocal


def _backup(path, rows):
    """A copy of the one table this reads, as the real one has it."""
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE web_videos (video_id TEXT, sec_uid TEXT, "
        "author_handle TEXT, author_name TEXT)"
    )
    connection.executemany(
        "INSERT INTO web_videos VALUES (?, ?, ?, ?)", rows
    )
    connection.commit()
    connection.close()


def _gone(session, video_id: str) -> None:
    """A post the checks say has disappeared, with an emptied row."""
    from app.models import LinkCheck, WebVideo
    from app.recheck import ID_CONFIRMED, SERVED_ANOTHER

    session.add(WebVideo(platform="douyin", video_id=video_id, sec_uid=None,
                         fetched_at=datetime(2026, 9, 30, 12, 0)))
    session.add(LinkCheck(
        platform="douyin", video_id=video_id, target_kind="video",
        url=f"https://www.douyin.com/video/{video_id}", http_status=200,
        checked_at=datetime(2026, 9, 29, 12, 0), evidence=ID_CONFIRMED,
    ))
    session.add(LinkCheck(
        platform="douyin", video_id=video_id, target_kind="video",
        url=f"https://www.douyin.com/video/{video_id}", http_status=200,
        checked_at=datetime(2026, 9, 30, 12, 0), evidence=SERVED_ANOTHER,
    ))
    session.commit()


def test_the_account_comes_back_out_of_the_backup(db: None, tmp_path) -> None:
    from app.models import WebAuthor
    from app.recover_authors import recover

    _backup(tmp_path / "scraper-2026-09-29.db", [
        ("7001", "MS4wLjABAAAA-her", "herhandle", "她"),
    ])

    with SessionLocal() as session:
        _gone(session, "7001")
        found = recover(session, tmp_path, apply=True)
        held = session.query(WebAuthor).one()

    assert found == {"7001": ("MS4wLjABAAAA-her", "herhandle", "她")}
    assert held.sec_uid == "MS4wLjABAAAA-her"
    assert held.kept_for_video_id == "7001"


def test_a_backup_is_never_written_to(db: None, tmp_path) -> None:
    """A backup is evidence. The tool that reads it opens it read-only."""
    from app.recover_authors import from_backup

    path = tmp_path / "scraper-2026-09-29.db"
    _backup(path, [("7001", "MS4wLjABAAAA-her", None, "她")])
    before = path.read_bytes()

    assert from_backup(path, {"7001"})
    assert path.read_bytes() == before


def test_a_post_still_up_is_not_in_the_list(db: None, tmp_path) -> None:
    """Its own row still carries the account; fetch_authors reaches it."""
    from datetime import datetime as dt

    from app.models import LinkCheck, WebVideo
    from app.recheck import ID_CONFIRMED
    from app.recover_authors import gone_without_an_account

    with SessionLocal() as session:
        session.add(WebVideo(platform="douyin", video_id="7002",
                             sec_uid="MS4wLjABAAAA-him",
                             fetched_at=dt(2026, 9, 30, 12, 0)))
        session.add(LinkCheck(
            platform="douyin", video_id="7002", target_kind="video",
            url="https://www.douyin.com/video/7002", http_status=200,
            checked_at=dt(2026, 9, 30, 12, 0), evidence=ID_CONFIRMED,
        ))
        session.commit()

        assert gone_without_an_account(session) == set()
