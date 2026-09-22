"""Keeping a copy of the video file itself."""
from __future__ import annotations

from pathlib import Path

from app import download_videos
from app.db import SessionLocal
from app.douyin_page import Fetched, file_urls
from app.models import WebVideo


_MP4 = b"\x00\x00\x00\x18" + b"ftyp" + b"isom" + b"\x00" * 200_000


def _record(video_id: str, url: str) -> dict:
    return {
        "aweme_detail": {
            "aweme_id": video_id,
            "desc": "#wlw",
            "video": {"play_addr": {"url_list": [url]}},
        }
    }


class _FakeBrowser:
    def __init__(self, payloads, files, wall=False):
        self.payloads = payloads
        self.files = files
        self.wall = wall
        self.asked: list[str] = []

    def read(self, url, settle_seconds=0.0):
        from app.browser import PageRead

        return PageRead(
            Fetched(url=url, html="<html></html>", http_status=200,
                    payloads=self.payloads),
            wall=self.wall,
        )

    def download(self, url, referer=None, timeout_ms=0):
        self.asked.append(url)
        return self.files.get(url, (None, 404))


def test_the_file_addresses_come_out_of_the_record():
    payloads = [_record("7688128736507805041", "https://cdn/a.mp4")]
    assert file_urls(payloads) == ["https://cdn/a.mp4"]


def test_a_record_about_another_video_offers_no_address():
    """The guard that keeps someone else's footage out of the folder.

    Douyin answers a request for a removed video by serving the next
    recommended one. Its addresses work perfectly well -- they are
    just not this video, and a file saved under this id would be
    indistinguishable from the real thing later.
    """
    payloads = [_record("7686999999999999999", "https://cdn/someone-else.mp4")]
    assert file_urls(payloads, video_id="7688128736507805041") == []


def test_an_error_page_is_not_saved_as_a_video():
    """The silent failure this exists to stop.

    A media URL fetched without the right session answers 200 with a
    short body. Written to disk it gives a folder that looks complete
    and a corpus that is not.
    """
    assert not download_videos.looks_like_video(b'{"status_code":10000}')
    assert not download_videos.looks_like_video(b"<html>403</html>" * 50)
    assert download_videos.looks_like_video(_MP4)


def test_a_video_is_written_and_recorded(db, tmp_path: Path):
    url = "https://cdn/a.mp4"
    video_id = "7688128736507805041"
    browser = _FakeBrowser([_record(video_id, url)], {url: (_MP4, 200)})

    with SessionLocal() as session:
        session.add(WebVideo(video_id=video_id, caption="#wlw"))
        session.commit()
        rows = download_videos.wanted(session)
        report = download_videos.run(session, rows, tmp_path, browser, pause_seconds=0)

        assert report["saved"] == 1
        written = tmp_path / f"{video_id}.mp4"
        assert written.read_bytes() == _MP4

        row = session.query(WebVideo).one()
        assert row.local_path == str(written)
        assert row.file_bytes == len(_MP4)
        assert len(row.file_sha256) == 64
        assert row.download_error is None

        # Held now, so a second pass asks for nothing.
        assert download_videos.wanted(session) == []
        # And no half-written file is left behind.
        assert list(tmp_path.glob("*.part")) == []


def test_a_row_whose_file_has_gone_missing_comes_back(db, tmp_path: Path):
    """The folder may be moved or cleaned; the fix is to run again."""
    with SessionLocal() as session:
        session.add(
            WebVideo(
                video_id="7688128736507805041",
                local_path=str(tmp_path / "not-there.mp4"),
                file_bytes=200_000,
            )
        )
        session.commit()
        assert len(download_videos.wanted(session)) == 1


def test_a_download_that_fails_is_recorded_not_lost(db, tmp_path: Path):
    url = "https://cdn/a.mp4"
    video_id = "7688128736507805041"
    # The URL answers, but with an error page rather than a video.
    browser = _FakeBrowser([_record(video_id, url)], {url: (b"nope", 200)})

    with SessionLocal() as session:
        session.add(WebVideo(video_id=video_id))
        session.commit()
        report = download_videos.run(
            session, download_videos.wanted(session), tmp_path, browser, pause_seconds=0
        )
        assert report["failed"] == 1
        assert list(tmp_path.glob("*.mp4")) == []
        row = session.query(WebVideo).one()
        assert row.local_path is None
        assert "not a video" in row.download_error


def test_the_manifest_lists_what_is_held(db, tmp_path: Path):
    with SessionLocal() as session:
        session.add(
            WebVideo(
                video_id="7688128736507805041",
                author_name="35",
                caption="再来一次\n我不会再与你相恋#wlw",
                local_path=str(tmp_path / "7688128736507805041.mp4"),
                file_bytes=200_000,
                file_sha256="a" * 64,
            )
        )
        session.add(WebVideo(video_id="7000000000000000000"))  # not held
        session.commit()

        text = download_videos.write_manifest(session, tmp_path).read_text()
        assert "7688128736507805041" in text
        assert "7000000000000000000" not in text
        # The caption's newline must not break the row.
        assert len(text.strip().splitlines()) == 2


def test_a_record_with_no_id_of_its_own_offers_no_address():
    """"No id here" is not "this is the right video".

    A Douyin page carries a recommendation feed beside its own video,
    and some of those records do not name an id at their own level.
    Treating that as "no conflict" let a neighbour's addresses through
    on exactly the pages where the requested video was missing --
    which is the case the id check exists for.
    """
    anonymous = {"aweme_detail": {"video": {"play_addr": {"url_list": ["https://cdn/x.mp4"]}}}}
    assert file_urls([anonymous], video_id="7688128736507805041") == []
    # Still offered when no particular video was asked for.
    assert file_urls([anonymous]) == ["https://cdn/x.mp4"]


def _tiktok_record(video_id: str, url: str) -> dict:
    return {
        "itemInfo": {
            "itemStruct": {
                "id": video_id,
                "desc": "#Chineselesbian #wlw",
                "author": {"uniqueId": "rulebreaker2424"},
                "video": {"playAddr": url},
            }
        }
    }


def test_tiktok_videos_download_through_the_same_path(db, tmp_path):
    """One downloader, two sites.

    The guards are what took work -- the id check, the "is this
    actually a video" check, the digest -- so TikTok gets them by
    construction rather than by a second implementation.
    """
    from app import download_videos
    from app.fetch_videos import SITES

    url = "https://cdn.tiktok/play.mp4"
    video_id = "7687820515369510629"
    browser = _FakeBrowser([_tiktok_record(video_id, url)], {url: (_MP4, 200)})

    with SessionLocal() as session:
        session.add(
            WebVideo(
                video_id=video_id,
                platform="tiktok",
                author_handle="rulebreaker2424",
                caption="#Chineselesbian #wlw",
            )
        )
        session.add(WebVideo(video_id="7000000000000000000", platform="douyin"))
        session.commit()

        # Each platform's queue is its own.
        rows = download_videos.wanted(session, "tiktok")
        assert [row.video_id for row in rows] == [video_id]

        report = download_videos.run(
            session, rows, tmp_path, browser, pause_seconds=0,
            site=SITES["tiktok"],
        )
        assert report["saved"] == 1
        assert (tmp_path / f"{video_id}.mp4").read_bytes() == _MP4

        # Asked for by the address its own handle gives.
        assert browser.asked == [url]
        row = session.query(WebVideo).filter_by(video_id=video_id).one()
        assert len(row.file_sha256) == 64


def test_each_platform_keeps_its_own_folder_and_manifest(db, tmp_path):
    from app import download_videos

    with SessionLocal() as session:
        session.add(
            WebVideo(
                video_id="7687820515369510629",
                platform="tiktok",
                local_path=str(tmp_path / "tiktok" / "7687820515369510629.mp4"),
                file_bytes=200_000,
            )
        )
        session.add(
            WebVideo(
                video_id="7000000000000000000",
                platform="douyin",
                local_path=str(tmp_path / "douyin" / "7000000000000000000.mp4"),
                file_bytes=200_000,
            )
        )
        session.commit()

        tiktok = download_videos.write_manifest(
            session, tmp_path / "tiktok", "tiktok"
        ).read_text()
        assert "7687820515369510629" in tiktok
        assert "7000000000000000000" not in tiktok
        # And the watch URL is that platform's, not the other's.
        assert "tiktok.com" in tiktok

    assert download_videos.default_dir("tiktok").name == "tiktok"
    assert download_videos.default_dir("douyin").parent == (
        download_videos.default_dir("tiktok").parent
    )
