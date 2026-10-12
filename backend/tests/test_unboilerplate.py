"""The site's own sentence, stored as somebody's caption."""
from __future__ import annotations

from datetime import datetime

from app.db import SessionLocal
from app.douyin_page import _caption_or_boilerplate
from app.models import WebVideo
from app.unboilerplate import boilerplate_rows, clear

SITE_WIDE = ("海量优质视频内容，涵盖游戏、二次元、美食、音乐、知识、"
             "体育运动、旅行、生活等多个领域")
PER_PAGE = "于20261006发布在抖音，已经收获了0个喜欢，来抖音，记录美好生活！"


def test_both_shapes_of_the_platforms_own_wording_are_refused() -> None:
    """The second was found four days after the first was guarded.

    A page that does not hand over its record still carries a
    description, and it is the platform's. Neither shape is a caption
    and neither may be judged as one.
    """
    assert _caption_or_boilerplate(SITE_WIDE) is None
    assert _caption_or_boilerplate(PER_PAGE) is None

    # And a real caption is untouched, including one that happens to
    # mention 抖音.
    for real in ("点赞的都是我老婆#日系 #lwl #fyp",
                 "和老婆的第三年 #wlw",
                 "第一次用抖音剪这个 #lwl"):
        assert _caption_or_boilerplate(real) == real


def test_the_rows_already_written_are_found_and_cleared(db: None) -> None:
    """A wrong caption is worse than none, three times over.

    The topic filter reads it and declines to keep the post's
    pictures -- for a post later removed, the archive's only chance.
    The content coding will read it. And a caption gets quoted in a
    thesis as the author's words.

    NULL is what the passes already treat as "cannot tell", and a
    post with no caption is kept rather than filtered out.
    """
    with SessionLocal() as session:
        session.add_all([
            WebVideo(platform="douyin_note", video_id="7001",
                     caption=SITE_WIDE, parsed_by="surface",
                     fetched_at=datetime(2026, 10, 12, 12, 0)),
            WebVideo(platform="douyin", video_id="7002",
                     caption=PER_PAGE, parsed_by="surface",
                     fetched_at=datetime(2026, 10, 12, 12, 0)),
            WebVideo(platform="douyin_note", video_id="7003",
                     caption="和老婆的第三年 #wlw", parsed_by="api",
                     fetched_at=datetime(2026, 10, 12, 12, 0)),
            WebVideo(platform="douyin_note", video_id="7004",
                     caption=None, parsed_by="surface",
                     fetched_at=datetime(2026, 10, 12, 12, 0)),
        ])
        session.commit()

        found = boilerplate_rows(session)
        assert sorted(row.video_id for row in found) == ["7001", "7002"]

        assert clear(found) == 2
        session.commit()

        kept = {row.video_id: row.caption for row in session.scalars(
            __import__("sqlalchemy").select(WebVideo))}

    assert kept["7001"] is None
    assert kept["7002"] is None
    # The real caption and the already-empty one are not touched.
    assert kept["7003"] == "和老婆的第三年 #wlw"
    assert kept["7004"] is None
