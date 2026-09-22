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
