"""Fetching video and profile pages, and what the dashboard does with them."""
from __future__ import annotations

import json

from app.db import SessionLocal
from app.douyin_page import Fetched
from app.models import SharedLink, WebAuthor, WebVideo
from app import fetch_authors, fetch_videos

_SEC_UID = "MS4wLjABAAAAQ3osBXG0LqnkGyPJZ11GS"


def _page(payload: dict) -> str:
    return f"<script>window._ROUTER_DATA = {json.dumps(payload, ensure_ascii=False)};</script>"


def _video_page(video_id: str, **over) -> str:
    record = {
        "aweme_id": video_id,
        "desc": over.get("desc", "再来一次 我不会再与你相恋#wlw"),
        "create_time": 1789917000,
        "author": {
            "nickname": over.get("nickname", "35"),
            "sec_uid": _SEC_UID,
            "unique_id": "",
        },
        "statistics": {
            "digg_count": over.get("digg", 0),
            "comment_count": 0,
            "share_count": 2,
            "collect_count": 1,
        },
    }
    return _page({"item_list": [record]})


def _link(client, api_key, slug, video_id, author="35", caption="#wlw"):
    client.post(
        "/api/links/shared",
        json={
            "raw_text": (
                f"5.61 复制打开抖音，看看【{author}的作品】{caption} "
                f"https://v.douyin.com/{slug}/ :8p"
            ),
            "shared_at": "2026-09-20T23:45:00Z",
        },
        headers={"X-API-Key": api_key},
    )
    with SessionLocal() as session:
        link = (
            session.query(SharedLink)
            .filter(SharedLink.raw_text.contains(f"/{slug}/"))
            .one()
        )
        link.video_id = video_id
        session.commit()


def test_only_links_whose_page_has_not_been_read_are_wanted(client, api_key):
    _link(client, api_key, "a", "7687820515369510629")
    _link(client, api_key, "b", "7687818847273685937")

    with SessionLocal() as session:
        assert len(fetch_videos.wanted(session)) == 2

        fetch_videos.run(
            session,
            ["7687820515369510629"],
            pause_seconds=0,
            fetcher=lambda video_id: Fetched(
                url=video_id, html=_video_page(video_id), http_status=200
            ),
        )
        # The one already read drops out; --refresh brings it back.
        assert fetch_videos.wanted(session) == ["7687818847273685937"]
        assert len(fetch_videos.wanted(session, refresh=True)) == 2


def test_what_the_page_said_is_stored_against_the_id_in_its_address(client, api_key):
    _link(client, api_key, "a", "7687820515369510629")

    with SessionLocal() as session:
        report = fetch_videos.run(
            session,
            ["7687820515369510629"],
            pause_seconds=0,
            fetcher=lambda video_id: Fetched(
                url=video_id, html=_video_page(video_id), http_status=200
            ),
        )
        assert report["read"] == 1

        row = session.query(WebVideo).one()
        assert row.video_id == "7687820515369510629"
        assert row.author_name == "35"
        assert row.sec_uid == _SEC_UID
        assert row.share_count == 2
        assert row.like_count == 0
        assert row.parsed_by == "embedded"
        assert row.error is None


def test_a_page_that_cannot_be_read_is_recorded_as_such(client, api_key):
    """Not left looking like one that was never tried."""
    _link(client, api_key, "a", "7687820515369510629")

    with SessionLocal() as session:
        report = fetch_videos.run(
            session,
            ["7687820515369510629"],
            pause_seconds=0,
            fetcher=lambda video_id: Fetched(url=video_id, http_status=403, error="HTTPError"),
        )
        assert report["unreadable"] == 1
        row = session.query(WebVideo).one()
        assert row.error == "HTTPError"
        assert row.http_status == 403
        assert row.caption is None
        # Still wanted, because it was never actually read.
        assert fetch_videos.wanted(session) == ["7687820515369510629"]


def test_the_profile_pass_visits_each_account_once(client, api_key):
    _link(client, api_key, "a", "7687820515369510629")
    _link(client, api_key, "b", "7687818847273685937")

    profile = _page(
        {
            "user": {
                "nickname": "35",
                "sec_uid": _SEC_UID,
                "unique_id": "70056222078",
                "ip_location": "湖南",
                "follower_count": 1,
            }
        }
    )

    with SessionLocal() as session:
        for video_id in ("7687820515369510629", "7687818847273685937"):
            fetch_videos.run(
                session,
                [video_id],
                pause_seconds=0,
                fetcher=lambda wanted: Fetched(
                    url=wanted, html=_video_page(wanted), http_status=200
                ),
            )
        # Two videos, one account.
        assert fetch_authors.wanted(session) == [_SEC_UID]

        visits = []
        report = fetch_authors.run(
            session,
            [_SEC_UID],
            pause_seconds=0,
            fetcher=lambda sec_uid: visits.append(sec_uid)
            or Fetched(url=sec_uid, html=profile, http_status=200),
        )
        assert report["with_handle"] == 1
        assert len(visits) == 1
        assert session.query(WebAuthor).one().author_handle == "70056222078"


def test_the_page_overrules_the_screen_on_the_dashboard(client, api_key):
    """Both are observations; only one is attached to the id by address."""
    _link(
        client,
        api_key,
        "a",
        "7687820515369510629",
        author="错的名字",
        caption="错的文案",
    )

    with SessionLocal() as session:
        fetch_videos.run(
            session,
            ["7687820515369510629"],
            pause_seconds=0,
            fetcher=lambda video_id: Fetched(
                url=video_id, html=_video_page(video_id), http_status=200
            ),
        )
        fetch_authors.run(
            session,
            [_SEC_UID],
            pause_seconds=0,
            fetcher=lambda sec_uid: Fetched(
                url=sec_uid,
                html=_page(
                    {
                        "user": {
                            "nickname": "35",
                            "sec_uid": _SEC_UID,
                            "unique_id": "70056222078",
                        }
                    }
                ),
                http_status=200,
            ),
        )

    body = client.get("/dashboard?key=test-admin-key&platform=douyin").text
    assert "再来一次 我不会再与你相恋#wlw" in body
    assert "错的文案" not in body
    assert "70056222078" in body      # the 抖音号, from the profile
    assert "read from the page" in body
    assert "from the page" in body    # the publication time's provenance


class _FakeBrowser:
    """A browser that meets a verification page once, then answers."""

    def __init__(self, html: str, walls: int = 0) -> None:
        self.html = html
        self.walls = walls
        self.visits: list[str] = []
        self.waits = 0

    def read(self, url: str, settle_seconds: float = 0.0):
        from app.browser import PageRead

        self.visits.append(url)
        if self.walls:
            self.walls -= 1
            return PageRead(Fetched(url=url, html="请完成验证", http_status=200), wall=True)
        return PageRead(Fetched(url=url, html=self.html, http_status=200))

    def wait_for_person(self, message: str) -> None:
        self.waits += 1


def test_the_browser_reads_the_sites_own_page(client, api_key):
    browser = _FakeBrowser(_video_page("7687820515369510629"))
    read = fetch_videos.through(browser)

    page = read("7687820515369510629")

    assert browser.visits == ["https://www.douyin.com/video/7687820515369510629"]
    assert "再来一次" in page.html


def test_a_verification_page_waits_for_a_person_and_then_retries(client, api_key):
    """Hammering a challenge is how a session becomes a block."""
    browser = _FakeBrowser(_video_page("7687820515369510629"), walls=1)
    read = fetch_videos.through(browser, on_wall=browser.wait_for_person)

    page = read("7687820515369510629")

    assert browser.waits == 1
    assert len(browser.visits) == 2
    assert "再来一次" in page.html


def test_without_someone_to_ask_the_wall_is_recorded_not_retried(client, api_key):
    browser = _FakeBrowser(_video_page("7687820515369510629"), walls=1)
    read = fetch_videos.through(browser, on_wall=None)

    page = read("7687820515369510629")

    assert len(browser.visits) == 1
    assert "验证" in page.html


def test_the_profile_pass_uses_the_browser_too(client, api_key):
    profile = _page(
        {"user": {"nickname": "35", "sec_uid": _SEC_UID, "unique_id": "70056222078"}}
    )
    browser = _FakeBrowser(profile)

    page = fetch_authors.through(browser)(_SEC_UID)

    assert browser.visits == [f"https://www.douyin.com/user/{_SEC_UID}"]
    assert "70056222078" in page.html
