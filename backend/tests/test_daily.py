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
