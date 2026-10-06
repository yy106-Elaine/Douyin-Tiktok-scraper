"""One page visit per video, not two."""

from pathlib import Path

import pytest

from app.daily import one, run
from app.fetch_videos import SITES
from app.pagedata import Fetched

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 60_000


def _page(video_id: str, caption: str = "#lwl 今天") -> Fetched:
    return Fetched(
        url="x",
        html="",
        http_status=200,
        payloads=[{
            "aweme_id": video_id,
            "desc": caption,
            "create_time": 1_758_000_000,
            "author": {"nickname": "某人", "unique_id": "abc123"},
            "statistics": {"digg_count": 12, "comment_count": 3, "share_count": 1},
            "video": {"play_addr": {"url_list": ["https://cdn.example/v.mp4"]}},
        }],
    )


@pytest.fixture()
def session(db):
    from app.db import SessionLocal

    with SessionLocal() as open_session:
        yield open_session


def test_the_page_is_read_once_and_the_file_comes_out_of_it(session, tmp_path):
    """The addresses are in the answer the first visit already got.

    Fetching and downloading separately opened every page twice, which
    is a second page load, a second pause and a second request against
    a site that counts them -- for information already in hand.
    """
    visits = []
    outcome, said, kept = one(
        session,
        read=lambda url: visits.append(url) or _page("7686773732988082810"),
        download=lambda address, referer: (MP4, 200),
        video_id="7686773732988082810",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
    )

    assert len(visits) == 1
    assert outcome == "saved"
    assert kept == len(MP4)
    assert (tmp_path / "7686773732988082810.mp4").read_bytes() == MP4


def test_a_removed_video_is_recorded_gone_and_not_downloaded(session, tmp_path):
    """Douyin serves the next recommended video for a removed one.

    Downloading from that answer files somebody else's video under the
    removed video's id: a gap that looks full, which is worse than a
    gap, and only discovered at the point of analysis.
    """
    from app.models import LinkCheck
    from app.recheck import SERVED_ANOTHER

    asked = []
    outcome, said, kept = one(
        session,
        read=lambda url: _page("9999999999999999999"),
        download=lambda address, referer: asked.append(address) or (MP4, 200),
        video_id="7686773732988082810",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
    )

    assert outcome == "gone"
    assert asked == []
    assert list(tmp_path.iterdir()) == []
    check = session.query(LinkCheck).one()
    assert check.evidence == SERVED_ANOTHER
    assert check.video_id == "7686773732988082810"


def test_the_author_of_a_removed_post_survives_the_wipe(session, tmp_path):
    """The one field the study cannot lose, lost exactly when it mattered.

    A post found gone has its contents cleared, because the page that
    answered was another video's record -- and `sec_uid` was in that
    list. The 抖音号 is only on the profile and the profile is only
    reachable through the sec_uid, so the moment a post went, its
    author became unreachable. For a study whose interviews are *with
    the authors of removed posts*, that is every author it needs.

    The account is not the post's content. It moves to `web_authors`,
    which is keyed on the account, and `fetch_authors` reads the
    handle from there afterwards.
    """
    from app.fetch_authors import forget_orphans, wanted
    from app.models import WebAuthor, WebVideo

    # Day one: the post is alive and read, so the account is on file.
    one(
        session,
        read=lambda url: _page("7686773732988082810"),
        download=lambda address, referer: (MP4, 200),
        video_id="7686773732988082810",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
    )
    row = session.query(WebVideo).one()
    row.sec_uid = "MS4wLjABAAAA-whoever"
    # The common case, and the reason this matters: the video page
    # gave a display name and no 抖音号. Where it does give one the
    # author is already reachable and no profile visit is needed.
    row.author_handle = None
    session.commit()

    # Day two: it is gone -- the site answers with another video.
    one(
        session,
        read=lambda url: _page("9999999999999999999"),
        download=lambda address, referer: (MP4, 200),
        video_id="7686773732988082810",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
    )

    # Nothing of the other video's is left on the row ...
    assert session.query(WebVideo).one().sec_uid is None
    # ... but the account is still reachable, and says which post it
    # was kept for.
    held = session.query(WebAuthor).one()
    assert held.sec_uid == "MS4wLjABAAAA-whoever"
    assert held.kept_for_video_id == "7686773732988082810"

    # The housekeeping that drops accounts no video points at any more
    # must not take it: by construction no video points at this one.
    assert forget_orphans(session) == 0
    assert "MS4wLjABAAAA-whoever" in wanted(session)


def test_an_error_page_served_as_a_video_is_refused(session, tmp_path):
    """A media URL fetched without the right session answers 200.

    Saved as .mp4 that gives a folder that looks complete and a corpus
    that is not.
    """
    outcome, said, kept = one(
        session,
        read=lambda url: _page("7686773732988082810"),
        download=lambda address, referer: (b'{"error":"forbidden"}', 200),
        video_id="7686773732988082810",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
    )
    assert outcome == "read"
    assert "not a video" in said
    assert list(tmp_path.iterdir()) == []


def test_a_file_already_held_is_not_fetched_again(session, tmp_path):
    read = lambda url: _page("7686773732988082810")  # noqa: E731
    one(session, read, lambda a, r: (MP4, 200), "7686773732988082810",
        SITES["douyin"], None, tmp_path)

    asked = []
    outcome, said, _ = one(
        session, read, lambda a, r: asked.append(a) or (MP4, 200),
        "7686773732988082810", SITES["douyin"], None, tmp_path,
    )
    assert asked == []
    assert "file held" in said


def test_the_run_counts_a_saved_video_as_read_too(session, tmp_path):
    """One visit produced both the observation and the file."""
    report = run(
        session,
        ["7686773732988082810", "7686773732988082811"],
        read=lambda url: _page(url.rsplit("/", 1)[-1]),
        download=lambda address, referer: (MP4, 200),
        directory=tmp_path,
        site=SITES["douyin"],
        pause_seconds=0,
    )
    assert (report["saved"], report["read"]) == (2, 2)
    assert report["bytes"] == 2 * len(MP4)


def test_an_off_topic_video_is_read_but_not_kept(session, tmp_path):
    """`#butchfemme #femme4butch #lesbiansoftiktok` is somebody's video.

    The page is still visited -- that visit is the takedown check, and
    a rule change can put the video back in the corpus tomorrow, which
    has happened repeatedly. What is skipped is the copy.
    """
    asked = []
    outcome, said, kept = one(
        session,
        read=lambda url: _page("7686773732988082810", "#butchfemme #femme4butch"),
        download=lambda address, referer: asked.append(address) or (MP4, 200),
        video_id="7686773732988082810",
        site=SITES["tiktok"],
        handle=None,
        directory=tmp_path,
    )
    assert outcome == "read"
    assert asked == []
    assert "not kept" in said
    assert list(tmp_path.iterdir()) == []


def test_a_video_with_no_caption_at_all_is_still_kept(session, tmp_path):
    """"no text" is the filter saying it cannot tell, not that it is out.

    A fifth of the Douyin rows have no caption. They were collected by
    searching a community tag, so the evidence that they belong is the
    search, which lives in `feed` and not in the caption -- and the two
    mistakes do not cost the same. A file wrongly kept can be deleted
    whenever the question is settled; a file wrongly skipped cannot be
    fetched once the video is gone. `download_videos.wanted` has always
    made this exception; this pass used to contradict it, and nine
    Douyin videos were sitting unarchived because of that.
    """
    outcome, said, kept = one(
        session,
        read=lambda url: _page("7686427432119291057", ""),
        download=lambda address, referer: (MP4, 200),
        video_id="7686427432119291057",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
    )
    assert outcome == "saved"
    assert kept == len(MP4)


def test_the_page_caption_decides_it_not_the_screen_one(session, tmp_path):
    """The phone's caption is cut off mid-word; the page's is not.

    Judging a never-read video on the screen text would drop videos
    the full caption puts squarely in the corpus -- which is the whole
    reason the page is fetched at all.
    """
    outcome, said, kept = one(
        session,
        read=lambda url: _page(
            "7686773732988082810", "our anniversary #chinese #wlw #lesbiancouple"
        ),
        download=lambda address, referer: (MP4, 200),
        video_id="7686773732988082810",
        site=SITES["tiktok"],
        handle=None,
        directory=tmp_path,
    )
    assert outcome == "saved"
    assert kept == len(MP4)


def test_everything_keeps_the_excluded_ones_too(session, tmp_path):
    outcome, said, kept = one(
        session,
        read=lambda url: _page("7686773732988082810", "#butchfemme #femme4butch"),
        download=lambda address, referer: (MP4, 200),
        video_id="7686773732988082810",
        site=SITES["tiktok"],
        handle=None,
        directory=tmp_path,
        keep_all=True,
    )
    assert outcome == "saved"


def test_the_day_s_change_is_reported_not_left_to_subtraction(db):
    """A pass prints how many are gone *now*, which is a running total.

    Reading the day's news out of it means remembering yesterday's
    number and subtracting, every day, by hand -- on the study's main
    result. Yesterday's Douyin pass printed 20 and today's printed 18,
    and the interesting thing in that pair is not the 18.
    """
    from datetime import datetime

    from app.db import SessionLocal
    from app.models import LinkCheck
    from app.recheck import ID_CONFIRMED, SERVED_ANOTHER
    from app.survival import findings, today_at_a_glance

    today = datetime(2026, 9, 25, 12, 0)
    yesterday = datetime(2026, 9, 24, 12, 0)

    def check(video_id, when, evidence):
        return LinkCheck(
            platform="douyin",
            video_id=video_id,
            target_kind="video",
            url=f"https://www.douyin.com/video/{video_id}",
            http_status=200,
            evidence=evidence,
            checked_at=when,
        )

    with SessionLocal() as session:
        # Gone yesterday, still gone.
        session.add(check("1", yesterday, SERVED_ANOTHER))
        session.add(check("1", today, SERVED_ANOTHER))
        # Gone for the first time today.
        session.add(check("2", yesterday, ID_CONFIRMED))
        session.add(check("2", today, SERVED_ANOTHER))
        # Gone yesterday, back today.
        session.add(check("3", yesterday, SERVED_ANOTHER))
        session.add(check("3", today, ID_CONFIRMED))
        # Never gone.
        session.add(check("4", today, ID_CONFIRMED))
        session.commit()

        new_gone, back = today_at_a_glance(findings(session, "douyin"), day=today)

    assert (new_gone, back) == (1, 1)


def test_a_video_that_never_disappeared_is_not_a_comeback(db):
    """Otherwise every alive video would count as one every day."""
    from datetime import datetime

    from app.db import SessionLocal
    from app.models import LinkCheck
    from app.recheck import ID_CONFIRMED
    from app.survival import findings, today_at_a_glance

    today = datetime(2026, 9, 25, 12, 0)
    with SessionLocal() as session:
        session.add(LinkCheck(
            platform="douyin", video_id="9", target_kind="video",
            url="https://www.douyin.com/video/9", http_status=200,
            evidence=ID_CONFIRMED, checked_at=today,
        ))
        session.commit()
        assert today_at_a_glance(findings(session, "douyin"), day=today) == (0, 0)


def test_a_reinstated_video_still_shows_when_it_was_gone(client, api_key):
    """The row read "alive", First gone empty, as if nothing happened.

    `first_gone_at` is cleared by the check that finds a video
    watchable again -- right for deciding whether it is gone now, and
    wrong for the table whose subject is removals. A real video,
    7688128619269629350, was found gone and came back, and the page
    showed no trace of it.
    """
    from datetime import datetime

    from app.db import SessionLocal
    from app.models import LinkCheck
    from app.recheck import ID_CONFIRMED, SERVED_ANOTHER

    with SessionLocal() as session:
        for when, evidence in [
            (datetime(2026, 9, 23, 13, 38), SERVED_ANOTHER),
            (datetime(2026, 9, 24, 22, 45), ID_CONFIRMED),
        ]:
            session.add(LinkCheck(
                platform="douyin",
                video_id="7688128619269629350",
                target_kind="video",
                url="https://www.douyin.com/video/7688128619269629350",
                http_status=200,
                evidence=evidence,
                checked_at=when,
            ))
        session.commit()

    body = client.get("/dashboard/takedowns?key=test-admin-key&platform=douyin").text
    assert "7688128619269629350" in body
    assert "came back" in body
    assert "then back" in body
    # The date it disappeared, not a dash.
    assert "09-23" in body


def test_a_comeback_is_news_on_one_day_only(db):
    """It was reported as today's news on every later day.

    "Came back today" was computed from `last_alive_at`, which moves
    forward on every check a video survives. So one comeback -- a
    single real event, 7688128619269629350 on 25 September -- would
    have been reported as having happened today, every day, for the
    rest of the study. A state dressed up as an event.
    """
    from datetime import datetime

    from app.db import SessionLocal
    from app.models import LinkCheck
    from app.recheck import ID_CONFIRMED, SERVED_ANOTHER
    from app.survival import findings, today_at_a_glance

    gone_on = datetime(2026, 9, 23, 17, 37)
    back_on = datetime(2026, 9, 25, 16, 29)
    later = datetime(2026, 9, 26, 16, 0)

    with SessionLocal() as session:
        for when, evidence in [
            (datetime(2026, 9, 22, 10, 0), ID_CONFIRMED),
            (gone_on, SERVED_ANOTHER),
            (back_on, ID_CONFIRMED),
            (later, ID_CONFIRMED),
        ]:
            session.add(LinkCheck(
                platform="douyin",
                video_id="7688128619269629350",
                target_kind="video",
                url="https://www.douyin.com/video/7688128619269629350",
                http_status=200,
                evidence=evidence,
                checked_at=when,
            ))
        session.commit()

        found = findings(session, "douyin")
        assert found[0].came_back_at == back_on

        # News on the day it happened.
        assert today_at_a_glance(found, day=back_on) == (0, 1)
        # And not on the days after, however long it stays up.
        assert today_at_a_glance(found, day=later) == (0, 0)


def test_the_day_s_news_is_the_researcher_s_day_not_utc_s():
    """A pass run at 22:00 in Boston is 02:00 tomorrow in UTC.

    Everything stored is UTC, which is right. Bucketing by UTC is not:
    a Douyin pass run last night reported its removals under today,
    and the evening's work vanished from the day it was done. Worse
    for a daily series, one local day's removals split across two UTC
    buckets depending on whether the pass ran in the morning or after
    dinner -- a difference in when the researcher sat down, showing up
    as a difference in the data.
    """
    from datetime import datetime

    from app.survival import Finding, today_at_a_glance

    # 2026-09-27 02:00 UTC is 2026-09-26 22:00 in New York.
    last_night = datetime(2026, 9, 27, 2, 0)
    # 2026-09-27 13:00 UTC is 2026-09-27 09:00 in New York: a different
    # local day, and in UTC the same one.
    this_morning = datetime(2026, 9, 27, 13, 0)

    def gone_at(video_id, moment):
        return Finding(
            video_id=video_id,
            platform="douyin",
            author_handle=None,
            url=f"https://www.douyin.com/video/{video_id}",
            checks=2,
            uninformative=0,
            first_checked_at=moment,
            last_checked_at=moment,
            last_alive_at=None,
            current="gone",
            outcome="gone",
            first_gone_at=moment,
        )

    evening = gone_at("1", last_night)
    morning = gone_at("2", this_morning)

    assert today_at_a_glance([evening, morning], day=last_night) == (1, 0)
    assert today_at_a_glance([evening, morning], day=this_morning) == (1, 0)


def test_a_page_that_says_the_video_is_gone_is_a_removal(session, tmp_path):
    """A whole kind of removal was being filed as an unreadable page.

    Douyin answers some removed videos by handing over the next
    recommended one -- that is the signal this study was built on --
    and others with a page that says "你要观看的视频不存在". The second
    leaves no record to parse, so the pass called it "HTTP 200:
    nothing readable" and recorded no check at all. Two hundred and
    fifty-two of those in one night.
    """
    from app.models import LinkCheck
    from app.recheck import PAGE_SAYS_GONE

    empty = Fetched(
        url="x",
        html="<div>你要观看的视频不存在</div>",
        http_status=200,
        payloads=[],
        missing=True,
    )

    outcome, said, kept = one(
        session,
        read=lambda url: empty,
        download=lambda address, referer: (MP4, 200),
        video_id="7686528190130806202",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
    )

    assert outcome == "gone"
    check = session.query(LinkCheck).one()
    assert check.evidence == PAGE_SAYS_GONE
    assert check.video_id == "7686528190130806202"


def test_a_page_that_says_nothing_is_still_only_unreadable(session, tmp_path):
    """Silence is not evidence of removal, and must not be counted as one."""
    quiet = Fetched(url="x", html="<div>…</div>", http_status=200, payloads=[])

    outcome, said, kept = one(
        session,
        read=lambda url: quiet,
        download=lambda address, referer: (MP4, 200),
        video_id="7686528190130806203",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
    )

    assert outcome == "unreadable"


def test_a_visit_that_read_nothing_is_still_recorded_as_a_visit(session, tmp_path):
    """"We did not look" and "we looked and saw nothing" are not the same.

    They were indistinguishable: a page that came back empty wrote no
    check at all, so the row kept yesterday's time and read as a day
    the study had skipped. Two posts that were alive and open fine in
    a browser sat there looking neglected.

    It is recorded as telling us nothing -- never as a sighting, which
    would fabricate survival.
    """
    from app.models import LinkCheck
    from app.recheck import NOTHING_READ, UNKNOWN, classify

    quiet = Fetched(url="x", html="<div>…</div>", http_status=200, payloads=[])

    outcome, said, kept = one(
        session,
        read=lambda url: quiet,
        download=lambda address, referer: (MP4, 200),
        video_id="7691661533974593265",
        site=SITES["douyin_note"],
        handle=None,
        directory=tmp_path,
    )

    assert outcome == "unreadable"
    check = session.query(LinkCheck).one()
    assert check.evidence == NOTHING_READ
    assert classify(check) == UNKNOWN
