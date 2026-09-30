"""The analysis pass, and the three things it must not let itself say.

A raw rate is not comparable across platforms, a day nobody looked is
not a day with no removals, and a 图文 counted twice is not a second
removal. Each is a real mistake this study has already come close to
making, so each gets a test.
"""
from __future__ import annotations

import csv
from datetime import datetime

from app.analyse import captions, daily_hazard, export, observed_days, own
from app.db import SessionLocal
from app.models import LinkCheck, WebVideo
from app.survival import findings

ALIVE_EVIDENCE = "id confirmed"
GONE_EVIDENCE = "served another video"


def _check(
    session,
    platform: str,
    video_id: str,
    when: datetime,
    alive: bool = True,
) -> None:
    session.add(
        LinkCheck(
            platform=platform,
            video_id=video_id,
            target_kind="video",
            url=f"https://www.douyin.com/video/{video_id}",
            http_status=200,
            evidence=ALIVE_EVIDENCE if alive else GONE_EVIDENCE,
            checked_at=when,
        )
    )


def test_a_note_is_counted_with_douyin_but_not_as_a_video(db: None) -> None:
    """The dashboard's family merge is the opposite of what this wants.

    `findings` folds 图文 into douyin so the site shows one platform.
    A comparison between the two formats needs them apart, and the run
    report that once claimed the notes' removals as the video pass's
    is what this guards against.
    """
    with SessionLocal() as session:
        _check(session, "douyin", "7001", datetime(2026, 9, 25, 18, 0))
        _check(session, "douyin_note", "7002", datetime(2026, 9, 25, 18, 0))
        session.commit()

        merged = {f.video_id for f in findings(session, "douyin")}
        assert merged == {"7001", "7002"}

        assert {f.video_id for f in own(session, "douyin")} == {"7001"}
        assert {f.video_id for f in own(session, "douyin_note")} == {"7002"}


def test_a_day_nobody_looked_is_absent_not_zero(db: None) -> None:
    """2026-09-27, as data rather than as a footnote.

    A calendar would put a zero there, and a zero is a claim: we
    looked and nothing was removed. The series is built from the
    checks, so the day simply is not in it.
    """
    with SessionLocal() as session:
        _check(session, "douyin", "7001", datetime(2026, 9, 25, 18, 0))
        _check(session, "douyin", "7001", datetime(2026, 9, 28, 18, 0))
        session.commit()

        assert sorted(observed_days(session, "douyin")) == ["2026-09-25", "2026-09-28"]

        days = [row[0] for row in daily_hazard(session, "douyin", own(session, "douyin"))]
        assert "2026-09-26" not in days
        assert "2026-09-27" not in days


def test_a_day_is_the_researchers_day_not_utcs(db: None) -> None:
    """An evening pass in New York is the next morning in UTC.

    Binning by `datetime.utcnow().date()` split one evening's run
    across two days and made a 14-hour-old removal look 48 hours old.
    """
    with SessionLocal() as session:
        # 22:00 on the 25th in New York.
        _check(session, "douyin", "7001", datetime(2026, 9, 26, 2, 0))
        session.commit()

        assert sorted(observed_days(session, "douyin")) == ["2026-09-25"]


def test_a_video_already_gone_is_not_at_risk_again(db: None) -> None:
    """The denominator is who could still be removed, not who was checked.

    Leaving a removed video in the risk set on later days would divide
    each day's events by a population that cannot produce them, and
    every hazard after the first would read low.
    """
    with SessionLocal() as session:
        for video_id in ("7001", "7002"):
            _check(session, "douyin", video_id, datetime(2026, 9, 25, 18, 0))
        _check(session, "douyin", "7001", datetime(2026, 9, 26, 18, 0), alive=False)
        _check(session, "douyin", "7002", datetime(2026, 9, 26, 18, 0))
        _check(session, "douyin", "7001", datetime(2026, 9, 27, 18, 0), alive=False)
        _check(session, "douyin", "7002", datetime(2026, 9, 27, 18, 0))
        session.commit()

        rows = {row[0]: row for row in daily_hazard(session, "douyin", own(session, "douyin"))}
        assert rows["2026-09-25"][1:3] == (2, 0)
        # One of the two goes, and it is the one counted.
        assert rows["2026-09-26"][1:3] == (2, 1)
        # The next day only the survivor is still at risk.
        assert rows["2026-09-27"][1:3] == (1, 0)


def test_export_writes_the_interval_not_a_removal_time(db: None, tmp_path) -> None:
    """Last alive and first gone, both in local wall clock.

    A CSV that disagreed with the dashboard by four hours would be
    read as a finding about the platform rather than about the
    timezone, so the export converts exactly as the pages do.
    """
    with SessionLocal() as session:
        _check(session, "douyin", "7001", datetime(2026, 9, 25, 18, 0))
        _check(session, "douyin", "7001", datetime(2026, 9, 26, 18, 0), alive=False)
        session.add(
            WebVideo(
                platform="douyin",
                video_id="7001",
                caption="姐妹 情侣 日常\n第二行",
                fetched_at=datetime(2026, 9, 25, 18, 0),
            )
        )
        session.commit()

        path = str(tmp_path / "findings.csv")
        assert export(session, path) == 1

        with open(path, encoding="utf-8") as handle:
            row = next(iter(csv.DictReader(handle)))

        assert row["platform"] == "douyin"
        assert row["is_gone"] == "1"
        # 18:00 UTC is 14:00 in New York, and both columns say so.
        assert row["last_alive_at"] == "2026-09-25 14:00:00"
        assert row["first_gone_at"] == "2026-09-26 14:00:00"
        # The caption survives as one line, so a row is one row.
        assert "\n" not in row["caption"]
        assert row["caption"].startswith("姐妹 情侣 日常")


def test_a_captionless_video_is_an_empty_string_not_a_missing_row(db: None) -> None:
    """"No caption" is a category, not an absence.

    Sixty-odd collected videos carry no caption at all. They are
    usable for survival and not for text analysis, and the export has
    to keep the difference legible instead of dropping them.
    """
    with SessionLocal() as session:
        session.add(
            WebVideo(
                platform="douyin",
                video_id="7001",
                caption=None,
                fetched_at=datetime(2026, 9, 25, 18, 0),
            )
        )
        session.commit()

        assert captions(session, "douyin") == {"7001": ""}
