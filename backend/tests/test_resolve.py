"""Resolving a copied short link into a video id.

"Copy link" gives `v.douyin.com/XXXX` or `vm.tiktok.com/XXXX`: neither
carries the id, both redirect to a URL that does. The redirect follower
is injected, so this exercises the logic without the network.
"""

import urllib.error

from app.db import SessionLocal
from app.models import SharedLink, TikTokPost
from app.resolve import resolve_pending

_CAPTURE = {
    "platform_package": "com.zhiliaoapp.musically",
    "fingerprint": "fp-1",
    "captured_at": "2026-09-14T12:00:00Z",
    "payload": {"author_name": "someuser", "caption": "hello world"},
}


def _capture(client, api_key):
    return client.post(
        "/api/captures/batch",
        json={"device_id": "pixel-7a", "captures": [_CAPTURE]},
        headers={"X-API-Key": api_key},
    )


def _copy_link(client, api_key, text, fingerprint="fp-1"):
    return client.post(
        "/api/links/shared",
        json={
            "raw_text": text,
            "shared_at": "2026-09-14T12:00:30Z",
            "fingerprint": fingerprint,
        },
        headers={"X-API-Key": api_key},
    )


def test_a_short_link_resolves_and_pairs(client, api_key):
    _capture(client, api_key)
    body = _copy_link(
        client, api_key, "7.86 复制打开抖音 https://v.douyin.com/iRkQwBt/ 复制此链接"
    ).json()
    assert body["video_id"] is None
    assert body["needs_resolution"] is True

    def follower(url: str) -> str:
        assert url == "https://v.douyin.com/iRkQwBt/"
        return "https://www.douyin.com/video/7123456789012345678?extra=1"

    with SessionLocal() as session:
        report = resolve_pending(session, follower=follower, pause_seconds=0)

    assert report.resolved == 1
    with SessionLocal() as session:
        link = session.query(SharedLink).one()
        assert link.video_id == "7123456789012345678"
        assert link.canonical_url == "https://www.douyin.com/video/7123456789012345678"


def test_resolution_reaches_the_captured_post(client, api_key):
    _capture(client, api_key)
    _copy_link(client, api_key, "https://vm.tiktok.com/ZMabc123/")

    def follower(_: str) -> str:
        return "https://www.tiktok.com/@someuser/video/7301234567890123456"

    with SessionLocal() as session:
        report = resolve_pending(session, follower=follower, pause_seconds=0)

    assert report.paired == 1
    with SessionLocal() as session:
        post = session.query(TikTokPost).one()
        assert post.video_id == "7301234567890123456"
        assert post.video_url == (
            "https://www.tiktok.com/@someuser/video/7301234567890123456"
        )


def test_the_handle_from_a_resolved_url_is_kept(client, api_key):
    # The feed only shows a display name; the resolved URL carries the
    # handle, which is what makes an author contactable.
    _capture(client, api_key)
    _copy_link(client, api_key, "https://vm.tiktok.com/ZMabc123/")

    with SessionLocal() as session:
        resolve_pending(
            session,
            follower=lambda _: "https://www.tiktok.com/@realhandle/video/7301234567890123456",
            pause_seconds=0,
        )
        assert session.query(SharedLink).one().author_handle == "realhandle"


def test_an_unreachable_link_stays_pending(client, api_key):
    _copy_link(client, api_key, "https://v.douyin.com/broken/")

    def follower(_: str) -> str:
        raise urllib.error.URLError("no route to host")

    with SessionLocal() as session:
        report = resolve_pending(session, follower=follower, pause_seconds=0)

    assert report.failed == 1
    with SessionLocal() as session:
        # Left for the next run rather than written off.
        assert session.query(SharedLink).one().video_id is None


def test_a_redirect_that_yields_no_id_is_a_failure_not_a_wrong_id(client, api_key):
    _copy_link(client, api_key, "https://v.douyin.com/gone/")

    with SessionLocal() as session:
        report = resolve_pending(
            session,
            follower=lambda _: "https://www.douyin.com/?recommend=1",
            pause_seconds=0,
        )

    assert report.resolved == 0
    assert report.failed == 1


def test_already_resolved_links_are_not_refetched(client, api_key):
    _capture(client, api_key)
    _copy_link(
        client, api_key, "https://www.tiktok.com/@someuser/video/7301234567890123456"
    )

    calls = []

    with SessionLocal() as session:
        report = resolve_pending(
            session,
            follower=lambda url: calls.append(url) or url,
            pause_seconds=0,
        )

    assert calls == []
    assert report.attempted == 0


def test_each_link_reports_as_it_is_settled(client, api_key):
    """A run of a few hundred links is minutes long; silence reads as a hang."""
    _capture(client, api_key)
    _copy_link(client, api_key, "https://v.douyin.com/iRkQwBt/")
    _copy_link(client, api_key, "https://v.douyin.com/bad/", fingerprint="fp-2")

    def follower(url: str) -> str:
        if url.endswith("/bad/"):
            raise urllib.error.URLError("nope")
        return "https://www.douyin.com/video/7123456789012345678"

    seen: list[tuple[int, int, str]] = []
    with SessionLocal() as session:
        resolve_pending(
            session,
            follower=follower,
            pause_seconds=0,
            on_progress=lambda done, total, outcome: seen.append(
                (done, total, outcome)
            ),
        )

    assert [(done, total) for done, total, _ in seen] == [(1, 2), (2, 2)]
    assert "7123456789012345678" in seen[0][2]
    assert seen[1][2] == "could not be followed"


def test_many_links_to_one_video_all_resolve(client, api_key):
    """One video, copied over and over, is what this collection does.

    When a day's search results run out the feed stops advancing and
    the loop keeps copying whatever is on screen: 晒月亮, shares 3,629,
    took 130 links in a single run. Two guards were written against
    that shape on the theory that a repeated id meant Douyin had
    started redirecting everything to one fallback page. It had not,
    and the second guard deadlocked every pass -- the queue is walked
    in the same order each time, so a refusal at the head never
    clears.
    """
    for slug in ("a", "b", "c", "d", "e", "f", "g"):
        _copy_link(
            client, api_key, f"https://v.douyin.com/{slug}/", fingerprint=f"fp-{slug}"
        )

    spun_on = "7686479376405819109"
    landing = {
        "a": spun_on,
        "b": spun_on,
        "c": spun_on,
        "d": spun_on,
        "e": "7686913835698122345",
        "f": spun_on,
        "g": "7686886744431564474",
    }

    def follower(url: str) -> str:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return f"https://www.iesdouyin.com/share/video/{landing[slug]}/"

    with SessionLocal() as session:
        report = resolve_pending(session, follower=follower, pause_seconds=0)

    assert report.resolved == 7
    with SessionLocal() as session:
        held = [
            link.video_id for link in session.query(SharedLink).all() if link.video_id
        ]
        assert held.count(spun_on) == 5
