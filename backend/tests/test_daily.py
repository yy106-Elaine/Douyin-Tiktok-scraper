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
