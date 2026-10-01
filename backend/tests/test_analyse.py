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


def test_the_caption_dump_carries_no_outcome(db: None) -> None:
    """A taxonomy built while looking at the answer is fitted to it.

    If the captions handed to a human or a model for category design
    arrive labelled "this one was removed", every category that
    emerges is partly a description of removal, and the later finding
    that content predicts removal is circular. So the dump is text
    only: no id, no date, no verdict.
    """
    from app.analyse import caption_dump

    with SessionLocal() as session:
        _check(session, "douyin", "7001", datetime(2026, 9, 25, 18, 0))
        _check(session, "douyin", "7001", datetime(2026, 9, 26, 18, 0), alive=False)
        session.add_all([
            WebVideo(platform="douyin", video_id="7001",
                     caption="和女朋友的\n第三年 #wlw", author_handle="someone",
                     fetched_at=datetime(2026, 9, 25, 18, 0)),
            WebVideo(platform="douyin", video_id="7002", caption=None,
                     fetched_at=datetime(2026, 9, 25, 18, 0)),
        ])
        session.commit()

        path = str(__import__("tempfile").mkdtemp()) + "/captions.txt"
        assert caption_dump(session, path) == 1
        written = open(path, encoding="utf-8").read()

    assert "和女朋友的 第三年 #wlw" in written
    assert "7001" not in written
    assert "someone" not in written
    assert "gone" not in written
    # The captionless posts are counted, not silently dropped.
    assert "1 post(s) carry none" in written


def test_a_removed_posts_caption_survives_the_wipe(db: None) -> None:
    """The captions that matter most are the ones the fetch destroys.

    When Douyin answers with another video's record the post is gone,
    and `fetch_videos.wipe` empties the fetched row -- rightly, since
    none of it belonged to that id. The caption goes with it. Reading
    captions off the fetched rows alone therefore returns text for the
    survivors and blanks for the removed, which is the one bias that
    makes "does content predict removal" unanswerable.

    The phone's capture is never wiped, and for a removed post it is
    the only copy of what the post said.
    """
    from app.analyse import captions
    from app.models import CaptureEvent, DouyinPost

    with SessionLocal() as session:
        event = CaptureEvent(
            participant_id="P001", device_id="d", platform="douyin",
            fingerprint="f", capture_date="2026-09-25",
            captured_at=datetime(2026, 9, 25, 18, 0), payload="{}",
        )
        session.add(event)
        session.flush()
        session.add(DouyinPost(
            capture_event_id=event.id, participant_id="P001",
            captured_at=datetime(2026, 9, 25, 18, 0),
            video_id="7001", caption="和老婆的第三年 #wlw #长发t",
        ))
        # What the fetch left behind after the post was found gone.
        session.add(WebVideo(platform="douyin", video_id="7001", caption=None,
                             fetched_at=datetime(2026, 9, 26, 18, 0)))
        session.commit()

        assert captions(session, "douyin")["7001"] == "和老婆的第三年 #wlw #长发t"


def test_an_out_of_scope_row_is_not_in_the_caption_dump(db: None) -> None:
    """A cookery video in the sample produces a category for cookery.

    The topic filter marks rather than deletes, which is right -- a
    row a filter drops is a disappearance nothing can observe later.
    It does mean the dump has to do the excluding itself.
    """
    from app.analyse import caption_dump
    from app.models import CaptureEvent, DouyinPost

    with SessionLocal() as session:
        event = CaptureEvent(
            participant_id="P001", device_id="d", platform="douyin",
            fingerprint="f", capture_date="2026-09-25",
            captured_at=datetime(2026, 9, 25, 18, 0), payload="{}",
        )
        session.add(event)
        session.flush()
        session.add_all([
            DouyinPost(capture_event_id=event.id, participant_id="P001",
                       captured_at=datetime(2026, 9, 25, 18, 0),
                       video_id="7001", caption="和老婆的第三年 #wlw",
                       relevance=None),
            DouyinPost(capture_event_id=event.id, participant_id="P001",
                       captured_at=datetime(2026, 9, 25, 18, 0),
                       video_id="7002", caption="师傅教做菜！",
                       relevance="no topic term"),
        ])
        session.commit()

        path = str(__import__("tempfile").mkdtemp()) + "/captions.txt"
        assert caption_dump(session, path) == 1
        written = open(path, encoding="utf-8").read()

    assert "和老婆的第三年" in written
    assert "师傅教做菜" not in written


def test_a_post_is_in_the_corpus_once(db: None) -> None:
    """The two Douyin formats share one capture table.

    The phone writes every post it reads into `douyin_posts`,
    whichever format it was, so `captions("douyin")` and
    `captions("douyin_note")` both return it. Walking the two
    platforms and appending counted every captured post twice, and the
    page reported a corpus half again larger than the dashboard's.
    """
    from app.analyse import corpus_captions
    from app.models import CaptureEvent, DouyinPost

    with SessionLocal() as session:
        event = CaptureEvent(
            participant_id="P001", device_id="d", platform="douyin",
            fingerprint="f", capture_date="2026-09-25",
            captured_at=datetime(2026, 9, 25, 18, 0), payload="{}",
        )
        session.add(event)
        session.flush()
        session.add(DouyinPost(
            capture_event_id=event.id, participant_id="P001",
            captured_at=datetime(2026, 9, 25, 18, 0),
            video_id="7001", caption="跟老婆在一起307天了 #wlw",
        ))
        session.commit()

        assert [row[1] for row in corpus_captions(session)] == ["7001"]


def test_a_note_is_reported_as_a_note(db: None) -> None:
    """Deduplicating must not flatten the format distinction.

    Nothing in the capture row says which format it was; the rows
    written after the link resolved do. A 图文 counted as a video
    would put it on the wrong side of the one comparison the two
    formats exist to support.
    """
    from app.analyse import corpus_captions
    from app.models import CaptureEvent, DouyinPost

    with SessionLocal() as session:
        event = CaptureEvent(
            participant_id="P001", device_id="d", platform="douyin",
            fingerprint="f", capture_date="2026-09-25",
            captured_at=datetime(2026, 9, 25, 18, 0), payload="{}",
        )
        session.add(event)
        session.flush()
        session.add_all([
            DouyinPost(capture_event_id=event.id, participant_id="P001",
                       captured_at=datetime(2026, 9, 25, 18, 0),
                       video_id="7002", caption="淡淡的稳稳的两个人 #lwl"),
            WebVideo(platform="douyin_note", video_id="7002",
                     fetched_at=datetime(2026, 9, 25, 18, 0)),
        ])
        session.commit()

        assert corpus_captions(session)[0][0] == "douyin_note"


def test_a_pasted_blob_is_the_only_copy_of_its_own_caption(db: None) -> None:
    """Until the page is fetched, the share text is all there is.

    A hand-pasted post has no capture row and no fetched row, so every
    one of them counted as having no caption at all -- 119 of them at
    once, which is what made a quarter of the corpus look captionless.
    Worse: a post removed before that first fetch ever happens leaves
    the blob as the only copy of its text there will ever be.
    """
    from app.analyse import author_names, captions
    from app.models import SharedLink

    blob = (
        "7.15 复制打开抖音，看看【qianxxxx（限流版的图文作品】"
        "就算你对我说谎我也会爱着你呀。# 古早 # 韩流 ... "
        "https://v.douyin.com/v559YY3leFg/ UYM:/ :8pm"
    )
    with SessionLocal() as session:
        session.add(SharedLink(
            participant_id="P001", platform="douyin_note", raw_text=blob,
            video_id="7003", shared_at=datetime(2026, 10, 1, 2, 0),
            source="pasted",
        ))
        session.commit()

        assert "就算你对我说谎" in captions(session, "douyin_note")["7003"]
        assert author_names(session)["7003"].startswith("qianxxxx")


def test_a_hand_copied_link_is_not_excluded_on_its_truncated_caption(
    db: None,
) -> None:
    """The share blob cuts the caption off, usually right at the tags.

    These posts were found by searching a community tag, so by
    construction they carry one. Reading the truncated copy and
    concluding there is no tag drops the rows that cost the most to
    collect -- 48 of them at once, the first time the blob's caption
    was read at all.
    """
    from app.analyse import corpus_captions
    from app.models import SharedLink

    blob = (
        "3.84 复制打开抖音，看看【qianxxxx的图文作品】"
        "就算你对我说谎我也会爱着你呀。# 古早 # 韩流 ... "
        "https://v.douyin.com/v559YY3leFg/ UYM:/ :8pm"
    )
    with SessionLocal() as session:
        session.add(SharedLink(
            participant_id="P001", platform="douyin_note", raw_text=blob,
            video_id="7003", shared_at=datetime(2026, 10, 1, 2, 0),
            source="pasted",
        ))
        session.commit()

        # The caption that survives the copy carries no community tag
        # at all, and the post stays in the corpus regardless.
        assert [row[1] for row in corpus_captions(session)] == ["7003"]
